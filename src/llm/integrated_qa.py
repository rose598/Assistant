"""双通道问答（关键词直回 + RAG/LLM 兜底）。

第 3 周周四交付物（A 职责）：将已有知识库关键词匹配与 RAG + LLM 结合，
形成 plan §3.4 的双通道问答：
- ① 关键词通道：命中且置信度 >= ``threshold``（默认 0.8）→ 直接返回知识库答案，
  省去 LLM 调用（目标减少 LLM 调用量）。
- ② RAG、LLM 通道：未命中/低置信 → 从 ``vector_store`` 检索 top-k →
  组装 RAG Prompt → ``llm.complete`` 生成；若 LLM 不可用则回退为关键词提示。

设计要点：
- 依赖全部通过构造注入（keyword_matcher / vector_store / llm / session_store），
  便于单测与 B 到位后无痛替换。
- 对话：每次 ask 用 ``Session.add_message`` 记录 user/assistant，TTL 由 store 层管理。
- 与 RAG 架构文档 §3.4 的 ``IntegratedQA``/``AskResult`` 契约一致。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from src.llm.query_understanding import normalize_query, rewrite_query
from src.llm.rag_engine import RagEngine, create_rag_engine, source_ids
from src.llm.streaming import iter_token_text
from src.llm.vector_store import VectorStore, create_vector_store

DEFAULT_THRESHOLD = 0.8  # 关键词直回阈值(plan: 得分 > 0.8 直接回复)


@dataclass
class KeywordHit:
    """关键词通道的命中结果。"""

    answer: str
    confidence: float  # 0~1
    intent: str = "keyword"
    sources: list[str] = field(default_factory=list)  # 来源 FAQ id / 文档


class KeywordMatcher(Protocol):
    """关键词匹配通道协议（可包装现有 AnswerPipeline 或独立实现）。"""

    def match(self, query: str) -> KeywordHit | None:
        """匹配失败/低置信返回 None，供双通道回退到 RAG/LLM。"""
        ...


@dataclass
class AskResult:
    """一次双通道问答的返回。"""

    answer: str
    intent: str
    confidence: float
    channel: str  # "keyword" | "rag" | "fallback"
    sources: list[str] = field(default_factory=list)
    needs_llm: bool = False


class IntegratedQA:
    """双通道问答装配点。"""

    def __init__(
        self,
        keyword_matcher: KeywordMatcher | None = None,
        vector_store: VectorStore | None = None,
        rag_engine: RagEngine | None = None,
        llm: Any | None = None,
        session_store: Any | None = None,
        threshold: float = DEFAULT_THRESHOLD,
        top_k: int = 3,
    ) -> None:
        self.keyword_matcher = keyword_matcher
        self.vector_store = vector_store if vector_store is not None else create_vector_store()
        # RAG 引擎: 默认用现有内存向量库; B 提供检索时替换 rag_engine/vector_store 即可
        self.rag_engine = rag_engine or create_rag_engine(self.vector_store, top_k=top_k)
        self.llm = llm
        self.session_store = session_store
        self.threshold = threshold
        self.top_k = top_k

    # ---- 通道 ① 关键词 ----
    def _keyword_channel(self, query: str) -> AskResult | None:
        if self.keyword_matcher is None:
            return None
        hit = self.keyword_matcher.match(query)
        if hit is None or hit.confidence < self.threshold:
            return None
        return AskResult(
            answer=hit.answer,
            intent=hit.intent,
            confidence=round(hit.confidence, 4),
            channel="keyword",
            sources=hit.sources,
            needs_llm=False,
        )

    # ---- 通道 ② RAG + LLM ----
    async def _rag_channel(self, query: str, history: Sequence[dict[str, str]]) -> AskResult | None:
        if self.llm is None:
            return None
        chunks = self.rag_engine.retrieve(query, top_k=self.top_k)
        messages = self.rag_engine.augment(query, chunks, history)
        try:
            response = await self.llm.complete(messages)
        except Exception:
            # LLM 调用失败(网络/限流/超时): 降级为无 LLM 兜底, 不把异常抛给端点
            return None
        return AskResult(
            answer=response.text,
            intent="rag",
            confidence=0.5,  # 语义通道置信度占位, Day 5 由 confidence.py 细化
            channel="rag",
            sources=[s for s in source_ids(chunks) if s],
            needs_llm=False,
        )

    def _record(self, session_id: str, role: str, content: str) -> None:
        """记录对话历史到 store（若配置了 session_store）。"""
        if self.session_store is None:
            return
        session = self.session_store.load(session_id)
        if session is None:
            from src.dialog.session import Session

            session = Session(session_id)
        session.add_message(role, content)
        self.session_store.save(session)

    def _load_history(self, session_id: str) -> list[dict[str, str]]:
        """读取会话历史消息（含已记录的本轮 user），供喂给 LLM；无 store 时返回空。"""
        if self.session_store is None:
            return []
        session = self.session_store.load(session_id)
        if session is None:
            return []
        msgs = session.get_messages()
        return [{"role": m["role"], "content": m["content"]} for m in msgs]

    def _fallback(self) -> AskResult:
        """双通道都不可用时的回退提示."""
        return AskResult(
            answer="未找到精确答案（关键词匹配未命中，且 LLM 通道暂不可用）。"
            "请补充更多报错/作业信息，或稍后重试。",
            intent="unknown",
            confidence=0.0,
            channel="fallback",
            needs_llm=True,
        )

    @staticmethod
    def _normalize(query: str) -> tuple[str, str]:
        """返回 (关键词通道用原文, RAG 通道用改写后 query)."""
        original = normalize_query(query) or query
        rewritten = rewrite_query(query)
        return original, (rewritten if rewritten else original)

    async def ask(self, session_id: str, query: str, user_id: str = "") -> AskResult:
        """主入口：关键词 -> 兜底 RAG/LLM，并记录多轮历史。"""
        original, rag_query = self._normalize(query)
        self._record(session_id, "user", query)

        result = self._keyword_channel(original)
        if result is not None:
            self._record(session_id, "assistant", result.answer)
            return result

        history = self._load_history(session_id)
        result = await self._rag_channel(rag_query, history)
        if result is not None:
            self._record(session_id, "assistant", result.answer)
            return result

        fallback = self._fallback()
        self._record(session_id, "assistant", fallback.answer)
        return fallback

    async def ask_stream(self, session_id: str, query: str) -> Any:
        """流式主入口：产出文本片段(逐 token)，用于 SSE 输出。

        - 关键词高置信直回: 一次性 yield 完整答案。
        - RAG + LLM: 经 ``iter_token_text`` 逐 token yield；中途异常记录已产出部分。
        - 双通道都不可用: yield 回退提示。
        均在结束前把 assistant 回答写回会话历史。
        """
        original, rag_query = self._normalize(query)
        self._record(session_id, "user", query)

        hit = self._keyword_channel(original)
        if hit is not None:
            self._record(session_id, "assistant", hit.answer)
            yield hit.answer
            return

        if self.llm is not None:
            chunks = self.rag_engine.retrieve(rag_query, top_k=self.top_k)
            messages = self.rag_engine.augment(
                rag_query, chunks, self._load_history(session_id)
            )
            collected: list[str] = []
            try:
                async for token in iter_token_text(self.llm, messages):
                    collected.append(token)
                    yield token
            except Exception:
                # 流式中断(网络/限流): 已产出部分保留, 不发异常给端点
                pass
            if collected:
                self._record(session_id, "assistant", "".join(collected))
            return

        fallback = self._fallback()
        self._record(session_id, "assistant", fallback.answer)
        yield fallback.answer


__all__ = ["DEFAULT_THRESHOLD", "AskResult", "IntegratedQA", "KeywordHit", "KeywordMatcher"]
