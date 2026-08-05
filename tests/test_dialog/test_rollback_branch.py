"""回退与分支场景测试.

测试回退机制和各种分支场景：
- 回退3步
- 回退到 INIT
- 修改后回退
- 分支场景
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import pytest


class DialogState(Enum):
    """对话状态."""

    INIT = "init"
    IDENTIFY = "identify"
    COLLECT = "collect"
    CONFIRM = "confirm"
    APPLY = "apply"
    DONE = "done"


@dataclass
class DialogContext:
    """对话上下文."""

    session_id: str
    state: DialogState = DialogState.INIT
    collected_fields: dict[str, Any] = field(default_factory=dict)
    rollback_stack: list[tuple[DialogState, dict[str, Any]]] = field(default_factory=list)

    def push_state(self) -> None:
        """保存当前状态到回退栈."""
        self.rollback_stack.append((self.state, self.collected_fields.copy()))

    def pop_state(self) -> bool:
        """恢复到上一个状态."""
        if not self.rollback_stack:
            return False
        prev_state, prev_fields = self.rollback_stack.pop()
        self.state = prev_state
        self.collected_fields = prev_fields
        return True


class MockRollbackManager:
    """模拟回退管理器（待 B 实现后替换）."""

    def __init__(self) -> None:
        """初始化回退管理器."""
        self.contexts: dict[str, DialogContext] = {}

    def create_session(self, session_id: str) -> DialogContext:
        """创建会话."""
        context = DialogContext(session_id=session_id)
        self.contexts[session_id] = context
        return context

    def get_session(self, session_id: str) -> DialogContext | None:
        """获取会话."""
        return self.contexts.get(session_id)

    def transition(self, session_id: str, new_state: DialogState) -> bool:
        """状态转换.

        Args:
            session_id: 会话ID.
            new_state: 新状态.

        Returns:
            是否转换成功.
        """
        context = self.contexts.get(session_id)
        if context is None:
            return False
        context.push_state()
        context.state = new_state
        return True

    def collect_field(self, session_id: str, field_name: str, value: Any) -> bool:
        """收集字段."""
        context = self.contexts.get(session_id)
        if context is None:
            return False
        context.collected_fields[field_name] = value
        return True

    def rollback(self, session_id: str) -> DialogState | None:
        """回退一步.

        Args:
            session_id: 会话ID.

        Returns:
            回退后的状态，如果无法回退返回 None.
        """
        context = self.contexts.get(session_id)
        if context is None:
            return None
        if context.pop_state():
            return context.state
        return None

    def rollback_to_init(self, session_id: str) -> bool:
        """回退到初始状态.

        Args:
            session_id: 会话ID.

        Returns:
            是否成功.
        """
        context = self.contexts.get(session_id)
        if context is None:
            return False
        # 清空回退栈，恢复到 INIT
        context.rollback_stack.clear()
        context.state = DialogState.INIT
        context.collected_fields.clear()
        return True

    def get_rollback_depth(self, session_id: str) -> int:
        """获取回退深度.

        Args:
            session_id: 会话ID.

        Returns:
            可以回退的步数.
        """
        context = self.contexts.get(session_id)
        if context is None:
            return 0
        return len(context.rollback_stack)


class TestRollbackMultipleSteps:
    """多步回退测试."""

    @pytest.fixture
    def manager(self) -> MockRollbackManager:
        """返回回退管理器."""
        return MockRollbackManager()

    def test_rollback_three_steps(self, manager: MockRollbackManager) -> None:
        """测试回退3步."""
        manager.create_session("session-001")

        # 前进3步
        manager.transition("session-001", DialogState.IDENTIFY)
        manager.transition("session-001", DialogState.COLLECT)
        manager.transition("session-001", DialogState.CONFIRM)

        context = manager.get_session("session-001")
        assert context is not None
        assert context.state == DialogState.CONFIRM
        assert manager.get_rollback_depth("session-001") == 3

        # 回退3步
        state = manager.rollback("session-001")
        assert state == DialogState.COLLECT

        state = manager.rollback("session-001")
        assert state == DialogState.IDENTIFY

        state = manager.rollback("session-001")
        assert state == DialogState.INIT

    def test_rollback_preserves_data(self, manager: MockRollbackManager) -> None:
        """测试回退保留数据."""
        manager.create_session("session-001")
        manager.transition("session-001", DialogState.COLLECT)
        manager.collect_field("session-001", "partition", "Students")

        # 回退应该恢复到之前的状态（字段为空）
        manager.rollback("session-001")
        context = manager.get_session("session-001")
        assert context is not None
        # 回退后恢复到 INIT 状态，字段被清空
        assert context.state == DialogState.INIT

    def test_rollback_empty_stack(self, manager: MockRollbackManager) -> None:
        """测试空回退栈."""
        manager.create_session("session-001")

        state = manager.rollback("session-001")
        assert state is None

    def test_rollback_depth_tracking(self, manager: MockRollbackManager) -> None:
        """测试回退深度追踪."""
        manager.create_session("session-001")

        assert manager.get_rollback_depth("session-001") == 0

        manager.transition("session-001", DialogState.IDENTIFY)
        assert manager.get_rollback_depth("session-001") == 1

        manager.transition("session-001", DialogState.COLLECT)
        assert manager.get_rollback_depth("session-001") == 2

        manager.rollback("session-001")
        assert manager.get_rollback_depth("session-001") == 1


class TestRollbackToInit:
    """回退到初始状态测试."""

    @pytest.fixture
    def manager(self) -> MockRollbackManager:
        """返回回退管理器."""
        return MockRollbackManager()

    def test_rollback_to_init_clears_state(self, manager: MockRollbackManager) -> None:
        """测试回退到 INIT 清除状态."""
        manager.create_session("session-001")
        manager.transition("session-001", DialogState.IDENTIFY)
        manager.transition("session-001", DialogState.COLLECT)
        manager.transition("session-001", DialogState.CONFIRM)

        manager.rollback_to_init("session-001")

        context = manager.get_session("session-001")
        assert context is not None
        assert context.state == DialogState.INIT
        assert context.collected_fields == {}
        assert context.rollback_stack == []

    def test_rollback_to_init_clears_fields(self, manager: MockRollbackManager) -> None:
        """测试回退到 INIT 清除字段."""
        manager.create_session("session-001")
        manager.transition("session-001", DialogState.COLLECT)
        manager.collect_field("session-001", "partition", "Students")
        manager.collect_field("session-001", "gpu", 1)

        manager.rollback_to_init("session-001")

        context = manager.get_session("session-001")
        assert context is not None
        assert context.collected_fields == {}

    def test_rollback_to_init_nonexistent_session(self, manager: MockRollbackManager) -> None:
        """测试回退不存在的会话."""
        result = manager.rollback_to_init("nonexistent")
        assert result is False


class TestRollbackAfterModification:
    """修改后回退测试."""

    @pytest.fixture
    def manager(self) -> MockRollbackManager:
        """返回回退管理器."""
        return MockRollbackManager()

    def test_rollback_after_field_collection(self, manager: MockRollbackManager) -> None:
        """测试收集字段后回退."""
        manager.create_session("session-001")
        manager.transition("session-001", DialogState.COLLECT)
        manager.collect_field("session-001", "partition", "Students")

        # 回退到上一个状态
        manager.rollback("session-001")

        context = manager.get_session("session-001")
        assert context is not None
        assert context.state == DialogState.INIT

    def test_rollback_multiple_collections(self, manager: MockRollbackManager) -> None:
        """测试多次收集后回退."""
        manager.create_session("session-001")
        manager.transition("session-001", DialogState.COLLECT)
        manager.collect_field("session-001", "partition", "Students")
        manager.collect_field("session-001", "gpu", 1)
        manager.collect_field("session-001", "time", "04:00:00")

        # 回退到上一个状态（INIT）
        manager.rollback("session-001")

        context = manager.get_session("session-001")
        assert context is not None
        # 回退后恢复到 INIT 状态
        assert context.state == DialogState.INIT

    def test_continue_after_rollback(self, manager: MockRollbackManager) -> None:
        """测试回退后继续."""
        manager.create_session("session-001")
        manager.transition("session-001", DialogState.IDENTIFY)
        manager.transition("session-001", DialogState.COLLECT)

        # 回退一步
        manager.rollback("session-001")

        context = manager.get_session("session-001")
        assert context is not None
        assert context.state == DialogState.IDENTIFY

        # 继续前进
        manager.transition("session-001", DialogState.COLLECT)
        manager.collect_field("session-001", "partition", "GPU-RTX5090")

        context = manager.get_session("session-001")
        assert context.state == DialogState.COLLECT
        assert context.collected_fields.get("partition") == "GPU-RTX5090"


class TestBranchScenarios:
    """分支场景测试."""

    @pytest.fixture
    def manager(self) -> MockRollbackManager:
        """返回回退管理器."""
        return MockRollbackManager()

    def test_branch_after_rollback(self, manager: MockRollbackManager) -> None:
        """测试回退后走不同分支."""
        manager.create_session("session-001")
        manager.transition("session-001", DialogState.IDENTIFY)
        manager.transition("session-001", DialogState.COLLECT)
        manager.collect_field("session-001", "partition", "Students")

        # 回退
        manager.rollback("session-001")

        # 走不同分支
        manager.transition("session-001", DialogState.COLLECT)
        manager.collect_field("session-001", "partition", "GPU-RTX5090")

        context = manager.get_session("session-001")
        assert context is not None
        assert context.collected_fields.get("partition") == "GPU-RTX5090"

    def test_multiple_sessions_independent(self, manager: MockRollbackManager) -> None:
        """测试多个会话独立."""
        manager.create_session("session-001")
        manager.create_session("session-002")

        manager.transition("session-001", DialogState.COLLECT)
        manager.collect_field("session-001", "partition", "Students")

        manager.transition("session-002", DialogState.IDENTIFY)

        # 两个会话状态独立
        ctx1 = manager.get_session("session-001")
        ctx2 = manager.get_session("session-002")

        assert ctx1 is not None
        assert ctx2 is not None
        assert ctx1.state == DialogState.COLLECT
        assert ctx2.state == DialogState.IDENTIFY
        assert ctx1.collected_fields.get("partition") == "Students"
        assert ctx2.collected_fields == {}

    def test_rollback_nonexistent_session(self, manager: MockRollbackManager) -> None:
        """测试回退不存在的会话."""
        state = manager.rollback("nonexistent")
        assert state is None

    def test_rollback_depth_after_branch(self, manager: MockRollbackManager) -> None:
        """测试分支后回退深度."""
        manager.create_session("session-001")
        manager.transition("session-001", DialogState.IDENTIFY)
        manager.transition("session-001", DialogState.COLLECT)

        # 回退到 IDENTIFY
        manager.rollback("session-001")

        # 再前进: IDENTIFY -> COLLECT -> CONFIRM
        manager.transition("session-001", DialogState.COLLECT)
        manager.transition("session-001", DialogState.CONFIRM)

        # 回退深度应该是 2 (INIT -> IDENTIFY -> COLLECT)
        # 加上 CONFIRM 是 3
        assert manager.get_rollback_depth("session-001") == 3
