"""脚本差分器自测（第 5 周，A 侧；无 D 预置用例，验收口径"合理可用"）."""

from __future__ import annotations

from src.script.differ import ScriptDiffer

ORIGINAL = """#!/bin/bash
#SBATCH -J train
#SBATCH -p Students
#SBATCH -t 04:00:00
python train.py
"""


class TestScriptDiffer:
    """差分文本与结构化摘要."""

    def setup_method(self) -> None:
        self.differ = ScriptDiffer()

    def test_identical_scripts(self) -> None:
        """完全一致：diff 为空串，摘要无变更."""
        assert self.differ.diff(ORIGINAL, ORIGINAL) == ""
        summary = self.differ.summarize(ORIGINAL, ORIGINAL)
        assert summary.changed is False
        assert summary.removed == []
        assert summary.added == []
        assert summary.replaced == []

    def test_detect_partition_change(self) -> None:
        """单字段修改：diff 含删增行，摘要记一条替换行对."""
        modified = ORIGINAL.replace("Students", "GPU")
        text = self.differ.diff(ORIGINAL, modified)
        assert "-#SBATCH -p Students" in text
        assert "+#SBATCH -p GPU" in text

        summary = self.differ.summarize(ORIGINAL, modified)
        assert summary.changed is True
        assert ("#SBATCH -p Students", "#SBATCH -p GPU") in summary.replaced

    def test_multiple_changes(self) -> None:
        """多处修改：摘要逐条记录."""
        modified = ORIGINAL.replace("04:00:00", "08:00:00").replace("train.py", "run.py")
        summary = self.differ.summarize(ORIGINAL, modified)
        assert summary.changed is True
        assert len(summary.replaced) == 2

    def test_added_line(self) -> None:
        """新增行归入 added."""
        modified = ORIGINAL + "echo done\n"
        summary = self.differ.summarize(ORIGINAL, modified)
        assert summary.changed is True
        assert summary.added == ["echo done"]
        assert summary.removed == []

    def test_removed_line(self) -> None:
        """删除行归入 removed."""
        modified = ORIGINAL.replace("python train.py\n", "")
        summary = self.differ.summarize(ORIGINAL, modified)
        assert summary.changed is True
        assert summary.removed == ["python train.py"]
        assert summary.added == []

    def test_empty_original(self) -> None:
        """空原脚本：整体视为新增."""
        summary = self.differ.summarize("", ORIGINAL)
        assert summary.changed is True
        assert len(summary.added) == len(ORIGINAL.splitlines())
        assert summary.removed == []
        assert summary.replaced == []
