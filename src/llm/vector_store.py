"""向量存储（mock 先行）。

第 3 周周四交付物（A 职责）：为 RAG 检索提供统一的向量库接口。

分工边界（plan §2.3 + RAG 架构文档 §3.2）：真实向量库（ChromaDB）由 B 负责。
本模块先提供：
- ``RetrievedChunk``：一条检索命中的统一结构
- ``VectorStore``：存取/检索协议（add/search/count）
- ``MemoryVectorStore``：基于现有 ``MockEmbedder`` + ``cosine_similarity`` 的内存实现，
  用于在 B 的向量库到位前打通检索链路（RAG 冷启动策略 R08：先关键词/内存，后真实）。
- ``create_vector_store`` 工厂：B 接入 ChromaDB 时只替换此处返回实现，上层不动。

分块约定：由调用方完成（chunk_size=256, overlap=32, 见 config），本模块只管存储与检索。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from src.llm.embedding import Embedder, cosine_similarity, create_embedder


@dataclass
class RetrievedChunk:
    """一条检索命中。"""

    text: str  # 命中文本/FAQ 回答
    metadata: dict[str, Any] = field(default_factory=dict)  # 如 {"faq_id": ..., "title": ...}
    score: float = 0.0  # 相似度 0~1


class VectorStore(Protocol):
    """向量库协议：写入文本并检索 top-k。"""

    def add(self, texts: Sequence[str], metadatas: Sequence[dict] | None = None) -> int:
        """写入文本及其元数据，返回写入条数。"""
        ...

    def search(self, query: str, top_k: int = 5, threshold: float = 0.0) -> list[RetrievedChunk]:
        """按 query 检索，返回降序 top-k 命中；低于 threshold 的剔除。"""
        ...

    def count(self) -> int:
        """当前库里条目数。"""
        ...


class MemoryVectorStore:
    """内存向量库：用 embedder 对文本向量化后做余弦检索。

    - 写入时惰性向量化并缓存，避免重复 embed。
    - ``search`` 用``cosine_similarity`` 排序，低于 ``threshold`` 的命中剔除。
    - 全部在内存 dict 中，仅用于开发/测试，B 到位后替换。
    """

    def __init__(self, embedder: Embedder | None = None) -> None:
        self._embedder = embedder if embedder is not None else create_embedder()
        self._texts: list[str] = []
        self._metadatas: list[dict[str, Any]] = []
        self._vectors: list[list[float]] = []
        self._matrix_cache: Any = None  # numpy 矩阵缓存, add 后失效

    def _try_numpy(self) -> Any:
        """惰性导入 numpy; 不可用返回 False(调用方回退纯 Python)."""
        if self._matrix_cache is None:
            try:
                import numpy

                self._matrix_cache = numpy.array(self._vectors, dtype=float)
            except Exception:
                self._matrix_cache = False  # 标记不可用
        return self._matrix_cache

    def add(self, texts: Sequence[str], metadatas: Sequence[dict] | None = None) -> int:
        items = list(texts)
        self._texts.extend(items)
        if metadatas is None:
            self._metadatas.extend({} for _ in items)
        else:
            meta = list(metadatas)
            if len(meta) != len(items):
                raise ValueError(f"texts 与 metadatas 数量不一致: {len(items)} vs {len(meta)}")
            self._metadatas.extend(meta)
        self._vectors.extend(self._embedder.embed_batch(items))
        self._matrix_cache = None  # 失效缓存
        return len(items)

    def search(self, query: str, top_k: int = 5, threshold: float = 0.0) -> list[RetrievedChunk]:
        if not self._texts:
            return []
        qvec = self._embedder.embed(query or "")
        scores = self._scores(qvec)
        scored = [
            RetrievedChunk(text=t, metadata=m, score=s)
            for t, m, s in zip(self._texts, self._metadatas, scores, strict=False)
            if s >= threshold
        ]
        scored.sort(key=lambda c: -c.score)
        return scored[:top_k]

    def _scores(self, qvec: list[float]) -> list[float]:
        """批量余弦相似度; 优先 numpy 向量化, 无 numpy 回退纯 Python."""
        matrix = self._try_numpy()
        if matrix is not False:
            import numpy

            q: Any = numpy.asarray(qvec, dtype=float)
            qn: Any = numpy.linalg.norm(q)
            if qn == 0:
                return [0.0] * len(self._texts)
            den: Any = numpy.linalg.norm(matrix, axis=1) * qn
            den = numpy.where(den == 0, 1.0, den)
            return [round(float(s), 4) for s in ((matrix @ q) / den)]

        # 纯 Python 回退
        return [round(cosine_similarity(qvec, vec), 4) for vec in self._vectors]

    def count(self) -> int:
        return len(self._texts)


def create_vector_store(config: Any | None = None) -> VectorStore:
    """工厂：创建向量库实现。

    当前返回 ``MemoryVectorStore``；B 接入 ChromaDB 时在此替换返回实现，
    上层无需改动。``config`` 预留（如 chroma 持久化路径）。
    """
    del config  # 预留 真实实现从配置读取 chroma 路径
    return MemoryVectorStore()


__all__ = [
    "MemoryVectorStore",
    "RetrievedChunk",
    "VectorStore",
    "create_vector_store",
]
