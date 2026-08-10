"""问答主流程 Pipeline 端到端测试."""

from __future__ import annotations

from src.pipeline import AnswerPipeline


class TestAnswerPipeline:
    """问答 Pipeline 测试类."""

    def setup_method(self) -> None:
        """每个测试前初始化 pipeline."""
        self.pipe = AnswerPipeline()

    def test_answer_hits_knowledge(self) -> None:
        """命中知识库返回真实答案."""
        a = self.pipe.ask("作业一直排队")
        assert a.matched_faq is not None
        assert not a.fallback
        assert len(a.answer) > 0

    def test_answer_gpu_oom(self) -> None:
        """GPU OOM 命中对应 FAQ."""
        a = self.pipe.ask("CUDA out of memory")
        assert a.matched_faq is not None
        assert "显存" in a.answer or "CUDA" in a.answer

    def test_answer_empty_query(self) -> None:
        """空查询返回引导文案."""
        a = self.pipe.ask("")
        assert len(a.answer) > 0

    def test_answer_intent_populated(self) -> None:
        """意图字段非空."""
        a = self.pipe.ask("怎么申请更高算力")
        assert a.intent.primary is not None
        assert a.intent.primary != ""

    def test_answer_fallback_for_unknown(self) -> None:
        """无关查询走回退且不抛异常."""
        a = self.pipe.ask("今天中午吃什么")
        assert a.answer is not None
        assert len(a.answer) > 0
