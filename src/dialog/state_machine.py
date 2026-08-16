"""对话状态机（第 5 周，A 职责）。

为脚本改写多轮对话提供状态存储与流转能力：会话创建/获取/删除、
状态转换（含回退栈快照）、字段收集、多级回退与 TTL 过期清理。

契约来源：docs/week5-A-state-machine-design.md §二/§三（两份验收测试
test_session_management.py 与 test_rollback_branch.py 的冲突裁决结果）：
- 回退栈统一为 ``(state, fields 快照)`` 元组，rollback 同时恢复状态与字段；
- ``update_state`` 与 ``transition`` 为同一逻辑的两个方法名（两份测试各用其一）；
- ``.sessions`` 与 ``.contexts`` 为同一容器的双别名（测试直接索引与 in 判断）；
- TTL 默认真实时钟（超时用例用 time.sleep 实测），支持注入时钟加速单测；
  ``ttl <= 0`` 表示不过期（无 TTL 语义的测试场景构造时传 0）。

与第 3 周对话层的关系：Session（对话历史）与本层 DialogContext（状态机）
并行存在，通过 session_id 关联；Redis 存储沿用 store.py 工厂预留入口，
当前为内存实现。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

NowFn = Callable[[], float]


class DialogState(Enum):
    """对话状态枚举（7 态超集，与 project_plan §3.7 状态图一致）。

    ROLLBACK 成员保留但无转换指向它——回退在验收用例中是栈操作语义
    而非驻留状态；保留以兼容含 ROLLBACK 的测试枚举定义。
    """

    INIT = "init"
    IDENTIFY = "identify"
    COLLECT = "collect"
    CONFIRM = "confirm"
    APPLY = "apply"
    ROLLBACK = "rollback"
    DONE = "done"


@dataclass
class DialogContext:
    """对话上下文（超集结构，同时满足两份验收测试的字段约定）。

    - ``collected_fields``: 已收集的参数（分区/GPU/时长等）。
    - ``history``: 对话消息历史（OpenAI 风格 dict 列表）。
    - ``rollback_stack``: 回退栈，元素为 ``(状态, 字段快照)``。
    - ``ttl``: 过期秒数，``<=0`` 表示不过期。
    """

    session_id: str
    state: DialogState = DialogState.INIT
    collected_fields: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, str]] = field(default_factory=list)
    rollback_stack: list[tuple[DialogState, dict[str, Any]]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    ttl: int = 3600

    def is_expired(self, at: float | None = None) -> bool:
        """是否已超过 TTL。``ttl <= 0`` 表示永不过期。"""
        if self.ttl <= 0:
            return False
        now = at if at is not None else time.time()
        return now - self.last_active > self.ttl


class DialogManager:
    """对话状态管理器：会话生命周期 + 状态流转 + 多级回退。

    容器同时暴露 ``sessions`` / ``contexts`` 两个属性别名，
    分别对应两份验收测试的直接访问方式。
    """

    def __init__(self, ttl: int = 3600, now_fn: NowFn = time.time) -> None:
        self.ttl = ttl
        self._now = now_fn
        self._contexts: dict[str, DialogContext] = {}

    @property
    def sessions(self) -> dict[str, DialogContext]:
        """会话容器（test_session_management 侧访问名）。"""
        return self._contexts

    @property
    def contexts(self) -> dict[str, DialogContext]:
        """会话容器（test_rollback_branch 侧访问名）。"""
        return self._contexts

    def create_session(self, session_id: str) -> DialogContext:
        """创建新会话（重复 id 覆盖旧会话），初始状态 INIT。"""
        context = DialogContext(
            session_id=session_id,
            ttl=self.ttl,
            created_at=self._now(),
            last_active=self._now(),
        )
        self._contexts[session_id] = context
        return context

    def get_session(self, session_id: str) -> DialogContext | None:
        """获取会话；不存在或已过期返回 None。

        过期会话惰性删除（真删容器条目）；命中时刷新 last_active，
        实现"活动重置计时器"语义。
        """
        context = self._contexts.get(session_id)
        if context is None:
            return None
        if context.is_expired(self._now()):
            del self._contexts[session_id]
            return None
        context.last_active = self._now()
        return context

    def update_state(self, session_id: str, new_state: DialogState) -> bool:
        """状态转换：先把 ``(当前状态, 字段快照)`` 压入回退栈，再置新状态。

        会话不存在返回 False。
        """
        context = self.get_session(session_id)
        if context is None:
            return False
        context.rollback_stack.append((context.state, dict(context.collected_fields)))
        context.state = new_state
        return True

    # 同义方法名：test_rollback_branch 侧契约使用 transition
    transition = update_state

    def collect_field(self, session_id: str, field_name: str, value: Any) -> bool:
        """收集一个字段（不入回退栈；快照在下次状态转换时生成）。"""
        context = self.get_session(session_id)
        if context is None:
            return False
        context.collected_fields[field_name] = value
        return True

    def rollback(self, session_id: str) -> DialogState | None:
        """回退一步：弹出栈顶快照，恢复状态与字段，返回恢复后的状态。

        会话不存在或栈空返回 None。
        """
        context = self.get_session(session_id)
        if context is None or not context.rollback_stack:
            return None
        prev_state, prev_fields = context.rollback_stack.pop()
        context.state = prev_state
        context.collected_fields = prev_fields
        return context.state

    def rollback_to_init(self, session_id: str) -> bool:
        """回退到初始状态：清空回退栈与已收集字段，状态置 INIT。"""
        context = self.get_session(session_id)
        if context is None:
            return False
        context.rollback_stack.clear()
        context.state = DialogState.INIT
        context.collected_fields.clear()
        return True

    def get_rollback_depth(self, session_id: str) -> int:
        """可回退步数（回退栈深度）；会话不存在返回 0。"""
        context = self._contexts.get(session_id)
        if context is None:
            return 0
        return len(context.rollback_stack)

    def delete_session(self, session_id: str) -> bool:
        """删除会话；存在并删除返回 True，否则 False。"""
        if session_id in self._contexts:
            del self._contexts[session_id]
            return True
        return False


__all__ = ["DialogContext", "DialogManager", "DialogState", "NowFn"]
