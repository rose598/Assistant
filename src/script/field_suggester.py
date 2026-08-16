"""sbatch 字段建议器（第 5 周，A 职责）。

在对话式改写中，根据用户已提供的字段（或解析出的现有脚本字段），
建议补齐缺失字段：先按重叠度匹配最接近的预设模板，用模板默认值
补齐；再按平台口径补 qos 启发式建议。

设计要点：
- 解析器按契约**不映射短键**（``-p`` 解析为 ``"p"``），短键 → 长名
  的映射由本层承担（``normalize``），建议输出统一为长键名；
- 只建议**缺失**字段，不覆盖用户已给值。

本模块无 D 预置验收用例（plan 验收口径为"建议合理可用"），
自带单测见 tests/test_script/test_field_suggester.py。
"""

from __future__ import annotations

from src.script.templates import TEMPLATES, ScriptTemplate

# 短选项 → 长键名（解析器保留原样，建议层统一）
_SHORT_KEY_MAP: dict[str, str] = {
    "p": "partition",
    "t": "time",
    "c": "cpus",
    "J": "job_name",
}

# qos 启发式口径（与真实平台 qos_stu_* 对齐）
_QOS_GPU_DEFAULT = "qos_stu_default"
_QOS_CPU_LONG = "qos_stu_cpu_long"
_CPU_LONG_THRESHOLD_HOURS = 24.0


class FieldSuggester:
    """字段建议器：模板匹配补齐 + qos 启发式。"""

    def normalize(self, fields: dict[str, str]) -> dict[str, str]:
        """短键映射为长键名（未收录键原样保留）。

        Args:
            fields: 解析器输出或用户输入的字段字典。

        Returns:
            长键名化的新字典。
        """
        return {_SHORT_KEY_MAP.get(key, key): value for key, value in fields.items()}

    def match_template(self, fields: dict[str, str]) -> ScriptTemplate:
        """按重叠度选最接近的模板。

        计分：默认值键存在且值相同 +2，键存在值不同 +1；
        平分取 TEMPLATES 中靠前者。

        Args:
            fields: 已归一化（长键名）的字段字典。

        Returns:
            最匹配的模板。
        """
        best: ScriptTemplate | None = None
        best_score = -1
        for template in TEMPLATES.values():
            score = 0
            for key, value in template.defaults.items():
                if key in fields:
                    score += 2 if fields[key] == value else 1
            if score > best_score:
                best = template
                best_score = score
        assert best is not None  # TEMPLATES 非空
        return best

    def suggest(self, fields: dict[str, str]) -> dict[str, str]:
        """给出缺失字段建议（不覆盖已有字段）。

        Args:
            fields: 已知字段（短键/长键均可）。

        Returns:
            建议补齐的字段字典；无缺失时为空 dict。
        """
        known = self.normalize(fields)
        suggestions: dict[str, str] = {}

        # 模板匹配补齐
        template = self.match_template(known)
        for key, value in template.defaults.items():
            if key not in known:
                suggestions[key] = value

        # qos 启发式：仍缺 qos 时按平台口径补
        if "qos" not in known and "qos" not in suggestions:
            has_gpu = bool(known.get("gres") or suggestions.get("gres", "").startswith("gpu:"))
            if has_gpu:
                suggestions["qos"] = _QOS_GPU_DEFAULT
            elif self._time_hours(known.get("time", suggestions.get("time", ""))) >= _CPU_LONG_THRESHOLD_HOURS:
                suggestions["qos"] = _QOS_CPU_LONG

        return suggestions

    def explain(self, fields: dict[str, str]) -> list[str]:
        """生成人类可读的建议说明（供对话展示）。

        Args:
            fields: 已知字段。

        Returns:
            建议文本行列表；无建议时为空列表。
        """
        suggestions = self.suggest(fields)
        if not suggestions:
            return []
        template = self.match_template(self.normalize(fields))
        lines = [f"参考模板：{template.name}（{template.description}）"]
        for key, value in suggestions.items():
            lines.append(f"建议补充 {key} = {value}")
        return lines

    @staticmethod
    def _time_hours(time_str: str) -> float:
        """把 ``HH:MM:SS`` / ``D-HH:MM:SS`` 时长串换算为小时；解析失败记 0。"""
        text = time_str.strip()
        if not text:
            return 0.0
        days = 0.0
        if "-" in text:
            day_part, _, text = text.partition("-")
            try:
                days = float(day_part) * 24
            except ValueError:
                return 0.0
        parts = text.split(":")
        try:
            numbers = [float(part) for part in parts]
        except ValueError:
            return 0.0
        # Slurm 时长格式：HH:MM:SS / MM:SS / 分钟数
        if len(numbers) == 3:
            hours, minutes, seconds = numbers
            result = hours + minutes / 60 + seconds / 3600
        elif len(numbers) == 2:
            minutes, seconds = numbers
            result = minutes / 60 + seconds / 3600
        elif len(numbers) == 1:
            result = numbers[0] / 60
        else:
            return 0.0
        return days + result


__all__ = ["FieldSuggester"]
