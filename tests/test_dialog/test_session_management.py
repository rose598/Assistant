"""对话状态管理测试.

测试对话状态管理在各种场景下的行为：
- 新建会话
- 恢复会话
- 会话超时
- 异常中断恢复
"""

from __future__ import annotations

import time

import pytest

from src.dialog.state_machine import DialogManager, DialogState


class TestDialogSessionCreate:
    """对话会话创建测试."""

    @pytest.fixture
    def dialog_manager(self) -> DialogManager:
        """返回对话管理器."""
        return DialogManager(ttl=3600)

    def test_create_new_session(self, dialog_manager: DialogManager) -> None:
        """测试创建新会话."""
        context = dialog_manager.create_session("session-001")

        assert context.session_id == "session-001"
        assert context.state == DialogState.INIT
        assert context.collected_fields == {}
        assert context.history == []

    def test_create_duplicate_session(self, dialog_manager: DialogManager) -> None:
        """测试创建重复会话会覆盖."""
        dialog_manager.create_session("session-001")
        context = dialog_manager.create_session("session-001")

        assert context.state == DialogState.INIT
        assert len(dialog_manager.sessions) == 1

    def test_create_multiple_sessions(self, dialog_manager: DialogManager) -> None:
        """测试创建多个会话."""
        dialog_manager.create_session("session-001")
        dialog_manager.create_session("session-002")
        dialog_manager.create_session("session-003")

        assert len(dialog_manager.sessions) == 3


class TestDialogSessionRecovery:
    """对话会话恢复测试."""

    @pytest.fixture
    def dialog_manager(self) -> DialogManager:
        """返回对话管理器."""
        return DialogManager(ttl=3600)

    def test_get_existing_session(self, dialog_manager: DialogManager) -> None:
        """测试获取已存在的会话."""
        dialog_manager.create_session("session-001")
        context = dialog_manager.get_session("session-001")

        assert context is not None
        assert context.session_id == "session-001"

    def test_get_nonexistent_session(self, dialog_manager: DialogManager) -> None:
        """测试获取不存在的会话返回 None."""
        context = dialog_manager.get_session("nonexistent")
        assert context is None

    def test_session_state_persistence(self, dialog_manager: DialogManager) -> None:
        """测试会话状态持久化."""
        dialog_manager.create_session("session-001")
        dialog_manager.update_state("session-001", DialogState.COLLECT)
        dialog_manager.collect_field("session-001", "partition", "Students")

        context = dialog_manager.get_session("session-001")
        assert context is not None
        assert context.state == DialogState.COLLECT
        assert context.collected_fields["partition"] == "Students"

    def test_session_history_preserved(self, dialog_manager: DialogManager) -> None:
        """测试会话历史保留."""
        context = dialog_manager.create_session("session-001")
        context.history.append({"role": "user", "content": "你好"})
        context.history.append({"role": "assistant", "content": "你好！"})

        recovered = dialog_manager.get_session("session-001")
        assert recovered is not None
        assert len(recovered.history) == 2


class TestDialogSessionTimeout:
    """对话会话超时测试."""

    @pytest.fixture
    def dialog_manager(self) -> DialogManager:
        """返回对话管理器（短 TTL）."""
        return DialogManager(ttl=1)  # 1秒过期

    def test_session_expires_after_ttl(self, dialog_manager: DialogManager) -> None:
        """测试会话在 TTL 后过期."""
        dialog_manager.create_session("session-001")
        time.sleep(1.5)  # 等待过期

        context = dialog_manager.get_session("session-001")
        assert context is None

    def test_session_active_before_ttl(self, dialog_manager: DialogManager) -> None:
        """测试会话在 TTL 前有效."""
        dialog_manager.create_session("session-001")
        time.sleep(0.5)

        context = dialog_manager.get_session("session-001")
        assert context is not None

    def test_session_activity_resets_timer(self, dialog_manager: DialogManager) -> None:
        """测试会话活动重置计时器."""
        dialog_manager.create_session("session-001")
        time.sleep(0.5)

        # 获取会话会更新活跃时间
        dialog_manager.get_session("session-001")
        time.sleep(0.5)

        context = dialog_manager.get_session("session-001")
        assert context is not None  # 还没过期

    def test_expired_session_removed(self, dialog_manager: DialogManager) -> None:
        """测试过期会话被移除."""
        dialog_manager.create_session("session-001")
        time.sleep(1.5)

        dialog_manager.get_session("session-001")
        assert "session-001" not in dialog_manager.sessions


class TestDialogSessionInterrupt:
    """对话会话异常中断测试."""

    @pytest.fixture
    def dialog_manager(self) -> DialogManager:
        """返回对话管理器."""
        return DialogManager(ttl=3600)

    def test_state_transition_on_interrupt(self, dialog_manager: DialogManager) -> None:
        """测试中断时的状态转换."""
        dialog_manager.create_session("session-001")
        dialog_manager.update_state("session-001", DialogState.IDENTIFY)
        dialog_manager.update_state("session-001", DialogState.COLLECT)

        context = dialog_manager.get_session("session-001")
        assert context is not None
        assert context.state == DialogState.COLLECT
        assert len(context.rollback_stack) == 2

    def test_partial_data_preserved(self, dialog_manager: DialogManager) -> None:
        """测试中断时部分数据保留."""
        dialog_manager.create_session("session-001")
        dialog_manager.update_state("session-001", DialogState.COLLECT)
        dialog_manager.collect_field("session-001", "partition", "Students")
        dialog_manager.collect_field("session-001", "gpu", 1)

        # 模拟中断后恢复
        context = dialog_manager.get_session("session-001")
        assert context is not None
        assert context.collected_fields["partition"] == "Students"
        assert context.collected_fields["gpu"] == 1

    def test_rollback_after_interrupt(self, dialog_manager: DialogManager) -> None:
        """测试中断后可以回退."""
        dialog_manager.create_session("session-001")
        dialog_manager.update_state("session-001", DialogState.IDENTIFY)
        dialog_manager.update_state("session-001", DialogState.COLLECT)

        state = dialog_manager.rollback("session-001")
        assert state == DialogState.IDENTIFY

    def test_delete_session(self, dialog_manager: DialogManager) -> None:
        """测试删除会话."""
        dialog_manager.create_session("session-001")
        result = dialog_manager.delete_session("session-001")

        assert result is True
        assert dialog_manager.get_session("session-001") is None

    def test_delete_nonexistent_session(self, dialog_manager: DialogManager) -> None:
        """测试删除不存在的会话."""
        result = dialog_manager.delete_session("nonexistent")
        assert result is False


class TestDialogStateTransitions:
    """对话状态转换测试."""

    @pytest.fixture
    def dialog_manager(self) -> DialogManager:
        """返回对话管理器."""
        return DialogManager(ttl=3600)

    def test_full_state_flow(self, dialog_manager: DialogManager) -> None:
        """测试完整状态流程."""
        dialog_manager.create_session("session-001")

        # INIT -> IDENTIFY
        dialog_manager.update_state("session-001", DialogState.IDENTIFY)
        context = dialog_manager.get_session("session-001")
        assert context is not None
        assert context.state == DialogState.IDENTIFY

        # IDENTIFY -> COLLECT
        dialog_manager.update_state("session-001", DialogState.COLLECT)
        dialog_manager.collect_field("session-001", "partition", "Students")

        # COLLECT -> CONFIRM
        dialog_manager.update_state("session-001", DialogState.CONFIRM)

        # CONFIRM -> APPLY
        dialog_manager.update_state("session-001", DialogState.APPLY)

        # APPLY -> DONE
        dialog_manager.update_state("session-001", DialogState.DONE)

        context = dialog_manager.get_session("session-001")
        assert context is not None
        assert context.state == DialogState.DONE

    def test_rollback_chain(self, dialog_manager: DialogManager) -> None:
        """测试回退链."""
        dialog_manager.create_session("session-001")
        dialog_manager.update_state("session-001", DialogState.IDENTIFY)
        dialog_manager.update_state("session-001", DialogState.COLLECT)
        dialog_manager.update_state("session-001", DialogState.CONFIRM)

        # 回退到 COLLECT
        state = dialog_manager.rollback("session-001")
        assert state == DialogState.COLLECT

        # 再回退到 IDENTIFY
        state = dialog_manager.rollback("session-001")
        assert state == DialogState.IDENTIFY

    def test_rollback_at_init(self, dialog_manager: DialogManager) -> None:
        """测试在初始状态无法回退."""
        dialog_manager.create_session("session-001")

        state = dialog_manager.rollback("session-001")
        assert state is None
