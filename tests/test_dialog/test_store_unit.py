"""会话存储（SessionStore）单元测试.

覆盖:
- 内存存储的 load/save/delete/list。
- 读取时的惰性过期清理（用注入时钟，避免真实 sleep）。
- 序列化往返（session_to_dict -> session_from_dict 保真）。
- 工厂 create_session_store 的可切换入口与 max_sessions 上限。
"""

from __future__ import annotations

import pytest

from src.dialog.session import Session
from src.dialog.store import (
    MemorySessionStore,
    create_session_store,
    session_from_dict,
    session_to_dict,
)


class _Clock:
    """可手动的假时钟."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, delta: float) -> None:
        self.now += delta


class TestMemoryStoreBasic:
    """内存存储的基本增删查."""

    @pytest.fixture
    def store(self) -> MemorySessionStore:
        return MemorySessionStore()

    def test_save_and_load(self, store: MemorySessionStore) -> None:
        s = Session("s1")
        s.add_message("user", "你好")
        store.save(s)
        loaded = store.load("s1")
        assert loaded is not None
        assert loaded.session_id == "s1"
        assert loaded.get_messages()[0]["content"] == "你好"

    def test_load_missing_returns_none(self, store: MemorySessionStore) -> None:
        assert store.load("nope") is None

    def test_delete_existing(self, store: MemorySessionStore) -> None:
        store.save(Session("s1"))
        assert store.delete("s1") is True
        assert store.load("s1") is None

    def test_delete_missing_returns_false(self, store: MemorySessionStore) -> None:
        assert store.delete("nope") is False

    def test_list_sessions(self, store: MemorySessionStore) -> None:
        store.save(Session("s2"))
        store.save(Session("s1"))
        assert store.list_sessions() == ["s1", "s2"]

    def test_update_overwrites(self, store: MemorySessionStore) -> None:
        s = Session("s1")
        s.add_message("user", "第一轮")
        store.save(s)
        s2 = Session("s1")
        s2.add_message("user", "第二轮")
        store.save(s2)
        loaded = store.load("s1")
        assert loaded is not None
        assert loaded.get_messages()[0]["content"] == "第二轮"


class TestMemoryStoreExpiry:
    """读取时惰性清理过期会话."""

    def test_expired_session_evicted_on_load(self) -> None:
        clock = _Clock()
        store = MemorySessionStore()
        s = Session("s1", ttl_seconds=3600, now_fn=clock)
        store.save(s)
        clock.advance(3601)
        assert store.load("s1") is None

    def test_fresh_session_survives(self) -> None:
        clock = _Clock()
        store = MemorySessionStore()
        s = Session("s1", ttl_seconds=3600, now_fn=clock)
        store.save(s)
        clock.advance(100)
        assert store.load("s1") is not None

    def test_list_excludes_expired(self) -> None:
        clock = _Clock()
        store = MemorySessionStore()
        store.save(Session("keep", ttl_seconds=0, now_fn=clock))
        expired = Session("gone", ttl_seconds=10, now_fn=clock)
        store.save(expired)
        clock.advance(20)
        assert store.list_sessions() == ["keep"]
        assert store.load("gone") is None

    def test_activity_reset_extends_life(self) -> None:
        clock = _Clock()
        store = MemorySessionStore()
        s = Session("s1", ttl_seconds=3600, now_fn=clock)
        store.save(s)
        clock.advance(3500)
        s.add_message("user", "仍在")
        store.save(s)
        clock.advance(100)
        assert store.load("s1") is not None


class TestMemoryStoreCapacity:
    """max_sessions 上限淘汰策略."""

    def test_capacity_evicts_oldest(self) -> None:
        store = MemorySessionStore(max_sessions=2)
        store.save(Session("a"))
        store.save(Session("b"))
        store.save(Session("c"))
        assert store.load("a") is None  # 最旧被淘汰
        assert store.load("b") is not None
        assert store.load("c") is not None

    def test_zero_capacity_unlimited(self) -> None:
        store = MemorySessionStore(max_sessions=0)
        for i in range(100):
            store.save(Session(f"s{i}"))
        assert len(store) == 100


class TestSessionSerialization:
    """Session 序列化往返保真."""

    def test_roundtrip_preserves_messages(self) -> None:
        s = Session("s1", system="你是助手")
        s.add_message("user", "q1")
        s.add_message("assistant", "a1")
        data = session_to_dict(s)
        restored = session_from_dict(data)
        assert restored.session_id == "s1"
        assert restored.get_messages() == s.get_messages()

    def test_roundtrip_preserves_meta(self) -> None:
        clock = _Clock()
        s = Session("s1", max_rounds=5, ttl_seconds=7200, now_fn=clock)
        s.add_message("user", "x")
        data = session_to_dict(s)
        restored = session_from_dict(data, now_fn=clock)
        assert restored.max_rounds == 5
        assert restored.ttl_seconds == 7200
        assert restored.session_created_at == s.session_created_at
        assert restored.last_active == s.last_active

    def test_roundtrip_defaults_for_missing(self) -> None:
        restored = session_from_dict({"session_id": "s1"})
        assert restored.session_id == "s1"
        assert restored.max_rounds == 10
        assert restored.ttl_seconds == 3600.0

    def test_data_is_pure_dict(self) -> None:
        s = Session("s1")
        s.add_message("user", "q")
        data = session_to_dict(s)
        assert data["session_id"] == "s1"
        assert isinstance(data["messages"], list)
        assert data["messages"][0]["role"] == "user"


class TestSessionStoreFactory:
    """工厂入口与可切换性."""

    def test_factory_returns_memory_store(self) -> None:
        store = create_session_store()
        assert isinstance(store, MemorySessionStore)

    def test_factory_roundtrip_via_protocol(self) -> None:
        store = create_session_store()
        s = Session("s1")
        s.add_message("user", "q")
        store.save(s)
        assert store.load("s1") is not None
