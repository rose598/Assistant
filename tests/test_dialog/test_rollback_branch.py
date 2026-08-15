"""回退与分支场景测试.

测试回退机制和各种分支场景：
- 回退3步
- 回退到 INIT
- 修改后回退
- 分支场景
"""

from __future__ import annotations

import pytest

from src.dialog.state_machine import DialogManager, DialogState


class TestRollbackMultipleSteps:
    """多步回退测试."""

    @pytest.fixture
    def manager(self) -> DialogManager:
        """返回回退管理器."""
        return DialogManager()

    def test_rollback_three_steps(self, manager: DialogManager) -> None:
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

    def test_rollback_preserves_data(self, manager: DialogManager) -> None:
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

    def test_rollback_empty_stack(self, manager: DialogManager) -> None:
        """测试空回退栈."""
        manager.create_session("session-001")

        state = manager.rollback("session-001")
        assert state is None

    def test_rollback_depth_tracking(self, manager: DialogManager) -> None:
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
    def manager(self) -> DialogManager:
        """返回回退管理器."""
        return DialogManager()

    def test_rollback_to_init_clears_state(self, manager: DialogManager) -> None:
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

    def test_rollback_to_init_clears_fields(self, manager: DialogManager) -> None:
        """测试回退到 INIT 清除字段."""
        manager.create_session("session-001")
        manager.transition("session-001", DialogState.COLLECT)
        manager.collect_field("session-001", "partition", "Students")
        manager.collect_field("session-001", "gpu", 1)

        manager.rollback_to_init("session-001")

        context = manager.get_session("session-001")
        assert context is not None
        assert context.collected_fields == {}

    def test_rollback_to_init_nonexistent_session(self, manager: DialogManager) -> None:
        """测试回退不存在的会话."""
        result = manager.rollback_to_init("nonexistent")
        assert result is False


class TestRollbackAfterModification:
    """修改后回退测试."""

    @pytest.fixture
    def manager(self) -> DialogManager:
        """返回回退管理器."""
        return DialogManager()

    def test_rollback_after_field_collection(self, manager: DialogManager) -> None:
        """测试收集字段后回退."""
        manager.create_session("session-001")
        manager.transition("session-001", DialogState.COLLECT)
        manager.collect_field("session-001", "partition", "Students")

        # 回退到上一个状态
        manager.rollback("session-001")

        context = manager.get_session("session-001")
        assert context is not None
        assert context.state == DialogState.INIT

    def test_rollback_multiple_collections(self, manager: DialogManager) -> None:
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

    def test_continue_after_rollback(self, manager: DialogManager) -> None:
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
    def manager(self) -> DialogManager:
        """返回回退管理器."""
        return DialogManager()

    def test_branch_after_rollback(self, manager: DialogManager) -> None:
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

    def test_multiple_sessions_independent(self, manager: DialogManager) -> None:
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

    def test_rollback_nonexistent_session(self, manager: DialogManager) -> None:
        """测试回退不存在的会话."""
        state = manager.rollback("nonexistent")
        assert state is None

    def test_rollback_depth_after_branch(self, manager: DialogManager) -> None:
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
