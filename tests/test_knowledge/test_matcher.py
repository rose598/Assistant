"""知识库匹配器测试。

覆盖模糊匹配与关键词精确匹配的各场景。
"""

from __future__ import annotations

from src.knowledge.loader import load_knowledge_base


class TestFuzzyMatch:
    """模糊匹配测试类."""

    def setup_method(self) -> None:
        """每个测试前加载知识库与匹配器."""
        self.kb, self.matcher = load_knowledge_base()

    def test_match_qos(self) -> None:
        """QOS 错误码模糊匹配."""
        results = self.matcher.match("QOSMaxWallDurationPerJobLimit")
        assert len(results) > 0
        entry, score = results[0]
        assert score >= 70
        assert "QOSMaxWall" in entry.title

    def test_match_gpu(self) -> None:
        """GPU 问题模糊匹配."""
        assert len(self.matcher.match("nvidia-smi 找不到 GPU")) > 0

    def test_match_queued(self) -> None:
        """排队问题模糊匹配."""
        assert len(self.matcher.match("作业一直在排队")) > 0

    def test_match_empty_query(self) -> None:
        """空查询返回空."""
        assert self.matcher.match("") == []
        assert self.matcher.match("   ") == []

    def test_match_no_result(self) -> None:
        """无命中返回空."""
        assert self.matcher.match("xxxxxxxxx不存在的查询yyyyyyyyy") == []

    def test_match_one_returns_tuple(self) -> None:
        """match_one 返回 (条目, 得分) 元组."""
        entry, score = self.matcher.match_one("CUDA out of memory")
        assert entry is not None
        assert 0.0 <= score <= 100.0


class TestKeywordMatch:
    """关键词精确匹配测试类."""

    def setup_method(self) -> None:
        """每个测试前加载知识库与匹配器."""
        _, self.matcher = load_knowledge_base()

    def test_match_hit(self) -> None:
        """关键词命中."""
        assert len(self.matcher.match_by_keyword("QOSMaxWall")) > 0
        assert len(self.matcher.match_by_keyword("conda")) > 0

    def test_match_miss(self) -> None:
        """无命中返回空."""
        assert self.matcher.match_by_keyword("不存在关键词xyz") == []
