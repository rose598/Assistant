"""一键修复命令 AutoFixCmd 测试.

覆盖（plan §第4周周四验收"命令语法正确可执行" + A 侧设计）:
- 12 子类命令模板全覆盖（与 classifier.SUBTYPE_CATEGORY 一致，无遗漏）。
- 每子类命令非空且含预期关键命令（sbatch/pip/conda/chmod/bash -n 等）。
- 占位替换：record 真实信息填充；缺失字段用可见占位且不残留 {key}。
- unknown 兜底：空命令 + 提示文案，不抛异常；FixGenerator 异常也不抛。
- 单向复用 FixGenerator：unknown 时附加其 advice（注入 stub 验证）。
"""

from __future__ import annotations

import pytest

from src.log_analysis.classifier import SUBTYPE_CATEGORY, ErrorClassification
from src.log_analysis.commands import JobRecord
from src.log_analysis.fix_generator import FixSuggestion
from src.monitor.auto_fix_cmd import (
    CMD_TEMPLATES,
    KNOWN_SUBTYPES,
    MISSING_TEMPLATES,
    AutoFixCmd,
    AutoFixResult,
)


def _cls(subtype: str, **record_kwargs: str) -> ErrorClassification:
    """构造指定子类的分类结果."""
    return ErrorClassification(
        record=JobRecord(**record_kwargs),
        category=SUBTYPE_CATEGORY.get(subtype, "unknown"),
        subtype=subtype,
        confidence=0.9,
    )


class TestTemplateCoverage:
    """12 子类模板全覆盖."""

    def test_all_subtypes_have_template(self) -> None:
        assert len(KNOWN_SUBTYPES) == 12
        assert frozenset() == MISSING_TEMPLATES
        assert set(CMD_TEMPLATES) == set(KNOWN_SUBTYPES)


class TestSubtypeCommands:
    """每子类命令非空且含预期关键命令."""

    @pytest.mark.parametrize(
        ("subtype", "keyword"),
        [
            ("gpu_oom", "sbatch"),
            ("mem_oom", "sbatch"),
            ("disk_full", "du -sh"),
            ("syntax_error", "bash -n"),
            ("path_error", "ls -l"),
            ("dependency_error", "pip install"),
            ("conda_missing", "conda activate"),
            ("module_missing", "pip install"),
            ("cuda_mismatch", "nvidia-smi"),
            ("kernel_issue", "gcc --version"),
            ("qos_limit", "sacctmgr show qos"),
            ("permission_denied", "chmod +x"),
        ],
    )
    def test_command_contains_keyword(self, subtype: str, keyword: str) -> None:
        result = AutoFixCmd().generate(_cls(subtype))
        assert result.has_command is True
        assert result.command != ""
        assert keyword in result.command
        assert result.note != ""

    def test_commands_list_head_is_main_command(self) -> None:
        result = AutoFixCmd().generate(_cls("gpu_oom"))
        assert result.commands[0] == result.command
        assert len(result.commands) >= 2  # 主命令 + 至少一条辅助命令

    def test_no_residual_placeholder_keys(self) -> None:
        # 任何子类的输出不应残留 {workdir}/{script} 等未替换占位
        for subtype in KNOWN_SUBTYPES:
            result = AutoFixCmd().generate(_cls(subtype))
            for cmd in result.commands:
                assert "{workdir}" not in cmd
                assert "{script}" not in cmd
                assert "{job_id}" not in cmd


class TestPlaceholderFilling:
    """record 真实信息填充占位."""

    def test_filled_from_record(self) -> None:
        result = AutoFixCmd().generate(
            _cls("gpu_oom", job_id="36001", workdir="/home/scc/stu001",
                 command="train.sbatch", partition="Students", qos="qos_stu_default")
        )
        assert result.command == "cd /home/scc/stu001 && sbatch train.sbatch"

    def test_job_id_filled_in_aux(self) -> None:
        result = AutoFixCmd().generate(_cls("mem_oom", job_id="36001"))
        assert any("scontrol show job 36001" in c for c in result.commands)

    def test_missing_fields_use_visible_placeholder(self) -> None:
        result = AutoFixCmd().generate(_cls("syntax_error"))  # 空 record
        assert "<提交脚本>" in result.command
        assert "<工作目录>" in " ".join(result.commands)

    def test_permission_denied_chmod_script(self) -> None:
        result = AutoFixCmd().generate(_cls("permission_denied", command="run.sbatch"))
        assert result.command == "chmod +x run.sbatch"


class TestUnknownFallback:
    """unknown 兜底：空命令 + 提示，不抛."""

    def test_unknown_returns_empty_command(self) -> None:
        result = AutoFixCmd().generate(_cls("unknown"))
        assert isinstance(result, AutoFixResult)
        assert result.command == ""
        assert result.commands == []
        assert result.has_command is False
        assert "未能精确归类" in result.note

    def test_future_unknown_subtype_also_falls_back(self) -> None:
        # 未来新增但尚无模板的子类同样兜底
        result = AutoFixCmd().generate(_cls("some_new_subtype"))
        assert result.command == ""
        assert result.note != ""

    def test_fix_generator_error_does_not_raise(self) -> None:
        class BrokenGenerator:
            def generate(self, cls: ErrorClassification) -> FixSuggestion:
                raise RuntimeError("boom")

        gen = AutoFixCmd(fix_generator=BrokenGenerator())  # type: ignore[arg-type]
        result = gen.generate(_cls("unknown"))
        assert result.command == ""
        assert "未能精确归类" in result.note  # 兜底文案仍在


class TestReuseFixGenerator:
    """单向复用 FixGenerator 的 advice（只读其输出）."""

    def test_advice_appended_for_unknown(self) -> None:
        class StubGenerator:
            def generate(self, cls: ErrorClassification) -> FixSuggestion:
                return FixSuggestion(
                    subtype=cls.subtype, label=cls.label,
                    advice="通用排查建议ABC", commands=[],
                )

        gen = AutoFixCmd(fix_generator=StubGenerator())  # type: ignore[arg-type]
        result = gen.generate(_cls("unknown"))
        assert "通用排查建议ABC" in result.note

    def test_known_subtype_not_affected_by_fix_generator(self) -> None:
        class StubGenerator:
            def generate(self, cls: ErrorClassification) -> FixSuggestion:
                raise AssertionError("known 子类不应调用 FixGenerator")

        gen = AutoFixCmd(fix_generator=StubGenerator())  # type: ignore[arg-type]
        result = gen.generate(_cls("gpu_oom"))
        assert result.has_command is True
