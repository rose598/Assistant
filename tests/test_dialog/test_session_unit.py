"""对话历史管理（Session）单元测试.

覆盖：增删、按轮截断、TTL 过期、清空、system 前缀保留、多轮计数。
用注入时钟测试过期，避免真实 sleep。
"""

from __future__ import annotations

import pytest

from src.dialog.session import Session


class _Clock:
    """可手动的假时钟。"""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, delta: float) -> None:
        self.now += delta


class TestSession:
    """Session 核心行为。"""

    def test_add_and_get_messages(self) -> None:
        s = Session("s1")
        s.add_message("user", "你好")
        s.add_message("assistant", "你好，有什么可以帮你")
        msgs = s.get_messages()
        assert msgs[0] == {"role": "user", "content": "你好"}
        assert msgs[1]["role"] == "assistant"
        assert s.size() == 2
        assert s.rounds() == 1

    def test_system_prefix_retained(self) -> None:
        s = Session("s1", system="你是助手")
        s.add_message("user", "提问")
        assert s.get_messages()[0] == {"role": "system", "content": "你是助手"}

    def test_trim_keeps_last_max_rounds(self) -> None:
        s = Session("s1", max_rounds=2)
        for i in range(5):
            s.add_message("user", f"q{i}")
            s.add_message("assistant", f"a{i}")
        assert s.rounds() == 2
        texts = [m["content"] for m in s.get_messages()]
        assert "q0" not in texts
        assert "q3" in texts and "q4" in texts

    def test_trim_preserves_system(self) -> None:
        s = Session("s1", max_rounds=1, system="sys")
        for i in range(3):
            s.add_message("user", f"q{i}")
            s.add_message("assistant", f"a{i}")
        msgs = s.get_messages()
        assert msgs[0] == {"role": "system", "content": "sys"}  # system 始终在最前

    def test_not_expired_before_ttl(self) -> None:
        clock = _Clock()
        s = Session("s1", ttl_seconds=3600, now_fn=clock)
        clock.advance(100)
        assert s.is_expired() is False

    def test_expired_after_ttl(self) -> None:
        clock = _Clock()
        s = Session("s1", ttl_seconds=3600, now_fn=clock)
        clock.advance(3601)
        assert s.is_expired() is True

    def test_activity_resets_on_message(self) -> None:
        clock = _Clock()
        s = Session("s1", ttl_seconds=3600, now_fn=clock)
        clock.advance(3500)
        s.add_message("user", "还在吗")  # 活跃时间重置
        clock.advance(100)
        assert s.is_expired() is False

    def test_zero_ttl_never_expires(self) -> None:
        clock = _Clock()
        s = Session("s1", ttl_seconds=0, now_fn=clock)
        clock.advance(1_000_000)
        assert s.is_expired() is False

    def test_clear_keeps_system(self) -> None:
        s = Session("s1", system="sys")
        s.add_message("user", "x")
        s.add_message("assistant", "y")
        s.clear()
        assert s.size() == 1
        assert s.get_messages()[0]["role"] == "system"

    def test_recent_context(self) -> None:
        s = Session("s1")
        s.add_message("user", "q1")
        s.add_message("assistant", "a1")
        ctx = s.get_recent_context()
        assert "user: q1" in ctx
        assert "assistant: a1" in ctx

    def test_unpaired_user_counts_as_round(self) -> None:
        s = Session("s1", max_rounds=3)
        s.add_message("user", "q")
        assert s.rounds() == 1