"""向量存储（MemoryVectorStore）单元测试.

覆盖:
- add/search/count 基本行为。
- 检索按相似度降序、threshold 过滤。
- 元数据与文本数量不匹配校验。
- 工厂 create_vector_store 的可切换入口。
"""

from __future__ import annotations

import pytest

from src.llm.vector_store import MemoryVectorStore, create_vector_store


class TestMemoryVectorStoreBasic:
    """基本写入与检索."""

    def test_add_and_count(self) -> None:
        store = MemoryVectorStore()
        assert store.count() == 0
        n = store.add(["a", "b", "c"])
        assert n == 3
        assert store.count() == 3

    def test_add_with_metadata(self) -> None:
        store = MemoryVectorStore()
        store.add(
            ["CUDA out of memory 调小 batch size", "排队等资源"],
            [{"faq_id": "faq-003"}, {"faq_id": "faq-006"}],
        )
        hits = store.search("显存不足 OOM", top_k=3)
        assert hits
        assert hits[0].metadata.get("faq_id") == "faq-003"

    def test_search_empty_store(self) -> None:
        store = MemoryVectorStore()
        assert store.search("anything") == []

    def test_metadata_mismatch_raises(self) -> None:
        store = MemoryVectorStore()
        with pytest.raises(ValueError):
            store.add(["a", "b"], [{"faq_id": "x"}])

    def test_search_returns_top_k(self) -> None:
        store = MemoryVectorStore()
        store.add(
            ["GPU OOM 调小 batch", "排队 pending 等待", "conda 未激活", "sbatch 提交"],
        )
        hits = store.search("GPU OOM", top_k=2)
        assert len(hits) == 2


class TestMemoryVectorStoreThreshold:
    """threshold 过滤与排序."""

    def test_threshold_filters_low_score(self) -> None:
        store = MemoryVectorStore()
        store.add(["GPU OOM 显存不足", "作业排队 等待资源"])
        # 高阈值应把不相关项过滤掉
        hits = store.search("GPU OOM", top_k=5, threshold=1.0)
        assert all(c.score >= 1.0 for c in hits)
        # 阈值降为 0 应包含更多
        hits0 = store.search("GPU OOM", top_k=5, threshold=0.0)
        assert len(hits0) >= len(hits)

    def test_sorted_descending(self) -> None:
        store = MemoryVectorStore()
        store.add(["GPU OOM 显存不足怎么解决", "conda 环境安装", "sbatch 提交作业"])
        hits = store.search("GPU OOM 显存不足 怎么解决", top_k=5)
        scores = [h.score for h in hits]
        assert scores == sorted(scores, reverse=True)


class TestVectorStoreFactory:
    """工厂入口."""

    def test_factory_returns_memory_store(self) -> None:
        store = create_vector_store()
        assert isinstance(store, MemoryVectorStore)

    def test_factory_roundtrip(self) -> None:
        store = create_vector_store()
        store.add(["hello"], [{"id": 1}])
        assert store.count() == 1
