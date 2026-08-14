"""对话历史管理（会话级）。

第 3 周周三交付物（A 职责）：为单一会话保存多轮对话消息，
维护最近 N 轮（默认 10），并支持 TTL 过期（默认 1 小时）。

设计要点：
- 消息为 OpenAI 风格 ``{"role": ..., "content": ...}``，便于直接喂给 LLM。
- 维护"最近 max_history_rounds 轮"，超出的历史截断（保留 system 前缀）。
- TTL 过期通过注入的时钟函数判断，便于测试（无需真实 sleep）。
- 不绑定具体存储（内存/Redis 由 store 层实现），本类只管"会话逻辑"。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

NowFn = Callable[[], float]

Message = dict[str, str]


@dataclass
class Conversation:
    """单会话的多轮对话状态。

    - ``messages``: 完整历史（含可选的 system 前缀）。
    - ``created_at`` / ``last_active``: 用于 TTL 判断。
    """

    messages: list[Message] = field(default_factory=list)
    created_at: float = 0.0
    last_active: float = 0.0

    def __post_init__(self) -> None:
        if self.created_at == 0.0:
            self.created_at = self.last_active


class Session:
    """一个用户会话：封装多轮对话的增删、截断、过期判断。"""

    def __init__(
        self,
        session_id: str,
        max_rounds: int = 10,
        ttl_seconds: float = 3600.0,
        now_fn: NowFn = time.time,
        system: str | None = None,
    ) -> None:
        self.session_id = session_id
        self.max_rounds = max(1, max_rounds)
        self.ttl_seconds = max(0.0, ttl_seconds)
        self._now = now_fn
        self._conv = Conversation(created_at=now_fn(), last_active=now_fn())
        if system:
            self._conv.messages.append({"role": "system", "content": system})

    @property
    def session_created_at(self) -> float:
        return self._conv.created_at

    @property
    def last_active(self) -> float:
        return self._conv.last_active

    def is_expired(self, at: float | None = None) -> bool:
        """是否已超过 TTL 过期。ttl_seconds<=0 表示永不过期。"""
        now = at if at is not None else self._now()
        if self.ttl_seconds <= 0:
            return False
        return now - self.last_active > self.ttl_seconds

    def add_message(self, role: str, content: str) -> None:
        """追加一条消息并重置活跃时间。"""
        self._conv.messages.append({"role": role, "content": content})
        self._conv.last_active = self._now()
        self._trim_history()

    def _trim_history(self) -> None:
        """按"轮"截断：每轮=1 user + 1 assistant（或仅 user）。

        保留 system 前缀；超出 max_rounds 的旧轮丢弃。
        """
        msgs = self._conv.messages
        system_msgs = [m for m in msgs if m["role"] == "system"]
        body = [m for m in msgs if m["role"] != "system"]
        # 一轮 = 一个 user 消息（其后可能跟 assistant），按 user 数量控制轮数
        user_indices = [i for i, m in enumerate(body) if m["role"] == "user"]
        if len(user_indices) > self.max_rounds:
            cut = user_indices[-self.max_rounds]
            body = body[cut:]
        self._conv.messages = system_msgs + body

    def get_messages(self) -> list[Message]:
        """返回当前完整消息（含 system 前缀），供 LLM/检索使用。"""
        return list(self._conv.messages)

    def get_recent_context(self) -> str:
        """拼一段便于人读/检索的最近对话文本。"""
        parts = [f"{m['role']}: {m['content']}" for m in self._conv.messages]
        return "\n".join(parts)

    def clear(self) -> None:
        """清空历史（保留 session 元数据，重置活跃时间）。"""
        self._conv.messages = [m for m in self._conv.messages if m["role"] == "system"]
        self._conv.last_active = self._now()

    def size(self) -> int:
        """当前消息条数。"""
        return len(self._conv.messages)

    def rounds(self) -> int:
        """当前对话轮数（按 user 消息数计）。"""
        return sum(1 for m in self._conv.messages if m["role"] == "user")


__all__ = ["Conversation", "Session", "Message", "NowFn"]
