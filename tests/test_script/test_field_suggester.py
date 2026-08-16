"""字段建议器自测（第 5 周，A 侧；无 D 预置用例，验收口径"建议合理可用"）."""

from __future__ import annotations

from src.script.field_suggester import FieldSuggester


class TestFieldSuggester:
    """短键归一 / 模板匹配补齐 / qos 启发式."""

    def setup_method(self) -> None:
        self.suggester = FieldSuggester()

    def test_normalize_short_keys(self) -> None:
        """短键映射为长键名，长键与未知键原样保留."""
        normalized = self.suggester.normalize({"p": "Students", "t": "04:00:00", "mem": "8G"})
        assert normalized == {"partition": "Students", "time": "04:00:00", "mem": "8G"}

    def test_suggest_from_empty(self) -> None:
        """空输入：按首个模板(minimal_cpu)补齐基础字段，不误推 qos."""
        suggestions = self.suggester.suggest({})
        assert suggestions["partition"] == "Students"
        assert suggestions["cpus"] == "1"
        assert suggestions["mem"] == "4G"
        assert suggestions["time"] == "00:10:00"
        assert "qos" not in suggestions

    def test_suggest_gpu_fields(self) -> None:
        """GPU 作业：模板补齐并按平台口径建议 qos_stu_default."""
        suggestions = self.suggester.suggest({"gres": "gpu:1", "partition": "Students"})
        assert suggestions["qos"] == "qos_stu_default"
        assert suggestions["mem"] == "16G"
        assert suggestions["time"] == "04:00:00"
        assert "gres" not in suggestions  # 已有字段不重复建议

    def test_suggest_long_cpu_qos(self) -> None:
        """长时 CPU 作业(≥24h)：启发式建议 qos_stu_cpu_long."""
        suggestions = self.suggester.suggest({"partition": "Students", "time": "72:00:00"})
        assert suggestions["qos"] == "qos_stu_cpu_long"

    def test_no_override_existing(self) -> None:
        """只建议缺失字段，不覆盖用户已给值."""
        suggestions = self.suggester.suggest({"mem": "64G", "partition": "Students"})
        assert "mem" not in suggestions
        assert suggestions["cpus"] == "1"

    def test_complete_fields_no_suggestion(self) -> None:
        """字段齐全时不产生任何建议."""
        full = {
            "partition": "Students",
            "qos": "qos_stu_default",
            "gres": "gpu:1",
            "cpus": "4",
            "mem": "16G",
            "time": "04:00:00",
        }
        assert self.suggester.suggest(full) == {}
        assert self.suggester.explain(full) == []

    def test_explain_readable_lines(self) -> None:
        """explain 输出含参考模板与逐条建议."""
        lines = self.suggester.explain({"gres": "gpu:1"})
        assert lines
        assert lines[0].startswith("参考模板：")
        assert any("qos" in line for line in lines)

    def test_time_hours_formats(self) -> None:
        """时长换算覆盖 HH:MM:SS / MM:SS / 分钟 / D-HH:MM:SS / 非法串."""
        convert = FieldSuggester._time_hours
        assert convert("04:00:00") == 4.0
        assert convert("72:00:00") == 72.0
        assert convert("30:00") == 0.5
        assert convert("60") == 1.0
        assert convert("1-00:00:00") == 24.0
        assert convert("abc") == 0.0
        assert convert("") == 0.0
