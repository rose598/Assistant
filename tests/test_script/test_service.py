"""脚本改写编排层自测（第 5 周，A 侧；双容器桥接方案核心验证）.

覆盖：全链路状态同步与分叉检测、TTL 过期同步清理、活动重置、
回退字段恢复、无状态工具、导出与删除。
"""

from __future__ import annotations

from src.dialog.state_machine import DialogManager
from src.script.service import ScriptRewriteService

SCRIPT = """#!/bin/bash
#SBATCH -J train
#SBATCH -p Students
#SBATCH -t 04:00:00
python train.py
"""

# start → identify → collect → confirm → apply → finish 的对话状态序列
_EXPECTED_SEQUENCE = ["identify", "collect", "collect", "confirm", "apply", "done"]


class _Clock:
    """可控假时钟（DialogManager 支持 now_fn 注入）."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestScriptRewriteServicePipeline:
    """全链路状态同步与分叉检测."""

    def setup_method(self) -> None:
        self.service = ScriptRewriteService()

    def _assert_consistent(self, session_id: str) -> None:
        """分叉检测：两容器状态必须一致."""
        status = self.service.status(session_id)
        assert status is not None
        assert status["consistent"] is True

    def test_start_creates_consistent_identify(self) -> None:
        """start 后双容器同处 IDENTIFY."""
        status = self.service.start("s1", SCRIPT)
        assert status["dialog_state"] == "identify"
        assert status["flow_state"] == "identify"
        self._assert_consistent("s1")

    def test_full_pipeline_state_sequence(self) -> None:
        """六步管线每步后对话状态正确且双容器无分叉."""
        sid = "s2"
        seen: list[str] = []

        def step(action: object) -> None:
            action()
            status = self.service.status(sid)
            assert status is not None
            seen.append(status["dialog_state"])
            self._assert_consistent(sid)

        self.service.start(sid, SCRIPT)
        seen.append(self.service.status(sid)["dialog_state"])
        self._assert_consistent(sid)
        step(lambda: self.service.identify(sid, {"partition": "GPU"}))
        step(lambda: self.service.collect(sid, "time", "08:00:00"))
        step(lambda: self.service.confirm(sid))
        step(lambda: self.service.apply(sid))
        step(lambda: self.service.finish(sid))

        assert seen == _EXPECTED_SEQUENCE
        status = self.service.status(sid)
        assert status["step_count"] == 5  # identify/collect/confirm/apply/finish

    def test_confirm_returns_modified_and_diff(self) -> None:
        """confirm 返回修改后脚本、差分文本与结构化摘要."""
        sid = "s3"
        self.service.start(sid, SCRIPT)
        self.service.identify(sid, {"partition": "GPU"})
        result = self.service.confirm(sid)
        assert result is not None
        assert "#SBATCH -p GPU" in result["modified_script"]
        assert "-#SBATCH -p Students" in result["diff_text"]
        assert result["diff_summary"]["replaced"] == [
            ["#SBATCH -p Students", "#SBATCH -p GPU"]
        ]

    def test_unknown_session_returns_none(self) -> None:
        """未知会话：所有流程方法返回 None."""
        ghost = "ghost"
        assert self.service.status(ghost) is None
        assert self.service.identify(ghost, {}) is None
        assert self.service.collect(ghost, "time", "1") is None
        assert self.service.confirm(ghost) is None
        assert self.service.apply(ghost) is None
        assert self.service.finish(ghost) is None
        assert self.service.rollback(ghost) is None

    def test_delete_cleans_both_containers(self) -> None:
        """显式删除：双容器同步清理."""
        sid = "s4"
        self.service.start(sid, SCRIPT)
        self.service.delete(sid)
        assert self.service.status(sid) is None
        assert sid not in self.service._flow.contexts  # noqa: SLF001
        assert sid not in self.service._manager.sessions  # noqa: SLF001


class TestScriptRewriteServiceTTL:
    """生命周期：TTL 裁决 + flow 数据同步清理."""

    def _build(self) -> tuple[ScriptRewriteService, _Clock]:
        clock = _Clock()
        manager = DialogManager(ttl=10, now_fn=clock)
        return ScriptRewriteService(manager=manager), clock

    def test_expired_session_sync_cleanup(self) -> None:
        """过期后下一步操作返回 None，且 flow 数据被同步丢弃."""
        service, clock = self._build()
        service.start("s1", SCRIPT)
        clock.advance(11)
        assert service.identify("s1", {"partition": "GPU"}) is None
        assert "s1" not in service._flow.contexts  # noqa: SLF001

    def test_activity_resets_ttl(self) -> None:
        """活动刷新计时器：中途操作后续命."""
        service, clock = self._build()
        service.start("s1", SCRIPT)
        clock.advance(5)
        assert service.identify("s1", {"partition": "GPU"}) is not None
        clock.advance(7)  # 距上次活动 7 < 10，仍然存活
        assert service.collect("s1", "time", "08:00:00") is not None


class TestScriptRewriteServiceRollback:
    """回退：状态机快照栈 + 数据层字段恢复."""

    def setup_method(self) -> None:
        self.service = ScriptRewriteService()
        self.sid = "r1"
        self.service.start(self.sid, SCRIPT)
        self.service.identify(self.sid, {"partition": "GPU"})
        self.service.collect(self.sid, "time", "08:00:00")
        self.service.confirm(self.sid)

    def test_rollback_restores_state_and_fields(self) -> None:
        """回退一步：回到 COLLECT，字段保留、修改稿清空、双容器一致."""
        status = self.service.rollback(self.sid)
        assert status is not None
        assert status["dialog_state"] == "collect"
        assert status["flow_state"] == "collect"
        assert status["consistent"] is True
        assert status["changes"] == {"partition": "GPU", "time": "08:00:00"}
        assert status["has_modified"] is False

    def test_rollback_chain_to_init(self) -> None:
        """连续回退到 INIT：变更集清空."""
        self.service.rollback(self.sid)
        self.service.rollback(self.sid)
        status = self.service.rollback(self.sid)
        assert status is not None
        assert status["dialog_state"] == "init"
        assert status["changes"] == {}
        assert status["consistent"] is True

    def test_rollback_after_start_returns_to_init(self) -> None:
        """start 也算可回退一步：回退后回到 INIT（撤销开始改写）."""
        sid = "r2-fresh"
        self.service.start(sid, SCRIPT)
        assert self.service.status(sid)["rollback_depth"] == 1
        status = self.service.rollback(sid)
        assert status is not None
        assert status["dialog_state"] == "init"
        assert status["consistent"] is True


class TestScriptRewriteServiceTools:
    """无状态工具与导出."""

    def setup_method(self) -> None:
        self.service = ScriptRewriteService()

    def test_stateless_tools(self) -> None:
        """解析/生成/模板清单/建议直通工具层."""
        assert self.service.parse("#SBATCH -p Students") == {"p": "Students"}
        script = self.service.generate("minimal_cpu")
        assert "#SBATCH -p Students" in script
        assert "gpu_single" in self.service.list_templates()
        suggestions = self.service.suggest({"gres": "gpu:1"})
        assert suggestions["qos"] == "qos_stu_default"

    def test_export_uses_modified_and_job_name(self) -> None:
        """confirm 后导出修改稿，文件名取自 -J 作业名."""
        sid = "e1"
        self.service.start(sid, SCRIPT)
        self.service.identify(sid, {"partition": "GPU"})
        self.service.confirm(sid)
        exported = self.service.export(sid)
        assert exported is not None
        assert exported["filename"] == "train.sbatch"
        assert "#SBATCH -p GPU" in exported["content"]

    def test_export_without_confirm_uses_original(self) -> None:
        """未 confirm 时导出原稿."""
        sid = "e2"
        self.service.start(sid, SCRIPT)
        exported = self.service.export(sid)
        assert exported is not None
        assert exported["content"] == SCRIPT

    def test_diff_before_and_after_confirm(self) -> None:
        """confirm 前无差分，confirm 后有差分."""
        sid = "e3"
        self.service.start(sid, SCRIPT)
        assert self.service.diff(sid) == {"diff_text": "", "changed": False}
        self.service.identify(sid, {"partition": "GPU"})
        self.service.confirm(sid)
        result = self.service.diff(sid)
        assert result is not None
        assert result["changed"] is True
