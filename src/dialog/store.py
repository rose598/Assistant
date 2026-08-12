"""会话存储抽象（内存 <-> Redis 可切换）。

第 3 周周三交付物（A 职责）：为 ``Session`` 提供上下层解耦的存取接口。

设计要点：
- ``SessionStore`` Protocol 定义统一存取协议：``load/save/delete/list``。
- ``MemorySessionStore``：进程内 dict 实现，天然适合开发/单测；读取时惰性清理过期会话。
- ``create_session_store`` 工厂：当前返回内存实现；将来接入 Redis / SQLite 时
  只需替换工厂返回实现，上层（session 管理、API/ws）无需改动。
- 序列化辅助 ``session_to_dict``/``session_from_dict``：把 Session 转成纯 dict /
  从 dict 重建，供 Redis / 落盘等跨进程场景使用（内存版直接存对象，不依赖它）。

真实 Redis 依赖（``redis`` 包）暂未引入（见 pyproject），此处仅预留接口与工厂入口。
"""

from __future__ import annotations

import time
from typing import Any, Protocol

from src.dialog.session import NowFn, Session

StoreData = dict[str, Any]


class SessionStore(Protocol):
    """会话存取协议。实现需线程/异步安全（由调用方保证串行即可）。"""

    def load(self, session_id: str) -> Session | None:
        """按 id 取回会话；不存在或已过期返回 None。"""
        ...

    def save(self, session: Session) -> None:
        """保存/更新一个会话。"""
        ...

    def delete(self, session_id: str) -> bool:
        """删除会话；存在则返回 True，否则 False。"""
        ...

    def list_sessions(self) -> list[str]:
        """返回当前所有未过期会话 id 列表。"""
        ...


class MemorySessionStore:
    """进程内字典实现的会话存储。

    - ``_store``: session_id -> Session
    - 读取时惰性清理：遇到已过期会话即删除并跳过，避免手动定时清理。
    - ``max_sessions`` 上限用于防止无界增长（默认不限制，0 表示不限）。
    """

    def __init__(self, max_sessions: int = 0) -> None:
        self.max_sessions = max(0, max_sessions)
        self._store: dict[str, Session] = {}

    def load(self, session_id: str) -> Session | None:
        session = self._store.get(session_id)
        if session is None:
            return None
        if session.is_expired():
            del self._store[session_id]
            return None
        return session

    def save(self, session: Session) -> None:
        if self.max_sessions > 0 and session.session_id not in self._store:
            while len(self._store) >= self.max_sessions:
                # 淘汰最旧会话(按创建时间排序)
                oldest_id = min(
                    self._store.keys(),
                    key=lambda sid: self._store[sid].session_created_at,
                )
                del self._store[oldest_id]
        self._store[session.session_id] = session

    def delete(self, session_id: str) -> bool:
        if session_id in self._store:
            del self._store[session_id]
            return True
        return False

    def list_sessions(self) -> list[str]:
        expired = [sid for sid, s in self._store.items() if s.is_expired()]
        for sid in expired:
            del self._store[sid]
        return sorted(self._store.keys())

    def __len__(self) -> int:
        return len(self._store)


def session_to_dict(session: Session) -> StoreData:
    """把 Session 序列化为纯 dict（供 Redis / 落盘使用）。

    不包含 ``_now``（函数不可序列化），重建时需重新注入时钟。
    """
    return {
        "session_id": session.session_id,
        "max_rounds": session.max_rounds,
        "ttl_seconds": session.ttl_seconds,
        "messages": session.get_messages(),
        "created_at": session.session_created_at,
        "last_active": session.last_active,
    }


def session_from_dict(data: StoreData, now_fn: NowFn | None = None) -> Session:
    """从 dict 重建 Session（``session_to_dict`` 的逆操作）。

    缺失字段使用 Session 默认值；``now_fn`` 默认取真实时钟。
    ``system`` 消息会保留在 messages 中，不单独传参。
    """
    if now_fn is None:
        now_fn = time.time
    session = Session(
        session_id=str(data["session_id"]),
        max_rounds=int(data.get("max_rounds", 10)),
        ttl_seconds=float(data.get("ttl_seconds", 3600.0)),
        now_fn=now_fn,
    )
    session._conv.messages = [dict(m) for m in data.get("messages", [])]
    session._conv.created_at = float(data.get("created_at", now_fn()))
    session._conv.last_active = float(data.get("last_active", session._conv.created_at))
    return session


def create_session_store(config: Any | None = None) -> SessionStore:
    """工厂：创建会话存储实现。

    当前返回 ``MemorySessionStore``；将来接入 Redis / SQLite 时在此替换入口，
    上层无需改动。``config`` 预留参数（如 redis_url、max_sessions）。
    """
    max_sessions = 0
    if config is not None and hasattr(config, "max_sessions"):
        max_sessions = int(config.max_sessions)
    return MemorySessionStore(max_sessions=max_sessions)


__all__ = [
    "MemorySessionStore",
    "SessionStore",
    "StoreData",
    "create_session_store",
    "session_from_dict",
    "session_to_dict",
]
