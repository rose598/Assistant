"""向量嵌入（mock）单元测试.

验证：确定性、维度、余弦相似度、相似/不相似文本区分、空文本、批量。
"""

from __future__ import annotations

import math

from src.llm.embedding import (
    DEFAULT_DIM,
    MockEmbedder,
    cosine_similarity,
    create_embedder,
)


class TestMockEmbedder:
    """mock 向量化核心行为。"""

    def test_dimension(self) -> None:
        emb = MockEmbedder()
        v = emb.embed("废作业")
        assert len(v) == DEFAULT_DIM == 384

    def test_deterministic_same_text(self) -> None:
        emb = MockEmbedder()
        assert emb.embed("作业排队") == emb.embed("作业排队")

    def test_empty_text_returns_zero_vector(self) -> None:
        emb = MockEmbedder()
        v = emb.embed("")
        assert len(v) == DEFAULT_DIM
        assert all(x == 0.0 for x in v)

    def test_none_coerced_empty(self) -> None:
        emb = MockEmbedder()
        v = emb.embed(None)  # type: ignore[arg-type]
        assert all(x == 0.0 for x in v)

    def test_batch_matches_single(self) -> None:
        emb = MockEmbedder()
        batch = emb.embed_batch(["a", "b"])
        assert len(batch) == 2
        assert batch[0] == emb.embed("a")
        assert batch[1] == emb.embed("b")


class TestCosineSimilarity:
    """余弦相似度。"""

    def test_identical_is_1(self) -> None:
        v = [1.0, 0.0, 0.0]
        assert math.isclose(cosine_similarity(v, v), 1.0)

    def test_orthogonal_is_0(self) -> None:
        assert math.isclose(cosine_similarity([1.0, 0.0], [0.0, 1.0]), 0.0)

    def test_zero_vector_is_0(self) -> None:
        assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_dim_mismatch_is_0(self) -> None:
        assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0

    def test_similar_texts_higher_than_dissimilar(self) -> None:
        """共享 token 多的文本相似度应高于无关文本。"""
        emb = MockEmbedder()
        a = emb.embed("作业一直在排队 等待资源")
        b = emb.embed("作业一直排队 分配不到资源")
        c = emb.embed("显卡驱动安装 版本不匹配")
        sa = cosine_similarity(a, b)
        sd = cosine_similarity(a, c)
        assert sa > sd


class TestCreateEmbedder:
    """工厂。"""

    def test_returns_embedder_with_dim(self) -> None:
        emb = create_embedder()
        assert emb.dim == DEFAULT_DIM
        assert len(emb.embed("测试")) == DEFAULT_DIM
