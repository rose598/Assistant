"""脚本改写流程测试.

测试完整的脚本改写流程，包括：
- 完整改写流程
- 每步回退
- 参数修改
"""

from __future__ import annotations

import pytest

from src.script.rewrite_flow import RewriteState, ScriptRewriteFlow


class TestScriptRewriteFullFlow:
    """脚本改写完整流程测试."""

    @pytest.fixture
    def flow(self) -> ScriptRewriteFlow:
        """返回改写流程."""
        return ScriptRewriteFlow()

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

    def test_full_rewrite_flow(self, flow: ScriptRewriteFlow, sample_script: str) -> None:
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

    def test_rewrite_partition_only(self, flow: ScriptRewriteFlow, sample_script: str) -> None:
        """测试只修改分区."""
        flow.start_rewrite("session-001", sample_script)
        flow.identify_changes("session-001", {"partition": "GPU-RTX5090"})
        flow.collect_params("session-001", "partition", "GPU-RTX5090")

        modified = flow.confirm_changes("session-001")
        assert modified is not None
        assert "-p GPU-RTX5090" in modified
        # 其他参数不变
        assert "--gres=gpu:1" in modified

    def test_rewrite_time_only(self, flow: ScriptRewriteFlow, sample_script: str) -> None:
        """测试只修改时间."""
        flow.start_rewrite("session-001", sample_script)
        flow.identify_changes("session-001", {"time": "12:00:00"})
        flow.collect_params("session-001", "time", "12:00:00")

        modified = flow.confirm_changes("session-001")
        assert modified is not None
        assert "-t 12:00:00" in modified

    def test_rewrite_gpu_count(self, flow: ScriptRewriteFlow, sample_script: str) -> None:
        """测试修改 GPU 数量."""
        flow.start_rewrite("session-001", sample_script)
        flow.identify_changes("session-001", {"gres": "gpu:2"})
        flow.collect_params("session-001", "gres", "gpu:2")

        modified = flow.confirm_changes("session-001")
        assert modified is not None
        # 原始格式是 --gres=gpu:1，替换后应该是 --gres gpu:2
        assert "gpu:2" in modified

    def test_rewrite_memory(self, flow: ScriptRewriteFlow, sample_script: str) -> None:
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
    def flow(self) -> ScriptRewriteFlow:
        """返回改写流程."""
        return ScriptRewriteFlow()

    @pytest.fixture
    def sample_script(self) -> str:
        """返回示例脚本."""
        return """#!/bin/bash
#SBATCH -p Students
#SBATCH -t 04:00:00
#SBATCH --mem=16G

python train.py
"""

    def test_rollback_after_collect(self, flow: ScriptRewriteFlow, sample_script: str) -> None:
        """测试收集参数后回退."""
        flow.start_rewrite("session-001", sample_script)
        flow.identify_changes("session-001", {"partition": "GPU-RTX5090"})
        flow.collect_params("session-001", "partition", "GPU-RTX5090")

        context = flow.contexts["session-001"]
        # 验证步骤历史
        assert len(context.step_history) == 2
        assert context.step_history[0]["step"] == "identify"
        assert context.step_history[1]["step"] == "collect"

    def test_step_history_preserved(self, flow: ScriptRewriteFlow, sample_script: str) -> None:
        """测试步骤历史保留."""
        flow.start_rewrite("session-001", sample_script)
        flow.identify_changes("session-001", {"partition": "GPU-RTX5090"})
        flow.collect_params("session-001", "partition", "GPU-RTX5090")
        flow.confirm_changes("session-001")

        context = flow.contexts["session-001"]
        assert len(context.step_history) == 3

    def test_multiple_param_collection(
        self, flow: ScriptRewriteFlow, sample_script: str
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
    def flow(self) -> ScriptRewriteFlow:
        """返回改写流程."""
        return ScriptRewriteFlow()

    def test_rewrite_nonexistent_session(self, flow: ScriptRewriteFlow) -> None:
        """测试改写不存在的会话."""
        result = flow.identify_changes("nonexistent", {"partition": "test"})
        assert result is False

    def test_rewrite_empty_script(self, flow: ScriptRewriteFlow) -> None:
        """测试改写空脚本."""
        context = flow.start_rewrite("session-001", "")
        assert context.original_script == ""

    def test_rewrite_no_changes(self, flow: ScriptRewriteFlow) -> None:
        """测试无修改的改写."""
        flow.start_rewrite("session-001", "#!/bin/bash\n#SBATCH -p Students")
        flow.identify_changes("session-001", {})

        modified = flow.confirm_changes("session-001")
        assert modified == "#!/bin/bash\n#SBATCH -p Students"

    def test_rewrite_preserves_non_sbatch_lines(self, flow: ScriptRewriteFlow) -> None:
        """测试改写保留非 SBATCH 行."""
        script = "#!/bin/bash\n#SBATCH -p Students\n\necho hello\npython train.py"
        flow.start_rewrite("session-001", script)
        flow.identify_changes("session-001", {"partition": "GPU-RTX5090"})
        flow.collect_params("session-001", "partition", "GPU-RTX5090")

        modified = flow.confirm_changes("session-001")
        assert modified is not None
        assert "echo hello" in modified
        assert "python train.py" in modified
