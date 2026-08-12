"""RAG 引擎（RagEngine）单元测试.

覆盖:
- retrieve: 从向量库查回 top-k, 按相似度降序。
- augment: 组装 messages —— system(含检索知识) 在最前, 历史旧轮居中, 当前 query 垫底;
  system 里注入检索知识/占位符。
- 辅助: format_knowledge 带序号来源, source_ids 抽取来源。
"""

from __future__ import annotations

from src.llm.rag_engine import RagEngine, format_knowledge, source_ids
from src.llm.vector_store import MemoryVectorStore


class _FakeLLM:
    class Resp:
        def __init__(self, text: str) -> None:
            self.text = text

    async def complete(self, messages: list[dict[str, str]]) -> Resp:
        return self.Resp("ok")


def _store() -> MemoryVectorStore:
    s = MemoryVectorStore()
    s.add(
        ["CUDA out of memory 时减小 batch size", "conda 未激活时加 conda init"],
        [{"faq_id": "faq-003"}, {"faq_id": "faq-007"}],
    )
    return s


class TestRetrieve:
    def test_retrieve_topk(self) -> None:
        engine = RagEngine(vector_store=_store(), top_k=3)
        chunks = engine.retrieve("CUDA out of memory")
        assert chunks
        assert chunks[0].metadata.get("faq_id") == "faq-003"

    def test_retrieve_topk_limit(self) -> None:
        engine = RagEngine(vector_store=_store(), top_k=1)
        chunks = engine.retrieve("CUDA 显存不足 OOM")
        assert len(chunks) <= 1

    def test_retrieve_empty_store(self) -> None:
        engine = RagEngine(vector_store=MemoryVectorStore(), top_k=3)
        assert engine.retrieve("anything") == []


class TestAugment:
    def test_messages_shape(self) -> None:
        engine = RagEngine(vector_store=_store(), top_k=3)
        chunks = engine.retrieve("CUDA out of memory")
        msgs = engine.augment("CUDA out of memory 怎么办", chunks)
        assert msgs[0]["role"] == "system"
        assert "CUDA out of memory" in msgs[0]["content"]  # 知识注入
        assert msgs[-1]["role"] == "user" and "怎么办" in msgs[-1]["content"]

    def test_history_inserted_before_current(self) -> None:
        engine = RagEngine(vector_store=_store(), top_k=3)
        chunks = engine.retrieve("CUDA out of memory")
        history = [
            {"role": "user", "content": "帮我写训练脚本"},
            {"role": "assistant", "content": "好的"},
            {"role": "user", "content": "CUDA out of memory 怎么办"},
        ]
        msgs = engine.augment("CUDA out of memory 怎么办", chunks, history)
        # system 在最前
        assert msgs[0]["role"] == "system"
        # 历史旧轮(含 assistant 与上轮 user) 应出现
        roles = [m["role"] for m in msgs]
        assert roles.count("user") == 2  # 历史上轮 user + 当前 user
        contents = [m["content"] for m in msgs if m["role"] == "user"]
        assert "帮我写训练脚本" in contents  # 上轮历史保留
        assert contents[-1] == "CUDA out of memory 怎么办"  # 当前在末尾

    def test_no_hit_placeholder(self) -> None:
        engine = RagEngine(vector_store=_store(), top_k=3)
        msgs = engine.augment("完全无关的内容", [])
        assert "无检索命中" in msgs[0]["content"]


class TestHelpers:
    def test_format_knowledge_with_source(self) -> None:
        engine = RagEngine(vector_store=_store(), top_k=3)
        chunks = engine.retrieve("CUDA out of memory")
        text = format_knowledge(chunks)
        assert "[1]" in text and "faq-003" in text

    def test_source_ids_extract(self) -> None:
        engine = RagEngine(vector_store=_store(), top_k=3)
        chunks = engine.retrieve("CUDA out of memory")
        ids = source_ids(chunks)
        assert "faq-003" in ids
