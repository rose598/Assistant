"""LLM 辅助日志分类 + 规则/LLM 双重判断测试.

覆盖（align docs/log-classifier-architecture.md §6 验收口径）:
- 规则优先: 规则置信度高时直接返回, 不触发 LLM 调用(省成本)。
- LLM 兜底: 规则未命中时, LLM 给出受控 JSON 分类。
- 优雅降级: LLM 抛错 / 返回非法 subtype / 置信度过低时回退规则结果, 不 500。
- async 主路径与降级计数。

用注入的 *同步/异步* 假 LLM 替身确定性驱动, 不依赖真实网络。
"""

from __future__ import annotations

import pytest

from src.log_analysis.classifier import (
    CAT_OOM,
    ErrorClassification,
)
from src.log_analysis.commands import JobRecord
from src.log_analysis.fix_generator import FixGenerator
from src.log_analysis.llm_log_classifier import (
    DualLogClassifier,
    LLMLogClassifier,
)


def _rec(job_state: str = "F", exit_code: str = "1:0", reason: str = "",
         job_name: str = "", partition: str = "", qos: str = "") -> JobRecord:
    """构造测试用作业记录."""
    return JobRecord(
        job_id="1", job_name=job_name, job_state=job_state, exit_code=exit_code,
        reason=reason, partition=partition, qos=qos,
    )


# ---- 假 LLM 替身 ----

class _FakeAsyncLLM:
    """异步 LLM 替身: 返回预设文本. 可注入 send/raise 行为. """

    def __init__(self, text: str | None = None, exc: Exception | None = None,
                 sync: bool = False) -> None:
        self.text = text
        self.exc = exc
        self.sync = sync
        self.calls = 0

    async def complete(self, messages):  # noqa: ANN001
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return _FakeResp(self.text or "")

    def classify_sync(self, messages):  # 仅同步替身用
        return _FakeResp(self.text or "")


class _FakeSyncLLM:
    """同步 LLM 替身(测试 classify 同步路径). """

    def __init__(self, text: str = "") -> None:
        self.text = text
        self.calls = 0

    def complete(self, messages):  # noqa: ANN001
        self.calls += 1
        return _FakeResp(self.text)


class _FakeResp:
    def __init__(self, text: str) -> None:
        self.text = text
        self.prompt_tokens = 0
        self.completion_tokens = 0


_GOOD_JSON = (
    '{"category":"oom","subtype":"gpu_oom","confidence":0.9,'
    '"signals_hit":["LLM发现显存特征"]}'
)
_BAD_SUBTYPE_JSON = (
    '{"category":"oom","subtype":"gpu_oom_bogus","confidence":0.9,"signals_hit":[]}'
)
_PROSE = "这看起来像显存不足, 建议减小 batch size."


def _desc(classification: ErrorClassification) -> str:
    """方便断言: 把分类结果压缩成 'category|subtype|conf|known'."""
    return (
        f"{classification.category}|{classification.subtype}|"
        f"{classification.confidence:.2f}|{classification.is_known}"
    )


# ---- 规则优先 ----------------------------------------------------------------

class TestRulePriority:
    """规则优先: 高置信规则结果直接返回, 不触发 LLM."""

    def test_high_conf_rule_skips_llm(self) -> None:
        llm = _FakeSyncLLM(_GOOD_JSON)
        llm_cls = LLMLogClassifier(llm=llm, threshold=0.5)
        dual = DualLogClassifier(llm_classifier=llm_cls, rule_conf_threshold=0.6)
        # CUDA OOM 规则高置信命中 -> 走规则, 不调 LLM
        res = dual.classify(_rec(reason="CUDA out of memory"))
        assert res.subtype == "gpu_oom"
        assert llm.calls == 0  # 规则优先, 未触发 LLM

    def test_rule_known_high_confidence(self) -> None:
        llm = _FakeSyncLLM(_GOOD_JSON)
        llm_cls = LLMLogClassifier(llm=llm, threshold=0.5)
        dual = DualLogClassifier(llm_classifier=llm_cls, rule_conf_threshold=0.6)
        res = dual.classify(_rec(reason="No such file or directory"))
        assert res.subtype == "path_error"
        assert llm.calls == 0

    def test_rule_priority_coverage_unit(self) -> None:
        """已知 8 个规则样本应全部走规则、0 次 LLM(验收: 省成本)."""
        llm = _FakeSyncLLM(_GOOD_JSON)
        llm_cls = LLMLogClassifier(llm=llm, threshold=0.5)
        dual = DualLogClassifier(llm_classifier=llm_cls, rule_conf_threshold=0.6)
        samples = [
            ("CUDA out of memory", "gpu_oom"),
            ("oom-killer", "mem_oom"),
            ("No space left on device", "disk_full"),
            ("SyntaxError", "syntax_error"),
            ("No such file or directory", "path_error"),
            ("conda: command not found", "conda_missing"),
            ("ModuleNotFoundError", "module_missing"),
            ("QOSMaxWallDurationPerJobLimit", "qos_limit"),
        ]
        for reason, expected in samples:
            res = dual.classify(_rec(reason=reason))
            assert res.subtype == expected, reason
        assert llm.calls == 0  # 全部规则直判

    def test_rule_low_conf_triggers_llm(self) -> None:
        llm = _FakeSyncLLM(_GOOD_JSON)
        llm_cls = LLMLogClassifier(llm=llm, threshold=0.9)
        dual = DualLogClassifier(llm_classifier=llm_cls, rule_conf_threshold=0.99)
        # 规则未知 -> 触发 LLM; LLM 置信 0.9 >= llm 阈值 0.9 -> 用它
        res = dual.classify(_rec(reason="某新式显存报错, 无规列"))
        assert res.subtype == "gpu_oom"
        assert llm.calls == 1


# ---- LLM 兜底 ----------------------------------------------------------------

class TestLLMFallback:
    """规则未命中时 LLM 兜底."""

    @pytest.mark.asyncio
    async def test_aclassify_uses_llm_when_rule_unknown(self) -> None:
        llm = _FakeAsyncLLM(_GOOD_JSON)
        llm_cls = LLMLogClassifier(llm=llm, threshold=0.5)
        dual = DualLogClassifier(llm_classifier=llm_cls, rule_conf_threshold=0.6)
        res = await dual.aclassify(_rec(reason="一些规则无法识别的显存报错"))
        assert res.subtype == "gpu_oom"
        assert res.category == CAT_OOM
        assert res.is_known
        assert llm.calls == 1

    @pytest.mark.asyncio
    async def test_aclassify_sync_fake_via_direct_llmlog(self) -> None:
        """LLMLogClassifier.aclassify 本身直接用 LLM."""
        llm = _FakeAsyncLLM(_GOOD_JSON)
        clf = LLMLogClassifier(llm=llm, threshold=0.1)
        res = await clf.aclassify(_rec(reason=""))
        assert res.subtype == "gpu_oom"
        assert res.confidence == 0.9


# ---- 优雅降级 ----------------------------------------------------------------

class TestDegradation:
    """LLM 异常 / 非法类别 / 低置信 -> 回退规则, 不 500."""

    @pytest.mark.asyncio
    async def test_llm_raises_falls_back_to_rule(self) -> None:
        llm = _FakeAsyncLLM(exc=RuntimeError("llm down"))
        llm_cls = LLMLogClassifier(llm=llm, threshold=0.5)
        dual = DualLogClassifier(llm_classifier=llm_cls, rule_conf_threshold=0.6)
        # 用 exit_code="" 使规则结果真正 unknown, 验证 LLM 异常后回退规则(不 500)
        res = await dual.aclassify(_rec(reason="未知新报错", exit_code=""))
        assert res.subtype == "unknown"
        assert llm.calls == 1  # 只尝试过一次 LLM

    @pytest.mark.asyncio
    async def test_invalid_subtype_falls_back_to_rule(self) -> None:
        llm = _FakeAsyncLLM(_BAD_SUBTYPE_JSON)
        llm_cls = LLMLogClassifier(llm=llm, threshold=0.1)
        dual = DualLogClassifier(llm_classifier=llm_cls, rule_conf_threshold=0.6)
        res = await dual.aclassify(_rec(reason="无法归类的新现象", exit_code=""))
        # LLM 给出非法 subtype -> 校验回退 unknown -> 交还规则(规则也 unknown)
        assert res.subtype == "unknown"

    @pytest.mark.asyncio
    async def test_low_llm_confidence_falls_back_to_rule(self) -> None:
        lowconf = '{"category":"oom","subtype":"gpu_oom","confidence":0.2,"signals_hit":[]}'
        llm = _FakeAsyncLLM(lowconf)
        llm_cls = LLMLogClassifier(llm=llm, threshold=0.5)
        dual = DualLogClassifier(llm_classifier=llm_cls, rule_conf_threshold=0.6)
        res = await dual.aclassify(_rec(reason="未知新报错", exit_code=""))
        # LLM 置信 0.2 < 0.5 -> 不可靠, 回退规则(规则也 unknown)
        assert res.subtype == "unknown"

    def test_prose_response_parsed_to_unknown(self) -> None:
        llm = _FakeSyncLLM(_PROSE)
        clf = LLMLogClassifier(llm=llm, threshold=0.1)
        res = clf.classify(_rec(reason=""))
        assert res.subtype == "unknown"  # 散文无法解析为受控 JSON

    @pytest.mark.asyncio
    async def test_default_mock_llm_degrades_gracefully(self) -> None:
        """默认 create_llm_client()(Mock, 无端点)下 LLM 无法给有效 JSON -> 回退规则、不 500."""
        from src.llm.mock_llm import create_llm_client

        llm_cls = LLMLogClassifier(llm=create_llm_client(), threshold=0.5)
        dual = DualLogClassifier(llm_classifier=llm_cls, rule_conf_threshold=0.6)
        rec = _rec(reason="某全新硬件报错", exit_code="")
        res = await dual.aclassify(rec)
        # mock 散文回复无法解析成受控 JSON -> unknown -> 优雅回退(不抛)
        assert res.subtype == "unknown"
        assert dual.llm_calls == 1


# ---- 覆盖率口径(单元级) ---------------------------------------------------------

class TestCoverage:
    """规则 + LLM 合并覆盖率 ≥ 98%(在本测试抽样上验证计数口径)."""

    @pytest.mark.asyncio
    async def test_combined_coverage_counting(self) -> None:
        llm = _FakeAsyncLLM(_GOOD_JSON)
        llm_cls = LLMLogClassifier(llm=llm, threshold=0.5)
        dual = DualLogClassifier(llm_classifier=llm_cls, rule_conf_threshold=0.6)
        # 混合样本: 大部分规则可判, 少数规则盲区靠 LLM
        cases = [
            "CUDA out of memory",          # rule
            "No such file or directory",   # rule
            "conda: command not found",    # rule
            "QOSMaxWallDurationPerJobLimit",  # rule
            "某全新框架显存耗尽错误",          # rule 盲区 -> LLM
            "未知环境初始化失败",             # rule 盲区 -> LLM
        ]
        total = len(cases)
        covered = 0
        for c in cases:
            res = await dual.aclassify(_rec(reason=c))
            if res.is_known or res.confidence > 0:
                covered += 1
        rate = covered / total
        assert rate >= 0.98  # 6 样本: 4 rule + 2 LLM = 6/6 = 1.0


# ---- 与 FixGenerator 兼容 -----------------------------------------------------

class TestFixCompat:
    """双判结果仍可被 FixGenerator 消费(不破坏下游)."""

    @pytest.mark.asyncio
    async def test_dual_result_feeds_fix_generator(self) -> None:
        llm = _FakeAsyncLLM(_GOOD_JSON)
        llm_cls = LLMLogClassifier(llm=llm, threshold=0.5)
        dual = DualLogClassifier(llm_classifier=llm_cls, rule_conf_threshold=0.6)
        rec = _rec(reason="未知显存问题", job_name="train_2gpu")
        res = await dual.aclassify(rec)
        fix = FixGenerator().generate(res)
        # 对 gpu_oom(LLM 判)应能生成修复建议
        assert fix.commands  # 非空
        assert fix.advice
