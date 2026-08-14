"""三通道推送 Notifier 测试.

覆盖（plan §第4周周三 + D 测试语义 MockNotifier）:
- Notification 字段（event/channel/message/priority，对齐 D 的 Notification）。
- 通道 key 集合 = {wecom_bot, email, ws}（对齐 D 的 test_all_channels_supported）。
- 统一入口 send 按通道转发 + 未知通道不抛。
- 各通道凭证未配置时优雅降级（delivered=False + reason，不抛异常）。
- 注入传输函数验证真实送达 + 传输异常降级。
"""

from __future__ import annotations

from typing import Any

import pytest

from src.monitor.notifier import (
    CHANNELS,
    EmailChannel,
    Notification,
    Notifier,
    WebSocketChannel,
    WeComBotChannel,
)


class TestNotification:
    """Notification 数据类字段（与 D 测试一致）."""

    def test_fields(self) -> None:
        note = Notification(event="queue_congestion", channel="wecom_bot",
                            message="排队作业 > 20", priority="P0")
        assert note.event == "queue_congestion"
        assert note.channel == "wecom_bot"
        assert note.message == "排队作业 > 20"
        assert note.priority == "P0"

    def test_priority_default_p1(self) -> None:
        note = Notification(event="idle_alert", channel="ws", message="空闲 > 60%")
        assert note.priority == "P1"

    def test_channel_keys_match_d_tests(self) -> None:
        assert set(CHANNELS) == {"wecom_bot", "email", "ws"}


def _empty_notifier() -> Notifier:
    """显式空凭证构造（不依赖环境变量，测试确定性）."""
    return Notifier(
        wecom=WeComBotChannel(webhook=""),
        email=EmailChannel(host="", user="", password=""),
        ws=WebSocketChannel(broadcaster=None),
    )


class TestGracefulDegradation:
    """凭证未配置 → 返回未送达，不抛异常."""

    @pytest.mark.asyncio
    async def test_all_channels_unconfigured_not_delivered(self) -> None:
        n = _empty_notifier()
        for ch in CHANNELS:
            result = await n.send("evt", ch, "msg", "P1")
            assert result.delivered is False
            assert result.reason != ""
            assert result.channel == ch

    @pytest.mark.asyncio
    async def test_available_channels_empty(self) -> None:
        n = _empty_notifier()
        assert n.available_channels() == []

    @pytest.mark.asyncio
    async def test_unknown_channel_no_raise(self) -> None:
        n = _empty_notifier()
        result = await n.send("evt", "telegram", "msg")
        assert result.delivered is False
        assert "未知通道" in result.reason

    @pytest.mark.asyncio
    async def test_sent_records_attempts_including_undelivered(self) -> None:
        n = _empty_notifier()
        await n.send("queue_congestion", "wecom_bot", "排队作业 > 20", "P0")
        await n.send("job_complete", "email", "作业 12345 已完成", "P0")
        await n.send("partition_down", "ws", "分区 Students 已 down", "P1")
        assert len(n.sent) == 3
        assert {note.channel for note in n.sent} == {"wecom_bot", "email", "ws"}


class TestWeComChannel:
    """企业微信 Bot 通道."""

    @pytest.mark.asyncio
    async def test_empty_webhook_unavailable(self) -> None:
        ch = WeComBotChannel(webhook="")
        assert ch.available is False
        note = Notification("e", "wecom_bot", "m")
        result = await ch.deliver(note)
        assert result.delivered is False
        assert "未配置" in result.reason

    @pytest.mark.asyncio
    async def test_injected_poster_delivers(self) -> None:
        captured: list[tuple[str, dict[str, Any]]] = []

        async def poster(webhook: str, payload: dict[str, Any]) -> None:
            captured.append((webhook, payload))

        ch = WeComBotChannel(webhook="https://qyapi.example/bot?key=k", poster=poster)
        assert ch.available is True
        result = await ch.deliver(Notification("queue_congestion", "wecom_bot", "拥堵", "P0"))
        assert result.delivered is True
        assert captured[0][0] == "https://qyapi.example/bot?key=k"
        payload = captured[0][1]
        assert payload["msgtype"] == "text"
        assert "queue_congestion" in payload["text"]["content"]
        assert "P0" in payload["text"]["content"]

    @pytest.mark.asyncio
    async def test_poster_raises_degrades(self) -> None:
        async def poster(webhook: str, payload: dict[str, Any]) -> None:
            raise ConnectionError("network down")

        ch = WeComBotChannel(webhook="https://x", poster=poster)
        result = await ch.deliver(Notification("e", "wecom_bot", "m"))
        assert result.delivered is False
        assert "发送失败" in result.reason


class TestEmailChannel:
    """Email 通道（smtplib，注入 sender 免真实网络）."""

    @pytest.mark.asyncio
    async def test_no_smtp_unavailable(self) -> None:
        ch = EmailChannel(host="", user="", password="")
        assert ch.available is False
        result = await ch.deliver(Notification("e", "email", "m"))
        assert result.delivered is False
        assert "SMTP" in result.reason

    @pytest.mark.asyncio
    async def test_injected_sender_delivers(self) -> None:
        captured: list[dict[str, Any]] = []

        async def sender(host: str, port: int, user: str, password: str,
                         to: str, subject: str, body: str) -> None:
            captured.append({"host": host, "to": to, "subject": subject, "body": body})

        ch = EmailChannel(host="smtp.example", port=465, user="a@x", password="p",
                          sender=sender)
        assert ch.available is True
        result = await ch.deliver(Notification("job_complete", "email", "作业完成", "P0"))
        assert result.delivered is True
        assert captured[0]["to"] == "a@x"  # 缺省收件人取 SMTP_USER
        assert "job_complete" in captured[0]["subject"]

    @pytest.mark.asyncio
    async def test_sender_raises_degrades(self) -> None:
        async def sender(*args: Any) -> None:
            raise TimeoutError("smtp timeout")

        ch = EmailChannel(host="smtp.example", user="a@x", password="p", sender=sender)
        result = await ch.deliver(Notification("e", "email", "m"))
        assert result.delivered is False


class TestWebSocketChannel:
    """WebSocket 通道（外部注入广播器）."""

    @pytest.mark.asyncio
    async def test_no_broadcaster_unavailable(self) -> None:
        ch = WebSocketChannel(broadcaster=None)
        assert ch.available is False
        result = await ch.deliver(Notification("e", "ws", "m"))
        assert result.delivered is False
        assert "无 WS" in result.reason

    @pytest.mark.asyncio
    async def test_injected_broadcaster_delivers(self) -> None:
        frames: list[dict[str, Any]] = []

        async def broadcast(frame: dict[str, Any]) -> None:
            frames.append(frame)

        ch = WebSocketChannel(broadcaster=broadcast)
        result = await ch.deliver(Notification("partition_down", "ws", "分区 down", "P1"))
        assert result.delivered is True
        assert frames[0]["type"] == "notification"
        assert frames[0]["event"] == "partition_down"

    @pytest.mark.asyncio
    async def test_broadcaster_raises_degrades(self) -> None:
        async def broadcast(frame: dict[str, Any]) -> None:
            raise RuntimeError("client gone")

        ch = WebSocketChannel(broadcaster=broadcast)
        result = await ch.deliver(Notification("e", "ws", "m"))
        assert result.delivered is False


class TestUnifiedSend:
    """统一入口转发."""

    @pytest.mark.asyncio
    async def test_dispatch_to_injected_channels(self) -> None:
        hits: list[str] = []

        async def poster(webhook: str, payload: dict[str, Any]) -> None:
            hits.append("wecom_bot")

        async def broadcast(frame: dict[str, Any]) -> None:
            hits.append("ws")

        n = Notifier(
            wecom=WeComBotChannel(webhook="https://x", poster=poster),
            email=EmailChannel(host="", user="", password=""),
            ws=WebSocketChannel(broadcaster=broadcast),
        )
        r1 = await n.send("queue_congestion", "wecom_bot", "拥堵", "P0")
        r2 = await n.send("partition_down", "ws", "down", "P1")
        r3 = await n.send("job_complete", "email", "完成", "P0")  # email 未配置降级
        assert r1.delivered is True and r2.delivered is True
        assert r3.delivered is False
        assert hits == ["wecom_bot", "ws"]
        assert n.available_channels() == ["wecom_bot", "ws"]
