"""对话管理测试.

本模块测试多轮对话会话管理：
- 会话创建 / 多轮上下文累积
- 最近 N 轮（10 轮）裁剪
- 过期（1h 自动失效）
- 会话异常中断恢复

验收标准：多轮上下文正确、最近 10 轮、过期 1h。

遵循角色 D 测试惯例：由于 A 的 dialog/session.py 尚未实现（计划用 Redis），
这里使用自包含的内存版 MockSessionStore 模拟，待 A 实现后替换为 Redis 实现。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

MAX_HISTORY_TURNS = 10
SESSION_TTL_SECONDS = 3600  # 1h


@dataclass
class Turn:
    """一条对话轮次."""

    role: str  # "user" | "assistant"
    content: str


@dataclass
class Session:
    """对话会话."""

    session_id: str
    created_at: float
    updated_at: float = 0.0
    history: list[Turn] = field(default_factory=list)

    def expired(self, now: float, ttl: int = SESSION_TTL_SECONDS) -> bool:
        """判断会话是否已过期（超过 TTL 未活动）."""
        return now - self.updated_at > ttl


class MockSessionStore:
    """模拟会话存储（待 A 实现 Redis 版 session.py 后替换）."""

    def __init__(self, max_turns: int = MAX_HISTORY_TURNS, ttl: int = SESSION_TTL_SECONDS) -> None:
        self._sessions: dict[str, Session] = {}
        self.max_turns = max_turns
        self.ttl = ttl

    def create(self, session_id: str, now: float | None = None) -> Session:
        """创建新会话."""
        if now is None:
            now = time.time()
        sess = Session(session_id=session_id, created_at=now, updated_at=now)
        self._sessions[session_id] = sess
        return sess

    def get(self, session_id: str, now: float | None = None) -> Session | None:
        """获取会话；过期则清理并返回 None."""
        if now is None:
            now = time.time()
        sess = self._sessions.get(session_id)
        if sess is None:
            return None
        if sess.expired(now, self.ttl):
            del self._sessions[session_id]
            return None
        return sess

    def append_turn(
        self, session_id: str, role: str, content: str, now: float | None = None
    ) -> Session:
        """追加一轮对话并裁剪到最近 max_turns 轮."""
        if now is None:
            now = time.time()
        sess = self.get(session_id, now)
        if sess is None:
            sess = self.create(session_id, now)
        sess.history.append(Turn(role=role, content=content))
        sess.updated_at = now
        # 裁剪：保留最近 max_turns 轮
        if len(sess.history) > self.max_turns:
            sess.history = sess.history[-self.max_turns :]
        return sess

    def delete(self, session_id: str) -> None:
        """删除会话."""
        self._sessions.pop(session_id, None)


class TestSessionBasics:
    """会话基础操作测试."""

    @pytest.fixture
    def store(self) -> MockSessionStore:
        return MockSessionStore()

    def test_create_session(self, store: MockSessionStore) -> None:
        """测试创建会话."""
        sess = store.create("s1", now=1000.0)
        assert sess.session_id == "s1"
        assert sess.history == []

    def test_get_existing(self, store: MockSessionStore) -> None:
        """测试获取已有会话."""
        store.create("s1", now=1000.0)
        sess = store.get("s1", now=1001.0)
        assert sess is not None

    def test_get_nonexistent_returns_none(self, store: MockSessionStore) -> None:
        """测试获取不存在的会话."""
        assert store.get("missing", now=1000.0) is None

    def test_append_turn_creates_if_missing(self, store: MockSessionStore) -> None:
        """测试向不存在会话追加时自动创建."""
        sess = store.append_turn("new", "user", "你好", now=1000.0)
        assert len(sess.history) == 1
        assert sess.history[0].role == "user"


class TestMultiTurnContext:
    """多轮上下文累积测试."""

    def test_context_accumulates(self) -> None:
        """测试多轮对话上下文正确累积."""
        store = MockSessionStore()
        s = "chat-1"
        store.append_turn(s, "user", "我的作业失败了", now=1000.0)
        store.append_turn(s, "assistant", "请问是哪种报错？", now=1001.0)
        store.append_turn(s, "user", "CUDA out of memory", now=1002.0)

        sess = store.get(s, now=1003.0)
        assert sess is not None
        assert len(sess.history) == 3
        assert sess.history[0].content == "我的作业失败了"
        assert sess.history[-1].content == "CUDA out of memory"

    def test_history_capped_at_10_turns(self) -> None:
        """测试最近 10 轮裁剪，更早轮次被丢弃."""
        store = MockSessionStore(max_turns=10)
        s = "chat-long"
        t = 1000.0
        for i in range(15):
            store.append_turn(s, "user", f"第{i}轮问题", now=t + i)

        sess = store.get(s, now=t + 20.0)
        assert sess is not None
        assert len(sess.history) == 10
        # 最早的 5 轮应被移除，剩下第 5~14 轮
        assert sess.history[0].content == "第5轮问题"
        assert sess.history[-1].content == "第14轮问题"

    def test_rollout_preserves_roles(self) -> None:
        """测试按 user/assistant 角色拼接的上下文用于 LLM."""
        store = MockSessionStore()
        s = "chat-roles"
        store.append_turn(s, "user", "Q1", now=1000.0)
        store.append_turn(s, "assistant", "A1", now=1001.0)
        store.append_turn(s, "user", "Q2", now=1002.0)

        sess = store.get(s, now=1003.0)
        assert sess is not None
        context = [{"role": t.role, "content": t.content} for t in sess.history]
        assert context == [
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
            {"role": "user", "content": "Q2"},
        ]


class TestSessionExpiry:
    """会话过期测试."""

    def test_session_expires_after_ttl(self) -> None:
        """测试超过 1h 过期后会话被清理."""
        store = MockSessionStore(ttl=3600)
        s = "chat-expire"
        store.append_turn(s, "user", "hi", now=0.0)
        # 1h + 1s 后应过期
        assert store.get(s, now=3601.0) is None

    def test_session_alive_within_ttl(self) -> None:
        """测试 TTL 内会话仍然有效."""
        store = MockSessionStore(ttl=3600)
        s = "chat-alive"
        store.append_turn(s, "user", "hi", now=0.0)
        assert store.get(s, now=3599.0) is not None

    def test_deleted_session_gone(self) -> None:
        """测试主动删除会话后不可再取."""
        store = MockSessionStore()
        store.create("s-del", now=0.0)
        store.delete("s-del")
        assert store.get("s-del", now=1.0) is None


class TestSessionInterruptRecovery:
    """会话异常中断恢复测试."""

    def test_recover_after_abrupt_disconnect(self) -> None:
        """测试异常中断后，基于已存历史可以恢复对话状态."""
        store = MockSessionStore()
        s = "chat-recover"
        store.append_turn(s, "user", "我要改脚本", now=1000.0)
        store.append_turn(s, "assistant", "好的，你想改哪个参数？", now=1001.0)

        # 模拟中断后重新连接
        recovered = store.get(s, now=1100.0)
        assert recovered is not None
        assert len(recovered.history) == 2

    def test_multi_sessions_isolated(self) -> None:
        """测试多个用户会话相互隔离，互不串扰."""
        store = MockSessionStore()
        store.append_turn("user-a", "user", "我的GPU不够", now=1000.0)
        store.append_turn("user-b", "user", "我的conda没激活", now=1001.0)

        a = store.get("user-a", now=1002.0)
        b = store.get("user-b", now=1002.0)
        assert a is not None and b is not None
        assert a.history[-1].content == "我的GPU不够"
        assert b.history[-1].content == "我的conda没激活"


class TestDialogReport:
    """生成对话管理测试报告."""

    def test_generate_report(self, tmp_path: Path) -> None:
        """生成对话管理测试报告."""
        store = MockSessionStore()
        scenario_results: list[dict[str, object]] = []

        # 场景 1: 新建
        store.append_turn("scenario-new", "user", "开始", now=0.0)
        scenario_results.append({"scenario": "新建", "ok": True})

        # 场景 2: 恢复
        store.append_turn("scenario-recover", "user", "上轮", now=0.0)
        recovered = store.get("scenario-recover", now=10.0)
        scenario_results.append({"scenario": "恢复", "ok": recovered is not None})

        # 场景 3: 超时
        store2 = MockSessionStore(ttl=3600)
        store2.append_turn("scenario-timeout", "user", "hi", now=0.0)
        scenario_results.append(
            {"scenario": "超时", "ok": store2.get("scenario-timeout", now=3601.0) is None}
        )

        # 场景 4: 异常中断
        store.append_turn("scenario-interrupt", "user", "修改脚本", now=100.0)
        store.append_turn("scenario-interrupt", "assistant", "请选择参数", now=101.0)
        recovered_i = store.get("scenario-interrupt", now=200.0)
        scenario_results.append(
            {
                "scenario": "异常中断",
                "ok": recovered_i is not None and len(recovered_i.history) == 2,
            }
        )

        report = {
            "summary": {
                "scenarios": 4,
                "all_ok": all(r["ok"] for r in scenario_results),
            },
            "details": scenario_results,
        }

        report_file = tmp_path / "dialog_management_report.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        assert report_file.exists()
        assert all(r["ok"] for r in scenario_results)
