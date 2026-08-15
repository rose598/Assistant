"""对话管理模块：会话历史 / 会话存储 / 对话状态机。

对外暴露：
- 第 3 周周三交付物（A 职责）：
  ``Session`` / ``Conversation``：单会话多轮对话逻辑（session.py）；
  ``SessionStore``/``MemorySessionStore``/``create_session_store``：存储抽象（store.py）。
- 第 5 周交付物（A 职责）：
  ``DialogState`` / ``DialogContext`` / ``DialogManager``：脚本改写
  多轮对话状态机（state_machine.py，契约见 docs/week5-A-state-machine-design.md）。

真实 Redis 存储为预留接入点，当前默认内存实现（见 store.create_session_store）。
"""

from src.dialog.session import Conversation, Message, NowFn, Session
from src.dialog.state_machine import DialogContext, DialogManager, DialogState
from src.dialog.store import (
    MemorySessionStore,
    SessionStore,
    create_session_store,
)

__all__ = [
    "Conversation",
    "DialogContext",
    "DialogManager",
    "DialogState",
    "MemorySessionStore",
    "Message",
    "NowFn",
    "Session",
    "SessionStore",
    "create_session_store",
]
