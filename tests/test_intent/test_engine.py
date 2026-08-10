"""意图识别引擎测试.

覆盖 4 个一级类、二级类命中、得分、unknown 与边界输入.
"""

from __future__ import annotations

from src.intent import (
    INTENT_ERROR_DIAGNOSIS,
    INTENT_JOB_STATUS,
    INTENT_JOB_SUBMISSION,
    INTENT_PERMISSION,
    IntentEngine,
)
from src.intent.engine import IntentResult


class TestIntentEngine:
    """意图识别引擎测试类."""

    def setup_method(self) -> None:
        """每个测试前初始化引擎."""
        self.eng = IntentEngine()

    def _classify(self, query: str) -> IntentResult:
        """调用分类."""
        return self.eng.classify(query)

    def test_job_submission(self) -> None:
        """识别作业提交意图."""
        r = self._classify("如何提交作业")
        assert r.primary == INTENT_JOB_SUBMISSION
        assert not r.is_unknown

    def test_job_status(self) -> None:
        """识别作业状态意图."""
        r = self._classify("作业一直排队怎么解决")
        assert r.primary == INTENT_JOB_STATUS
        assert not r.is_unknown

    def test_error_diagnosis(self) -> None:
        """识别报错诊断意图."""
        r = self._classify("CUDA out of memory")
        assert r.primary == INTENT_ERROR_DIAGNOSIS
        assert not r.is_unknown

    def test_permission(self) -> None:
        """识别权限资源意图."""
        r = self._classify("怎么申请更高算力")
        assert r.primary == INTENT_PERMISSION
        assert not r.is_unknown

    def test_subclass_detected(self) -> None:
        """二级类命中."""
        r = self._classify("怎么取消作业")
        assert "cancel_job" in r.subclasses

    def test_score_reasonable_when_hit(self) -> None:
        """命中级联得分合理."""
        r = self._classify("nvidia-smi 找不到 GPU")
        assert r.score >= 0.5

    def test_unknown_for_garbage(self) -> None:
        """无关查询判为 unknown."""
        r = self._classify("完全无关的一句话啊啊")
        assert r.is_unknown

    def test_empty_query_not_crash(self) -> None:
        """空查询不崩溃."""
        r = self._classify("")
        assert r is not None

    def test_html_markup_not_crash(self) -> None:
        """HTML 标签输入不崩溃."""
        r = self._classify("<script>alert(1)</script>")
        assert r is not None

    def test_suggest_llm_when_unknown(self) -> None:
        """unknown 时应建议走 LLM."""
        r = self._classify("你好")
        if r.is_unknown:
            assert self.eng.suggest_llm(r) is True
