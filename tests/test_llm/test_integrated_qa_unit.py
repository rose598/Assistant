"""双通道问答（IntegratedQA）单元测试.

覆盖:
- 关键词通道：高置信命中直接返回（channel=keyword），低置信回退。
- RAG/LLM 通道：无关键词命中时走检索 + LLM（channel=rag）。
- 双通道都不可用 → fallback + needs_llm=True。
- 对话历史记录到 session_store。
- 关键词 matcher 协议兼容（含打包 AnswerPipeline 的适配器）。
"""

from __future__ import annotations

from src.dialog.store import MemorySessionStore
from src.llm.integrated_qa import AskResult, IntegratedQA, KeywordHit
from src.llm.vector_store import MemoryVectorStore


class _FakeLLMProto:
    """更贴近真实 LLMResponse 的返回(完整/流式均为异步)."""

    class Resp:
        def __init__(self, text: str) -> None:
            self.text = text

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, messages: list[dict[str, str]]) -> Resp:
        self.calls += 1
        return self.Resp("llm 兜底回答")


class _FakeMatcher:
    """可配置的关键词 matcher."""

    def __init__(self, hit: KeywordHit | None) -> None:
        self._hit = hit
        self.calls = 0

    def match(self, query: str) -> KeywordHit | None:
        self.calls += 1
        return self._hit


class TestKeywordChannel:
    """通道①关键词直回."""

    async def test_high_confidence_keyword_direct(self) -> None:
        hit = KeywordHit(
            answer="知识库答案", confidence=0.95, intent="error_diagnosis", sources=["faq-003"]
        )
        qa = IntegratedQA(
            keyword_matcher=_FakeMatcher(hit),
            llm=_FakeLLMProto(),
        )
        result = await qa.ask("sess", "CUDA out of memory")
        assert isinstance(result, AskResult)
        assert result.channel == "keyword"
        assert result.answer == "知识库答案"
        assert result.intent == "error_diagnosis"
        assert result.needs_llm is False

    async def test_low_confidence_falls_to_rag(self) -> None:
        # 低置信关键词 → 走 RAG/LLM
        hit = KeywordHit(answer="低置信答案", confidence=0.3)
        llm = _FakeLLMProto()
        qa = IntegratedQA(keyword_matcher=_FakeMatcher(hit), llm=llm)
        result = await qa.ask("sess", "帮我看下作业")
        assert result.channel == "rag"
        assert llm.calls == 1

    async def test_no_matcher_goes_to_rag(self) -> None:
        llm = _FakeLLMProto()
        qa = IntegratedQA(keyword_matcher=None, llm=llm)
        result = await qa.ask("sess", "作业报错")
        assert result.channel == "rag"
        assert result.answer.startswith("llm ")


class TestRagChannel:
    """通道②RAG + LLM."""

    async def test_uses_vector_knowledge(self) -> None:
        store = MemoryVectorStore()
        store.add(
            ["CUDA out of memory 时减小 batch size"],
            [{"faq_id": "faq-003"}],
        )
        llm = _FakeLLMProto()
        qa = IntegratedQA(vector_store=store, llm=llm)
        result = await qa.ask("sess", "CUDA out of memory 怎么办")
        assert result.channel == "rag"
        assert "faq-003" in result.sources

    async def test_rag_sources_from_metadata(self) -> None:
        store = MemoryVectorStore()
        store.add(["conda 未激活"], [{"faq_id": "faq-007"}])
        llm = _FakeLLMProto()
        qa = IntegratedQA(vector_store=store, llm=llm, top_k=3)
        result = await qa.ask("sess", "conda")
        assert "faq-007" in result.sources


class TestFallback:
    """双通道都不可用."""

    async def test_no_keyword_no_llm_fallback(self) -> None:
        qa = IntegratedQA(keyword_matcher=None, llm=None)
        result = await qa.ask("sess", "随便问点什么")
        assert result.channel == "fallback"
        assert result.needs_llm is True
        assert "未找到精确答案" in result.answer


class TestSessionRecording:
    """对话历史记录."""

    async def test_records_user_and_assistant(self) -> None:
        hit = KeywordHit(answer="答案", confidence=0.9)
        store = MemorySessionStore()
        qa = IntegratedQA(keyword_matcher=_FakeMatcher(hit), session_store=store)
        result = await qa.ask("s1", "作业排队怎么办")
        session = store.load("s1")
        assert session is not None
        msgs = session.get_messages()
        assert msgs[0]["role"] == "user" and msgs[0]["content"] == "作业排队怎么办"
        assert msgs[1]["role"] == "assistant" and msgs[1]["content"] == result.answer

    async def test_keyword_does_not_call_llm(self) -> None:
        hit = KeywordHit(answer="关键词答案", confidence=0.99)
        llm = _FakeLLMProto()
        qa = IntegratedQA(keyword_matcher=_FakeMatcher(hit), llm=llm)
        await qa.ask("s1", "怎么提交作业")
        assert llm.calls == 0


class TestAdapterCompat:
    """协议兼容：matcher 可用返回 KeywordHit 的任何实现."""

    async def test_duck_typed_matcher(self) -> None:
        class Adapter:
            def match(self, query: str) -> KeywordHit:
                return KeywordHit(
                    answer="来自 pipeline 的答案",
                    confidence=1.0,
                    sources=["faq-001"],
                )

        qa = IntegratedQA(keyword_matcher=Adapter(), llm=_FakeLLMProto())
        result = await qa.ask("s", "QOS 超时")
        assert result.channel == "keyword"
        assert result.sources == ["faq-001"]


class _RecordingLLM:
    """记录收到的 messages，验证多轮历史是否喂给 LLM."""

    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    async def complete(self, messages: list[dict[str, str]]) -> object:
        self.calls.append(messages)
        return type("R", (), {"text": "ok"})()


class TestRagHistory:
    """验证 RAG 通道把多轮历史喂给 LLM."""

    async def test_history_passed_to_llm(self) -> None:
        store = MemorySessionStore()
        llm = _RecordingLLM()
        qa = IntegratedQA(keyword_matcher=None, llm=llm, session_store=store)

        await qa.ask("s1", "我想训练一个ResNet")
        await qa.ask("s1", "把GPU改成2个")

        assert len(llm.calls) == 2
        second = llm.calls[1]
        contents = [m["content"] for m in second if m["role"] == "user"]
        # 第二轮应包含第一轮的提问(历史被合并), 且当前 query 在末尾
        # 注意: rewrite_query 会把英文小写(resnet/gpu), 故用低敏感比较
        assert any("训练一个" in c for c in contents)  # 第一轮历史出现
        assert contents and "改成2个" in contents[-1]  # 当前 query 在末尾

    async def test_no_history_without_store(self) -> None:
        llm = _RecordingLLM()
        qa = IntegratedQA(keyword_matcher=None, llm=llm, session_store=None)
        await qa.ask("s1", "第一轮")
        await qa.ask("s1", "第二轮")
        assert len(llm.calls) == 2
        second = llm.calls[1]
        user_msgs = [m for m in second if m["role"] == "user"]
        # 无 store 时只有当前 query, 不含旧轮
        assert len(user_msgs) == 1
        assert user_msgs[0]["content"] == "第二轮"
