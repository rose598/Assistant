"""Mock 命令执行器。

实现 CommandExecutor 接口,返回与真实平台命令格式一致的假数据,
用于：
- 无真实 SSH 账号时的开发与演示(降级路径)
- 单元测试(无需网络、可复现)
- 模拟异常场景(命令失败 / 作业不存在 / 空输出)以验证上层鲁棒性

数据源复用 `log_analysis.mock`(第 1 周 A 的假数据模拟器)。
"""

from __future__ import annotations

from src.log_analysis.mock import (
    load_mock_jobs,
    render_sacct,
    render_scontrol,
)
from src.log_analysis.ssh_client import (
    CommandExecutor,
    CommandResult,
    SSHCommandError,
)


class MockExecutor(CommandExecutor):
    """基于假数据的命令执行器。

    参数:
        fail_commands: 需要模拟失败的命令子串集合(命中则返回非零退出码)。
        empty_commands: 需要模拟空输出的命令子串集合。
        missing_job_ids: 模拟"作业不存在"的作业 ID 集合。
    """

    def __init__(
        self,
        fail_commands: set[str] | None = None,
        empty_commands: set[str] | None = None,
        missing_job_ids: set[str] | None = None,
    ) -> None:
        self._jobs = load_mock_jobs()
        self._fail_commands = fail_commands or set()
        self._empty_commands = empty_commands or set()
        self._missing_job_ids = missing_job_ids or set()
        self._call_count = 0

    @property
    def call_count(self) -> int:
        return self._call_count

    async def run(self, command: str, timeout: float | None = None) -> CommandResult:
        """根据命令路由到对应假数据渲染。"""
        self._call_count += 1

        low = command.lower()

        # 模拟失败
        for marker in self._fail_commands:
            if marker.lower() in low:
                raise SSHCommandError(command, 1, f"[mock] 模拟失败: {marker}")

        # 模拟空输出
        for marker in self._empty_commands:
            if marker.lower() in low:
                return CommandResult("", "", 0, command)

        if "scontrol show job" in low:
            return self._handle_scontrol(command)
        if low.startswith("sacct") or low == "sacct":
            return CommandResult(render_sacct(self._jobs), "", 0, command)
        if low.startswith("squeue"):
            return CommandResult(self._render_squeue_ws(), "", 0, command)
        if low.startswith("sinfo"):
            return CommandResult(self._render_sinfo_ws(), "", 0, command)

        # 未知命令
        raise SSHCommandError(command, 127, f"[mock] 未知命令: {command}")

    # -- 空白分隔渲染(贴近真实 squeue -o / sinfo 输出,供命令层直接解析)--
    def _render_squeue_ws(self) -> str:
        """渲染空格分隔的 squeue 视图（仅 PD / R）。"""
        header = "JOBID PARTITION NAME USER ST TIME NODES NODELIST(REASON)"
        rows = []
        for j in self._jobs:
            if j.job_state not in ("PD", "R"):
                continue
            rows.append(
                f"{j.job_id:<10} {j.partition:<10} {j.job_name:<12} "
                f"scc_stu {j.job_state:<4} 0:00 {1:<2} {j.node_list or j.reason}"
            )
        if not rows:
            return header
        return "\n".join([header, *rows])

    def _render_sinfo_ws(self) -> str:
        """渲染空格分隔的 sinfo 节点状态。"""
        header = "PARTITION AVAIL TIMELIMIT NODES STATE NODELIST"
        rows = [
            "Students up infinite 13 idle anode[05-17]",
            "Students up infinite 2 mix anode[11,16]",
            "CPU-6530 up infinite 8 idle cnode[01-08]",
            "GPU-RTX5090 up infinite 6 idle gnode[01-06]",
            "GPU-RTX5090 up infinite 1 down gnode[07]",
        ]
        return "\n".join([header, *rows])

    def _handle_scontrol(self, command: str) -> CommandResult:
        """解析作业 ID 并返回对应 scontrol 输出或"不存在"。"""
        job_id = self._extract_job_id(command)
        if job_id in self._missing_job_ids:
            return CommandResult(
                "", "slurm_load_jobs error: Invalid job id specified", 1, command
            )
        for job in self._jobs:
            if str(job.job_id) == job_id:
                return CommandResult(render_scontrol([job]), "", 0, command)
        return CommandResult(
            "", "slurm_load_jobs error: Invalid job id specified", 1, command
        )

    @staticmethod
    def _extract_job_id(command: str) -> str:
        """从 `scontrol show job <id>` 提取作业 ID。"""
        parts = command.split()
        for part in parts[-1:]:
            if part.isdigit():
                return part
        return ""
