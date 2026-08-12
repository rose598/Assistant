"""对话管理模块：会话历史 / 会话存储。

对外暴露第 3 周周三交付物（A 职责）：
- ``Session`` / ``Conversation``：单会话多轮对话逻辑（session.py）
- ``SessionStore``/``MemorySessionStore``/``create_session_store``：存储抽象（store.py）

真实 Redis 存储为预留接入点，当前默认内存实现（见 store.create_session_store）。
"""

from src.dialog.session import Conversation, Message, NowFn, Session
from src.dialog.store import (
    MemorySessionStore,
    SessionStore,
    create_session_store,
)

__all__ = [
    "Conversation",
    "MemorySessionStore",
    "Message",
    "NowFn",
    "Session",
    "SessionStore",
    "create_session_store",
]
