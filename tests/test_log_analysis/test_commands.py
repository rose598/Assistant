"""SSH 客户端、命令执行层与 Mock 降级测试.

覆盖 SSH 未配置降级、Mock 命令层、命令失败/空输出容错.
"""

from __future__ import annotations

import pytest

from src.log_analysis.commands import LogCommandClient
from src.log_analysis.mock_executor import MockExecutor
from src.log_analysis.ssh_client import (
    SSHClient,
    SSHCommandError,
    SSHNotConfiguredError,
)


class TestSSHBoundary:
    """SSH 客户端边界测试类."""

    async def test_not_configured_raises(self) -> None:
        """未配置 host/user 时抛未配置异常."""
        client = SSHClient(host="", user="")
        with pytest.raises(SSHNotConfiguredError):
            await client.run("squeue -u $USER")

    async def test_init_defaults_from_config(self) -> None:
        """构造不传参时读 config, 为空则运行抛未配置异常."""
        client = SSHClient()
        with pytest.raises(SSHNotConfiguredError):
            await client.run("test")

    async def test_empty_command_raises_valueerror(self) -> None:
        """空命令抛 ValueError."""
        client = SSHClient(host="h", user="u")
        with pytest.raises(ValueError):
            await client.run("   ")


class TestMockCommandClient:
    """Mock 执行器 + 命令层降级链路测试类."""

    async def test_get_job_found(self) -> None:
        """查询到作业."""
        lcc = LogCommandClient(MockExecutor())
        rec = await lcc.get_job(1003)
        assert rec is not None
        assert rec.job_state == "F"
        assert rec.reason == "NonZeroExitCode"

    async def test_get_job_missing_returns_none(self) -> None:
        """被标记不存在的作业返回 None."""
        lcc = LogCommandClient(MockExecutor(missing_job_ids={"99999"}))
        assert await lcc.get_job(99999) is None

    async def test_get_job_unknown_id_returns_none(self) -> None:
        """未知作业 ID 返回 None."""
        lcc = LogCommandClient(MockExecutor())
        assert await lcc.get_job(123456) is None

    async def test_list_recent_jobs_limited(self) -> None:
        """最近作业列表受限."""
        lcc = LogCommandClient(MockExecutor())
        recs = await lcc.list_recent_jobs(limit=3)
        assert len(recs) <= 3
        assert len(recs) > 0

    async def test_list_queue_finds_states(self) -> None:
        """排队/运行状态均可查询到."""
        lcc = LogCommandClient(MockExecutor())
        q = await lcc.list_queue()
        states = {e.state for e in q}
        assert states & {"PD", "R"}

    async def test_list_nodes(self) -> None:
        """节点列表非空."""
        lcc = LogCommandClient(MockExecutor())
        nodes = await lcc.list_nodes()
        assert len(nodes) > 0

    async def test_command_failure_returns_empty(self) -> None:
        """命令失败返回空列表."""
        lcc = LogCommandClient(MockExecutor(fail_commands={"sacct"}))
        assert await lcc.list_recent_jobs() == []

    async def test_empty_output_returns_empty(self) -> None:
        """空输出返回空列表."""
        lcc = LogCommandClient(MockExecutor(empty_commands={"squeue"}))
        assert await lcc.list_queue() == []

    async def test_unknown_command_raises(self) -> None:
        """未知命令抛 SSHCommandError."""
        me = MockExecutor()
        with pytest.raises(SSHCommandError):
            await me.run("some unknown command")

    async def test_deterministic(self) -> None:
        """Mock 执行器确定性."""
        a = MockExecutor()
        b = MockExecutor()
        r1 = await LogCommandClient(a).get_job(1001)
        r2 = await LogCommandClient(b).get_job(1001)
        assert r1 is not None and r2 is not None
        assert r1.job_id == r2.job_id == "1001"
        assert r1.reason == r2.reason
