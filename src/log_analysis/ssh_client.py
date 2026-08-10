"""SSH 客户端封装。

基于 asyncssh 的异步远程命令执行,面向平台日志查询场景:
`scontrol` / `sacct` / `squeue` / `sinfo`。

鲁棒性设计（重点处理边界场景）：
- 连接参数缺失(ssh_host / ssh_user 未配置)-> 抛出明确的
  `SSHNotConfiguredError`,而不是让调用方面对神秘的连接失败。
- 连接/认证失败 -> 分类异常(SSHConnectError / SSHAuthError)。
- 重试:重连 N 次(指数退避),避免瞬时网络抖动导致整体失败;
  认证等确定性错误不重试。
- 超时:连接超时(connect_timeout)与命令超时(command_timeout)分离。
- 命令非零退出:不抛原始异常,包装为 SSHCommandError 并保留输出。
- 空输出:返回空 stdout,不误报为失败。
- 连接复用:懒建立并缓存,显式 ``close()`` 释放。
- 构造注入 CommandExecutor,便于无真实账号时做单元测试。

典型用法::

    client = SSHClient()
    result = await client.run("squeue -u $USER")
    await client.close()
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from src.config import get_config

# ---- 异常层级 ----------------------------------------------------------------

class SSHError(Exception):
    """SSH 相关错误基类。"""


class SSHNotConfiguredError(SSHError):
    """SSH 连接参数未配置（ssh_host / ssh_user 为空）。"""


class SSHAuthError(SSHError):
    """认证失败（连接建立后认证被拒）。"""


class SSHConnectError(SSHError):
    """无法建立连接（网络、主机不可达、超时等）。"""


class SSHCommandError(SSHError):
    """命令执行出错（非零退出码 / 超时 / 传输异常）。"""

    def __init__(self, command: str, exit_status: int, stderr: str) -> None:
        self.command = command
        self.exit_status = exit_status
        self.stderr = stderr
        super().__init__(f"命令失败 (exit={exit_status}): {command}")


# ---- 结果结构 ----------------------------------------------------------------

@dataclass
class CommandResult:
    """单条远程命令的执行结果。"""

    stdout: str
    stderr: str
    exit_status: int
    command: str

    @property
    def ok(self) -> bool:
        return self.exit_status == 0

    @property
    def stdout_lines(self) -> list[str]:
        """按行拆分 stdout，剔除空白行。"""
        return [ln for ln in (self.stdout or "").splitlines() if ln.strip()]


# ---- 执行器抽象(便于 mock 测试) ---------------------------------------------

class CommandExecutor:
    """远程命令执行抽象接口。

    生产实现基于 asyncssh(见 SSHClient);测试可注入伪执行器。
    """

    async def run(self, command: str, timeout: float | None = None) -> CommandResult:
        raise NotImplementedError


# ---- 真实 asyncssh 实现 ------------------------------------------------------

class SSHClient(CommandExecutor):
    """基于 asyncssh 的 SSH 客户端。

    参数缺省读取全局 config(ssh_host / ssh_user / ssh_port / ssh_timeout /
    ssh_retry)。可通过构造参数覆盖,便于测试与部署时灵活配置。
    """

    def __init__(
        self,
        host: str | None = None,
        user: str | None = None,
        port: int | None = None,
        password: str | None = None,
        key_filename: str | None = None,
        connect_timeout: float | None = None,
        retry: int | None = None,
        command_timeout: float | None = None,
    ) -> None:
        cfg = get_config()
        self._host = host or cfg.ssh_host
        self._user = user or cfg.ssh_user
        self._port = port or cfg.ssh_port
        self._password = password or ""
        self._key_filename = key_filename
        self._connect_timeout = connect_timeout or cfg.ssh_timeout
        self._retry = cfg.ssh_retry if retry is None else retry
        self._command_timeout = command_timeout or 60.0
        self._conn: Any | None = None

    # -- 生命周期 --
    async def close(self) -> None:
        """释放底层连接。"""
        if self._conn is not None:
            self._conn.close()
            await self._conn.wait_closed()
            self._conn = None

    async def _ensure_connected(self) -> Any:
        """建立（或复用）连接，失败时按 retry 重连。"""
        if self._conn is not None and not self._conn.is_closed():
            return self._conn

        if not self._host or not self._user:
            raise SSHNotConfiguredError(
                "SSH 未配置: 请设置 AGENT_SSH_HOST / AGENT_SSH_USER 环境变量,"
                "或在 src/config.py 中填写 ssh_host / ssh_user。"
            )

        if self._retry < 0:
            raise SSHError(f"ssh_retry 不能为负: {self._retry}")

        attempts = max(1, self._retry + 1)
        last_exc: Exception | None = None
        for attempt in range(attempts):
            try:
                conn = await self._open_connection()
                self._conn = conn
                return conn
            except asyncio.CancelledError:
                raise
            except SSHAuthError:
                # 认证失败是确定性错误, 重试无意义
                raise
            except Exception as exc:
                last_exc = exc
                self._close_conn_if_any()
                if attempt < attempts - 1:
                    await asyncio.sleep(self._backoff(attempt))

        assert last_exc is not None
        if isinstance(last_exc, SSHAuthError):
            raise last_exc
        raise SSHConnectError(
            f"SSH 连接失败(重试 {self._retry} 次后仍失败): {last_exc}"
        ) from last_exc

    async def _open_connection(self) -> Any:
        """建立单次连接。认证异常会被归类为 SSHAuthError。"""
        import asyncssh  # 延迟导入, 避免模块即依赖未安装而崩

        if self._connect_timeout <= 0:
            raise SSHError(f"connect_timeout 必须 > 0: {self._connect_timeout}")

        try:
            return await asyncssh.connect(
                host=self._host,
                username=self._user,
                port=self._port,
                password=self._password or None,
                client_keys=self._key_filename,
                known_hosts=None,  # 内部集群, 暂不校验指纹
                connect_timeout=self._connect_timeout,
            )
        except asyncssh.PermissionDenied as exc:
            raise SSHAuthError(f"SSH 认证失败: {exc}") from exc

    @staticmethod
    def _backoff(attempt: int) -> float:
        """指数退避，封顶 5s。"""
        return min(2.0 ** attempt, 5.0)

    def _close_conn_if_any(self) -> None:
        if self._conn is not None:
            with suppress(Exception):  # 关闭失败可忽略
                self._conn.close()
            self._conn = None

    # -- 命令执行 --
    async def run(self, command: str, timeout: float | None = None) -> CommandResult:
        """执行远程命令，返回 stdout/stderr/exit_status。"""
        if not command or not command.strip():
            raise ValueError("command 不能为空")
        timeout = timeout or self._command_timeout
        if timeout <= 0:
            raise ValueError(f"命令超时时间必须 > 0: {timeout}")

        conn = await self._ensure_connected()
        try:
            proc = await asyncio.wait_for(conn.run(command, check=False), timeout=timeout)
            return CommandResult(
                stdout=proc.stdout or "",
                stderr=proc.stderr or "",
                exit_status=proc.returncode if proc.returncode is not None else -1,
                command=command,
            )
        except asyncio.TimeoutError:
            # 命令超时: 关闭连接以防悬挂, 下次调用自动重连
            self._close_conn_if_any()
            raise SSHCommandError(command, -1, f"命令超时(>{timeout}s)") from None
        except asyncio.CancelledError:
            self._close_conn_if_any()
            raise
        except SSHCommandError:
            raise
        except Exception as exc:
            self._close_conn_if_any()
            raise SSHCommandError(command, -1, str(exc)) from exc


__all__ = [
    "CommandExecutor",
    "CommandResult",
    "SSHAuthError",
    "SSHClient",
    "SSHCommandError",
    "SSHConnectError",
    "SSHError",
    "SSHNotConfiguredError",
]
