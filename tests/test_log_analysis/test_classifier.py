"""错误分类器与修复建议生成器测试.

覆盖 4 大类 + 10 子类、多信号判定、未知回退、修复模板填充.
"""

from __future__ import annotations

from src.log_analysis.classifier import (
    CAT_ENV,
    CAT_OOM,
    CAT_PERMISSION,
    CAT_SCRIPT,
    ErrorClassifier,
)
from src.log_analysis.commands import JobRecord
from src.log_analysis.fix_generator import FixGenerator


def _rec(job_state: str = "F", exit_code: str = "1:0", reason: str = "",
         job_name: str = "", partition: str = "", qos: str = "") -> JobRecord:
    """构造测试用作业记录."""
    return JobRecord(
        job_id="1", job_name=job_name, job_state=job_state, exit_code=exit_code,
        reason=reason, partition=partition, qos=qos,
    )


class TestClassifier:
    """错误分类器测试类."""

    def setup_method(self) -> None:
        self.cls = ErrorClassifier()

    def test_oom_category(self) -> None:
        c = self.cls.classify(_rec(reason="CUDA out of memory", job_name="train_oom"))
        assert c.category == CAT_OOM
        assert c.subtype == "gpu_oom"
        assert c.is_known

    def test_script_category(self) -> None:
        c = self.cls.classify(_rec(reason="No such file or directory"))
        assert c.category == CAT_SCRIPT
        assert c.subtype == "path_error"

    def test_env_category(self) -> None:
        c = self.cls.classify(_rec(reason="conda: command not found"))
        assert c.category == CAT_ENV
        assert c.subtype == "conda_missing"

    def test_permission_category(self) -> None:
        c = self.cls.classify(_rec(reason="QOSMaxWallDurationPerJobLimit"))
        assert c.category == CAT_PERMISSION
        assert c.subtype == "qos_limit"

    def test_case_insensitive_reason(self) -> None:
        c = self.cls.classify(_rec(reason="QOSMAXWALLDURATIONPERJOBLIMIT"))
        assert c.subtype == "qos_limit"

    def test_exit_code_detection(self) -> None:
        c = self.cls.classify(_rec(exit_code="137:0"))
        assert c.subtype == "mem_oom"

    def test_disk_full_subtype(self) -> None:
        c = self.cls.classify(_rec(reason="No space left on device"))
        assert c.category == CAT_OOM
        assert c.subtype == "disk_full"
        assert c.is_known

    def test_kernel_issue_subtype(self) -> None:
        c = self.cls.classify(_rec(reason="Illegal instruction"))
        assert c.category == CAT_ENV
        assert c.subtype == "kernel_issue"
        assert c.is_known

    def test_unknown_reason_returns_unknown(self) -> None:
        c = self.cls.classify(_rec(reason="SomeWeirdUnknownReason", exit_code="9:0"))
        assert c.is_known is False
        assert c.confidence == 0.0

    def test_empty_record_no_crash(self) -> None:
        c = self.cls.classify(_rec(reason=""))
        assert c is not None

    def test_non_numeric_exit_code(self) -> None:
        c = self.cls.classify(_rec(exit_code="abc", reason="cuda out of memory"))
        assert c.subtype == "gpu_oom"

    def test_dirty_fields_no_crash(self) -> None:
        c = self.cls.classify(JobRecord())
        assert c.label


class TestFixGenerator:
    """修复建议生成器测试类."""

    def setup_method(self) -> None:
        self.cls = ErrorClassifier()
        self.fix = FixGenerator()

    def test_each_subtype_has_advice(self) -> None:
        """每个已知子类都生成非空建议与命令."""
        cases = [
            ("CUDA out of memory", "gpu_oom"),
            ("oom-killer", "mem_oom"),
            ("No space left on device", "disk_full"),
            ("SyntaxError", "syntax_error"),
            ("No such file or directory", "path_error"),
            ("ModuleNotFoundError", "module_missing"),
            ("conda: command not found", "conda_missing"),
            ("library version mismatch", "cuda_mismatch"),
            ("Illegal instruction", "kernel_issue"),
            ("QOSMaxCpuPerUserLimit", "qos_limit"),
            ("Permission denied", "permission_denied"),
        ]
        for reason, subtype in cases:
            c = self.cls.classify(_rec(reason=reason))
            s = self.fix.generate(c)
            assert len(s.advice) > 0, f"{subtype} 应有建议"
            assert len(s.commands) > 0, f"{subtype} 应有命令"
            assert s.subtype == subtype

    def test_unknown_uses_generic(self) -> None:
        c = self.cls.classify(_rec(reason="NonsenseXYZ", exit_code="9:0"))
        s = self.fix.generate(c)
        assert s.subtype == "unknown"
        assert len(s.advice) > 0

    def test_fills_job_ctx(self) -> None:
        """分区占位被真实值替换."""
        c = self.cls.classify(
            _rec(reason="QOSMaxCpuPerUserLimit", partition="Students", qos="qos_stu_default")
        )
        s = self.fix.generate(c)
        assert any("Students" in cmd for cmd in s.commands)

    def test_fills_log_hint(self) -> None:
        """日志名占位被 JobName 替换."""
        c = self.cls.classify(_rec(reason="No such file or directory", job_name="myjob"))
        s = self.fix.generate(c)
        assert any("myjob.err" in cmd for cmd in s.commands)

    def test_missing_ctx_graceful(self) -> None:
        """无作业信息时用占位符, 不崩溃."""
        c = self.cls.classify(_rec(reason="QOSMaxWallDurationPerJobLimit"))
        s = self.fix.generate(c)
        assert s.advice
        assert all(isinstance(cmd, str) for cmd in s.commands)

    def test_label_reasonable(self) -> None:
        c = self.cls.classify(_rec(reason="CUDA out of memory"))
        s = self.fix.generate(c)
        assert s.label
