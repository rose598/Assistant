"""RAG 引擎（检索 + 增强，mock 先行）。

第 3 周周四交付物（A 职责）：把"检索"与"Prompt 增强"封装为独立组件，
对齐 RAG 架构文档 §3.3 的 ``RagEngine`` 契约，供上层(integrated_qa)调用。

分工边界（plan §2.3）：B 负责检索端（embdedding 真实化 / 向量库 / 高质量检索）；
本模块提供可替换的默认实现(基于现有 ``MemoryVectorStore`` + ``MockEmbedder``)，
B 到位后只需替换 ``RagEngine`` 的检索实现，A 的 generate 逻辑不变。

职责：
- ``retrieve``: 给定 query 返回 top-k 检索命中。
- ``augment``: 把检索知识 + 对话历史 + 当前 query 组装成 OpenAI 风格 messages。

generate(调 LLM) 由调用方(IntegratedQA)完成，保持检索与生成的解耦。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from src.llm.prompts import RAG_TEMPLATE
from src.llm.vector_store import RetrievedChunk, VectorStore, create_vector_store


@dataclass
class RagConfig:
    """RAG 可调参数。"""

    top_k: int = 3
    no_hit_placeholder: str = "（无检索命中）"


def format_knowledge(chunks: Sequence[RetrievedChunk]) -> str:
    """把检索命中拼接为可读知识文本（带序号与来源标注）。"""
    parts = []
    for i, chunk in enumerate(chunks, start=1):
        ref = chunk.metadata.get("faq_id") or chunk.metadata.get("title") or ""
        prefix = f"[{i}]"
        if ref:
            prefix += f"({ref})"
        parts.append(f"{prefix} {chunk.text}")
    return "\n".join(parts)


def source_ids(chunks: Sequence[RetrievedChunk]) -> list[str]:
    """抽取检索命中的来源 id/标题（去空、保序）。"""
    return [chunk.metadata.get("faq_id") or chunk.metadata.get("title") or "" for chunk in chunks]


class RagEngine:
    """默认 RAG 引擎：检索 + Prompt 增强。

    可替换点：若 B 提供更优检索，可用同接口（retrieve/augment 不变）的实现替换，
    上层无需改动。
    """

    def __init__(
        self,
        vector_store: VectorStore | None = None,
        top_k: int = 3,
        no_hit_placeholder: str = "（无检索命中）",
    ) -> None:
        self.vector_store = vector_store if vector_store is not None else create_vector_store()
        self.top_k = top_k
        self.no_hit_placeholder = no_hit_placeholder
        self._config = RagConfig(top_k=top_k, no_hit_placeholder=no_hit_placeholder)

    def retrieve(self, query: str, top_k: int | None = None) -> list[RetrievedChunk]:
        """返回 top-k 检索命中（按相似度降序）。"""
        k = top_k if top_k is not None else self.top_k
        return self.vector_store.search(query, top_k=k)

    def augment(
        self,
        query: str,
        chunks: Sequence[RetrievedChunk],
        history: Sequence[dict[str, str]] | None = None,
    ) -> list[dict[str, str]]:
        """组装 OpenAI 风格 messages: system(含知识) + 历史旧轮 + 当前 query.

        ``history`` 约定含已记录的"本轮 user"在末尾，故取 ``[:-1]`` 避免与
        当前 query 重复；当前 query 作为最后一条 user 追加。
        """
        knowledge = format_knowledge(chunks) or self.no_hit_placeholder
        system_msg = RAG_TEMPLATE.render(question=query, knowledge=knowledge)[0]
        history = list(history or [])
        return [system_msg, *history[:-1], {"role": "user", "content": query}]


def create_rag_engine(
    vector_store: VectorStore | None = None,
    top_k: int = 3,
    no_hit_placeholder: str = "（无检索命中）",
) -> RagEngine:
    """工厂：创建默认 RAG 引擎。B 提供检索实现时替换此处返回。"""
    return RagEngine(
        vector_store=vector_store,
        top_k=top_k,
        no_hit_placeholder=no_hit_placeholder,
    )


__all__ = [
    "RagConfig",
    "RagEngine",
    "create_rag_engine",
    "format_knowledge",
    "source_ids",
]
