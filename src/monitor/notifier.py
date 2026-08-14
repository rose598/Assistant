"""推送通知模块：企业微信 Bot / Email / WebSocket 三通道.

第 4 周 A 交付物（plan §3.6 / 进度记录 §七）：监控预警与诊断结果的主动推送。

设计要点：
- **统一入口**：``Notifier.send(event, channel, message, priority)``，通道 key 为
  ``wecom_bot`` / ``email`` / ``ws``（与 D 测试 ``test_all_channels_supported`` 一致）。
- **每通道一个实现**：``WeComBotChannel`` / ``EmailChannel`` / ``WebSocketChannel``，
  均实现 ``available``（凭证是否就绪）+ ``async deliver``。
- **优雅降级**：凭证未配置（webhook 为空 / SMTP 未配 / 无 WS 广播器）或发送异常时，
  返回 ``SendResult(delivered=False, reason=...)``，**不抛异常**——
  推送失败不应让监控/诊断主流程崩溃。
- **可测**：每个通道支持注入传输函数（poster/smtp sender/broadcaster），
  测试无需真实网络；``Notifier.sent`` 记录全部尝试（含未送达），语义对齐 D 的 MockNotifier。
- **凭证来源**：Config（``WECHAT_BOT_WEBHOOK`` / ``SMTP_*``，config.py 已有模块级变量）。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import src.config as _cfg
from src.config import get_config

__all__ = [
    "CHANNELS",
    "EmailChannel",
    "Notification",
    "Notifier",
    "SendResult",
    "WeComBotChannel",
    "WebSocketChannel",
]

# 支持的通道 key（与 D 测试 test_all_channels_supported 对齐）
CHANNELS: tuple[str, ...] = ("wecom_bot", "email", "ws")


@dataclass
class Notification:
    """一条推送（字段名与 D 测试 Notification 一致）。"""

    event: str
    channel: str  # wecom_bot | email | ws
    message: str
    priority: str = "P1"  # P0 | P1


@dataclass
class SendResult:
    """一次推送尝试的结果（送达与否 + 原因）。"""

    delivered: bool
    channel: str
    notification: Notification
    reason: str = ""


# ---- 通道实现 ---------------------------------------------------------------


class WeComBotChannel:
    """企业微信 Bot 通道（webhook POST）。

    ``poster``：可注入的发送函数 ``async (webhook, payload) -> None``；
    未注入时走标准库 urllib 的线程池 POST（默认 JSON 文本消息格式）。
    """

    name = "wecom_bot"

    def __init__(
        self,
        webhook: str | None = None,
        poster: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self.webhook = webhook if webhook is not None else str(
            getattr(get_config(), "wechat_bot_webhook", "")
            or getattr(_cfg, "WECHAT_BOT_WEBHOOK", "")
        )
        self._poster = poster

    @property
    def available(self) -> bool:
        """webhook 已配置才算可用。"""
        return bool(self.webhook)

    async def deliver(self, note: Notification) -> SendResult:
        if not self.available:
            return SendResult(False, self.name, note, reason="wecom webhook 未配置")
        payload = {
            "msgtype": "text",
            "text": {"content": f"[{note.priority}][{note.event}] {note.message}"},
        }
        try:
            if self._poster is not None:
                await self._poster(self.webhook, payload)
            else:
                await asyncio.to_thread(_default_wecom_post, self.webhook, payload)
        except Exception as exc:
            return SendResult(False, self.name, note, reason=f"wecom 发送失败: {exc}")
        return SendResult(True, self.name, note)


class EmailChannel:
    """Email 通道（标准库 smtplib，无需第三方依赖）。

    ``to``：收件人，缺省取 SMTP_USER；``sender``：可注入的发送函数
    ``async (host, port, user, password, to, subject, body) -> None``，
    未注入时用 smtplib SMTP_SSL 在线程池发送。
    """

    name = "email"

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        to: str | None = None,
        sender: Callable[..., Awaitable[None]] | None = None,
    ) -> None:
        cfg = get_config()
        self.host = host if host is not None else str(
            getattr(cfg, "smtp_host", "") or getattr(_cfg, "SMTP_HOST", "")
        )
        self.port = port if port is not None else int(
            getattr(cfg, "smtp_port", 0) or getattr(_cfg, "SMTP_PORT", 465)
        )
        self.user = user if user is not None else str(
            getattr(cfg, "smtp_user", "") or getattr(_cfg, "SMTP_USER", "")
        )
        self.password = password if password is not None else str(
            getattr(cfg, "smtp_password", "") or getattr(_cfg, "SMTP_PASSWORD", "")
        )
        self.to = to or self.user
        self._sender = sender

    @property
    def available(self) -> bool:
        """SMTP 主机 + 账号就绪才算可用。"""
        return bool(self.host and self.user and self.password)

    async def deliver(self, note: Notification) -> SendResult:
        if not self.available:
            return SendResult(False, self.name, note, reason="SMTP 未配置")
        if not self.to:
            return SendResult(False, self.name, note, reason="收件人未配置")
        subject = f"[107-Agent][{note.priority}] {note.event}"
        try:
            if self._sender is not None:
                await self._sender(
                    self.host, self.port, self.user, self.password,
                    self.to, subject, note.message,
                )
            else:
                await asyncio.to_thread(
                    _default_smtp_send,
                    self.host, self.port, self.user, self.password,
                    self.to, subject, note.message,
                )
        except Exception as exc:
            return SendResult(False, self.name, note, reason=f"email 发送失败: {exc}")
        return SendResult(True, self.name, note)


class WebSocketChannel:
    """WebSocket 通道（复用既有 /ws 连接，由外部注入广播器）。

    ``broadcaster``：``async (frame: dict) -> None``，将帧广播给已连接客户端；
    未注入（无连接）时视为不可用。
    """

    name = "ws"

    def __init__(
        self,
        broadcaster: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self._broadcaster = broadcaster

    @property
    def available(self) -> bool:
        return self._broadcaster is not None

    async def deliver(self, note: Notification) -> SendResult:
        if not self.available:
            return SendResult(False, self.name, note, reason="无 WS 广播器/连接")
        frame = {
            "type": "notification",
            "event": note.event,
            "message": note.message,
            "priority": note.priority,
        }
        try:
            assert self._broadcaster is not None  # available 已判空，窄化类型
            await self._broadcaster(frame)
        except Exception as exc:
            return SendResult(False, self.name, note, reason=f"ws 广播失败: {exc}")
        return SendResult(True, self.name, note)


# ---- 统一入口 ---------------------------------------------------------------


class Notifier:
    """三通道统一推送入口。

    - ``send(...)``：统一入口，按 channel key 转发到对应通道（异步）；
      未知通道返回未送达结果（不抛）。
    - ``sent``：记录全部推送尝试（含未送达），字段语义对齐 D 的 ``MockNotifier.sent``。
    - 通道可构造时替换（测试注入 / 真实接线均可）。
    """

    def __init__(
        self,
        wecom: WeComBotChannel | None = None,
        email: EmailChannel | None = None,
        ws: WebSocketChannel | None = None,
    ) -> None:
        self.channels: dict[str, Any] = {
            "wecom_bot": wecom or WeComBotChannel(),
            "email": email or EmailChannel(),
            "ws": ws or WebSocketChannel(),
        }
        self.sent: list[Notification] = []

    async def send(
        self,
        event: str,
        channel: str,
        message: str,
        priority: str = "P1",
    ) -> SendResult:
        """统一推送入口：构造 Notification 并按通道转发；任何失败均不抛。"""
        note = Notification(event=event, channel=channel, message=message, priority=priority)
        self.sent.append(note)
        target = self.channels.get(channel)
        if target is None:
            return SendResult(False, channel, note, reason=f"未知通道: {channel}")
        try:
            return await target.deliver(note)
        except Exception as exc:  # 兜底：通道实现的意外异常也不得打断主流程
            return SendResult(False, channel, note, reason=f"通道异常: {exc}")

    def available_channels(self) -> list[str]:
        """当前凭证就绪的通道列表。"""
        return [name for name, ch in self.channels.items() if ch.available]


# ---- 默认传输实现（标准库，线程池执行避免阻塞事件循环） -----------------------


def _default_wecom_post(webhook: str, payload: dict[str, Any]) -> None:
    """标准库 urllib POST 企业微信 webhook（同步，跑在线程池）。"""
    import urllib.request

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        webhook, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


def _default_smtp_send(
    host: str, port: int, user: str, password: str, to: str, subject: str, body: str
) -> None:
    """标准库 smtplib SMTP_SSL 发送邮件（同步，跑在线程池）。"""
    import smtplib
    from email.mime.text import MIMEText

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    with smtplib.SMTP_SSL(host, port, timeout=10) as server:
        server.login(user, password)
        server.sendmail(user, [to], msg.as_string())
