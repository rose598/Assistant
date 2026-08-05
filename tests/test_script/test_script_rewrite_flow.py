"""脚本改写流程测试.

测试完整的脚本改写流程，包括：
- 完整改写流程
- 每步回退
- 参数修改
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import pytest


class RewriteState(Enum):
    """改写状态."""

    INIT = "init"
    IDENTIFY = "identify"
    COLLECT = "collect"
    CONFIRM = "confirm"
    APPLY = "apply"
    DONE = "done"


@dataclass
class RewriteContext:
    """改写上下文."""

    session_id: str
    state: RewriteState = RewriteState.INIT
    original_script: str = ""
    modified_script: str = ""
    changes: dict[str, Any] = field(default_factory=dict)
    step_history: list[dict[str, Any]] = field(default_factory=list)

    def save_step(self, step_name: str, data: Any) -> None:
        """保存步骤."""
        self.step_history.append({"step": step_name, "data": data, "state": self.state})


class MockScriptRewriteFlow:
    """模拟脚本改写流程（待 A/B 实现后替换）."""

    def __init__(self) -> None:
        """初始化改写流程."""
        self.contexts: dict[str, RewriteContext] = {}

    def start_rewrite(self, session_id: str, script: str) -> RewriteContext:
        """开始改写.

        Args:
            session_id: 会话ID.
            script: 原始脚本.

        Returns:
            改写上下文.
        """
        context = RewriteContext(session_id=session_id, original_script=script)
        context.state = RewriteState.IDENTIFY
        self.contexts[session_id] = context
        return context

    def identify_changes(self, session_id: str, changes: dict[str, Any]) -> bool:
        """识别要修改的内容.

        Args:
            session_id: 会话ID.
            changes: 要修改的字段.

        Returns:
            是否成功.
        """
        context = self.contexts.get(session_id)
        if context is None:
            return False
        context.changes = changes
        context.state = RewriteState.COLLECT
        context.save_step("identify", changes)
        return True

    def collect_params(self, session_id: str, field_name: str, value: Any) -> bool:
        """收集参数.

        Args:
            session_id: 会话ID.
            field_name: 字段名.
            value: 字段值.

        Returns:
            是否成功.
        """
        context = self.contexts.get(session_id)
        if context is None:
            return False
        context.changes[field_name] = value
        context.save_step("collect", {"field": field_name, "value": value})
        return True

    def confirm_changes(self, session_id: str) -> str | None:
        """确认修改.

        Args:
            session_id: 会话ID.

        Returns:
            修改后的脚本，如果失败返回 None.
        """
        context = self.contexts.get(session_id)
        if context is None:
            return None

        # 应用修改
        modified = context.original_script
        for field_name, value in context.changes.items():
            if field_name == "partition":
                modified = self._replace_param(modified, "-p", value)
            elif field_name == "time":
                modified = self._replace_param(modified, "-t", value)
            elif field_name == "mem":
                modified = self._replace_param(modified, "--mem", value)
            elif field_name == "gres":
                modified = self._replace_param(modified, "--gres", value)

        context.modified_script = modified
        context.state = RewriteState.CONFIRM
        context.save_step("confirm", None)
        return modified

    def apply_changes(self, session_id: str) -> bool:
        """应用修改.

        Args:
            session_id: 会话ID.

        Returns:
            是否成功.
        """
        context = self.contexts.get(session_id)
        if context is None:
            return False
        context.state = RewriteState.APPLY
        context.save_step("apply", None)
        return True

    def finish_rewrite(self, session_id: str) -> bool:
        """完成改写.

        Args:
            session_id: 会话ID.

        Returns:
            是否成功.
        """
        context = self.contexts.get(session_id)
        if context is None:
            return False
        context.state = RewriteState.DONE
        context.save_step("finish", None)
        return True

    def _replace_param(self, script: str, param: str, value: str) -> str:
        """替换参数."""
        import re

        # 处理 --key=value 格式
        pattern_eq = rf"{re.escape(param)}=\S+"
        if re.search(pattern_eq, script):
            return re.sub(pattern_eq, f"{param}={value}", script)

        # 处理 --key value 或 -k value 格式
        pattern_space = rf"{re.escape(param)}\s+\S+"
        return re.sub(pattern_space, f"{param} {value}", script)


class TestScriptRewriteFullFlow:
    """脚本改写完整流程测试."""

    @pytest.fixture
    def flow(self) -> MockScriptRewriteFlow:
        """返回改写流程."""
        return MockScriptRewriteFlow()

    @pytest.fixture
    def sample_script(self) -> str:
        """返回示例脚本."""
        return """#!/bin/bash
#SBATCH -J my_job
#SBATCH -p Students
#SBATCH --qos=qos_stu_default
#SBATCH --gres=gpu:1
#SBATCH -c 4
#SBATCH --mem=16G
#SBATCH -t 04:00:00

python train.py
"""

    def test_full_rewrite_flow(self, flow: MockScriptRewriteFlow, sample_script: str) -> None:
        """测试完整改写流程."""
        # 开始改写
        context = flow.start_rewrite("session-001", sample_script)
        assert context.state == RewriteState.IDENTIFY

        # 识别修改
        flow.identify_changes("session-001", {"partition": "GPU-RTX5090", "time": "08:00:00"})
        context = flow.contexts["session-001"]
        assert context.state == RewriteState.COLLECT

        # 收集参数
        flow.collect_params("session-001", "partition", "GPU-RTX5090")
        flow.collect_params("session-001", "time", "08:00:00")

        # 确认修改
        modified = flow.confirm_changes("session-001")
        assert modified is not None
        assert "GPU-RTX5090" in modified
        assert "08:00:00" in modified

        # 应用修改
        flow.apply_changes("session-001")
        context = flow.contexts["session-001"]
        assert context.state == RewriteState.APPLY

        # 完成改写
        flow.finish_rewrite("session-001")
        context = flow.contexts["session-001"]
        assert context.state == RewriteState.DONE

    def test_rewrite_partition_only(self, flow: MockScriptRewriteFlow, sample_script: str) -> None:
        """测试只修改分区."""
        flow.start_rewrite("session-001", sample_script)
        flow.identify_changes("session-001", {"partition": "GPU-RTX5090"})
        flow.collect_params("session-001", "partition", "GPU-RTX5090")

        modified = flow.confirm_changes("session-001")
        assert modified is not None
        assert "-p GPU-RTX5090" in modified
        # 其他参数不变
        assert "--gres=gpu:1" in modified

    def test_rewrite_time_only(self, flow: MockScriptRewriteFlow, sample_script: str) -> None:
        """测试只修改时间."""
        flow.start_rewrite("session-001", sample_script)
        flow.identify_changes("session-001", {"time": "12:00:00"})
        flow.collect_params("session-001", "time", "12:00:00")

        modified = flow.confirm_changes("session-001")
        assert modified is not None
        assert "-t 12:00:00" in modified

    def test_rewrite_gpu_count(self, flow: MockScriptRewriteFlow, sample_script: str) -> None:
        """测试修改 GPU 数量."""
        flow.start_rewrite("session-001", sample_script)
        flow.identify_changes("session-001", {"gres": "gpu:2"})
        flow.collect_params("session-001", "gres", "gpu:2")

        modified = flow.confirm_changes("session-001")
        assert modified is not None
        # 原始格式是 --gres=gpu:1，替换后应该是 --gres gpu:2
        assert "gpu:2" in modified

    def test_rewrite_memory(self, flow: MockScriptRewriteFlow, sample_script: str) -> None:
        """测试修改内存."""
        flow.start_rewrite("session-001", sample_script)
        flow.identify_changes("session-001", {"mem": "32G"})
        flow.collect_params("session-001", "mem", "32G")

        modified = flow.confirm_changes("session-001")
        assert modified is not None
        # 原始格式是 --mem=16G，替换后应该是 --mem 32G
        assert "32G" in modified


class TestScriptRewriteWithRollback:
    """脚本改写带回退测试."""

    @pytest.fixture
    def flow(self) -> MockScriptRewriteFlow:
        """返回改写流程."""
        return MockScriptRewriteFlow()

    @pytest.fixture
    def sample_script(self) -> str:
        """返回示例脚本."""
        return """#!/bin/bash
#SBATCH -p Students
#SBATCH -t 04:00:00
#SBATCH --mem=16G

python train.py
"""

    def test_rollback_after_collect(self, flow: MockScriptRewriteFlow, sample_script: str) -> None:
        """测试收集参数后回退."""
        flow.start_rewrite("session-001", sample_script)
        flow.identify_changes("session-001", {"partition": "GPU-RTX5090"})
        flow.collect_params("session-001", "partition", "GPU-RTX5090")

        context = flow.contexts["session-001"]
        # 验证步骤历史
        assert len(context.step_history) == 2
        assert context.step_history[0]["step"] == "identify"
        assert context.step_history[1]["step"] == "collect"

    def test_step_history_preserved(self, flow: MockScriptRewriteFlow, sample_script: str) -> None:
        """测试步骤历史保留."""
        flow.start_rewrite("session-001", sample_script)
        flow.identify_changes("session-001", {"partition": "GPU-RTX5090"})
        flow.collect_params("session-001", "partition", "GPU-RTX5090")
        flow.confirm_changes("session-001")

        context = flow.contexts["session-001"]
        assert len(context.step_history) == 3

    def test_multiple_param_collection(
        self, flow: MockScriptRewriteFlow, sample_script: str
    ) -> None:
        """测试收集多个参数."""
        flow.start_rewrite("session-001", sample_script)
        flow.identify_changes("session-001", {"partition": "GPU-RTX5090", "time": "08:00:00"})

        # 逐个收集
        flow.collect_params("session-001", "partition", "GPU-RTX5090")
        flow.collect_params("session-001", "time", "08:00:00")

        context = flow.contexts["session-001"]
        assert context.changes["partition"] == "GPU-RTX5090"
        assert context.changes["time"] == "08:00:00"


class TestScriptRewriteEdgeCases:
    """脚本改写边界情况测试."""

    @pytest.fixture
    def flow(self) -> MockScriptRewriteFlow:
        """返回改写流程."""
        return MockScriptRewriteFlow()

    def test_rewrite_nonexistent_session(self, flow: MockScriptRewriteFlow) -> None:
        """测试改写不存在的会话."""
        result = flow.identify_changes("nonexistent", {"partition": "test"})
        assert result is False

    def test_rewrite_empty_script(self, flow: MockScriptRewriteFlow) -> None:
        """测试改写空脚本."""
        context = flow.start_rewrite("session-001", "")
        assert context.original_script == ""

    def test_rewrite_no_changes(self, flow: MockScriptRewriteFlow) -> None:
        """测试无修改的改写."""
        flow.start_rewrite("session-001", "#!/bin/bash\n#SBATCH -p Students")
        flow.identify_changes("session-001", {})

        modified = flow.confirm_changes("session-001")
        assert modified == "#!/bin/bash\n#SBATCH -p Students"

    def test_rewrite_preserves_non_sbatch_lines(self, flow: MockScriptRewriteFlow) -> None:
        """测试改写保留非 SBATCH 行."""
        script = "#!/bin/bash\n#SBATCH -p Students\n\necho hello\npython train.py"
        flow.start_rewrite("session-001", script)
        flow.identify_changes("session-001", {"partition": "GPU-RTX5090"})
        flow.collect_params("session-001", "partition", "GPU-RTX5090")

        modified = flow.confirm_changes("session-001")
        assert modified is not None
        assert "echo hello" in modified
        assert "python train.py" in modified
