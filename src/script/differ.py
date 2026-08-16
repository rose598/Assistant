"""脚本差分显示（第 5 周，A 职责）。

基于 difflib 对改写前后的脚本生成统一 diff 文本与结构化变更摘要，
用于对话中向用户展示"改了什么"，供确认后再应用。

本模块无 D 预置验收用例（plan 验收口径为"合理可用"），
自带单测见 tests/test_script/test_differ.py。
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field


@dataclass
class DiffSummary:
    """结构化变更摘要。"""

    changed: bool = False
    removed: list[str] = field(default_factory=list)
    """原脚本中被删除的行。"""
    added: list[str] = field(default_factory=list)
    """修改后新增的行。"""
    replaced: list[tuple[str, str]] = field(default_factory=list)
    """被替换的行对 (原行, 新行)。"""


class ScriptDiffer:
    """脚本差分器：统一 diff 文本 + 结构化摘要。"""

    def diff(self, original: str, modified: str) -> str:
        """生成统一 diff 文本。

        Args:
            original: 原始脚本。
            modified: 修改后脚本。

        Returns:
            unified diff 文本；两脚本完全一致时返回空串。
        """
        if original == modified:
            return ""
        lines = difflib.unified_diff(
            original.splitlines(),
            modified.splitlines(),
            fromfile="original",
            tofile="modified",
            lineterm="",
        )
        return "\n".join(lines)

    def summarize(self, original: str, modified: str) -> DiffSummary:
        """按行比对生成结构化变更摘要。

        Args:
            original: 原始脚本。
            modified: 修改后脚本。

        Returns:
            DiffSummary：删除行 / 新增行 / 替换行对。
        """
        old_lines = original.splitlines()
        new_lines = modified.splitlines()
        summary = DiffSummary()

        matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            old = old_lines[i1:i2]
            new = new_lines[j1:j2]
            if tag == "replace":
                for idx in range(max(len(old), len(new))):
                    o = old[idx] if idx < len(old) else ""
                    n = new[idx] if idx < len(new) else ""
                    summary.replaced.append((o, n))
            elif tag == "delete":
                summary.removed.extend(old)
            elif tag == "insert":
                summary.added.extend(new)

        summary.changed = bool(summary.removed or summary.added or summary.replaced)
        return summary


__all__ = ["DiffSummary", "ScriptDiffer"]
