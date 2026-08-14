"""端到端流程集成测试（第 4 周周五，plan 周五"场景覆盖率 100%"口径）.

10 个典型场景（全部 mock 数据源 / 注入传输，不依赖真实网络/凭证/SSH）：
1-6  一键修复链路：gpu_oom / mem_oom / dependency_error / conda_missing /
     permission_denied / syntax_error → 分类 → 命令 → 三通道推送。
7    unknown 兜底：空命令 + 提示文案，推送不抛。
8    排队拥堵：scheduler 到点触发 queue_monitor → alert → 推送。
9    算力空闲：scheduler 到点触发 idle_detector → alert → 推送。
10   HTTP 端到端：TestClient POST /api/flow/diagnose-fix 全链路。

边界补充：正常队列不误报、调度注册与 60 tick 计数（对齐 D 语义）、
无凭证全降级不抛、404/422、scheduler/status 与 checks/trigger 端点。

诚实口径：ws 通道无广播器 → 断言"已调用且 delivered=False 降级"，不假装送达。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from src.api import routes_flow
from src.flow.flow_scheduler import build_monitor_scheduler
from src.flow.pipeline_flow import FlowContext, run_fix_flow, run_monitor_checks
from src.log_analysis.commands import JobRecord, parse_sinfo, parse_squeue
from src.main import app
from src.monitor.idle_detector import IdleDetector
from src.monitor.notifier import (
    EmailChannel,
    Notifier,
    WebSocketChannel,
    WeComBotChannel,
)
from src.monitor.queue_monitor import QueueMonitor

# ---- 测试基建 ----------------------------------------------------------------


def _recording_notifier() -> tuple[Notifier, dict[str, list[object]]]:
    """构造注入传输函数的 Notifier（wecom/email 可送达；ws 无广播器→降级）。"""
    calls: dict[str, list[object]] = {"wecom": [], "email": []}

    async def wecom_post(webhook: str, payload: dict[str, object]) -> None:
        calls["wecom"].append(payload)

    async def email_send(*args: object) -> None:
        calls["email"].append(args)

    notifier = Notifier(
        wecom=WeComBotChannel(webhook="https://example.invalid/hook", poster=wecom_post),
        email=EmailChannel(
            host="smtp.example.com", user="u@example.com", password="pw", sender=email_send
        ),
        ws=WebSocketChannel(),  # 不注入广播器：如实降级 delivered=False
    )
    return notifier, calls


def _failed_record(reason: str, job_id: str = "2001", exit_code: str = "1:0") -> JobRecord:
    """构造一条失败作业记录（字段齐全，供命令占位替换）。"""
    return JobRecord(
        job_id=job_id,
        job_name="train_flow",
        job_state="F",
        exit_code=exit_code,
        partition="Students",
        qos="qos_stu_default",
        command="/home/scc/stu/train.sbatch",
        workdir="/home/scc_stu/run1",
        reason=reason,
    )


# ---- 场景 1-6：一键修复链路（分类→命令→推送） ---------------------------------


class TestFixFlowScenarios:
    """6 类典型失败 → 分类正确 → 命令含关键动作 → 三通道推送（ws 如实降级）。"""

    @pytest.mark.parametrize(
        ("reason", "subtype", "keyword"),
        [
            ("CUDA out of memory. Tried to allocate 2.00 GiB", "gpu_oom", "sbatch"),
            ("OOM-killer invoked on compute node", "mem_oom", "sbatch"),
            ("ImportError: cannot import name 'foo' from 'bar'", "dependency_error", "pip install"),
            ("conda: command not found", "conda_missing", "conda activate"),
            ("Permission denied while opening dataset", "permission_denied", "chmod +x"),
            ("SyntaxError: invalid syntax in train.py", "syntax_error", "bash -n"),
        ],
    )
    async def test_fix_flow_scenario(self, reason: str, subtype: str, keyword: str) -> None:
        notifier, calls = _recording_notifier()
        ctx = FlowContext(notifier=notifier)
        result = await run_fix_flow(_failed_record(reason), ctx)

        # 分类 + 命令
        assert result.classification.subtype == subtype
        assert result.channel == "rule"
        assert result.fix.has_command
        assert keyword in result.fix.command
        assert "{job_id}" not in result.fix.command  # 占位已替换

        # 三通道推送：wecom/email 注入送达；ws 无广播器如实降级
        delivered = {n.channel: n.delivered for n in result.notifications}
        assert delivered == {"wecom_bot": True, "email": True, "ws": False}
        ws_result = next(n for n in result.notifications if n.channel == "ws")
        assert ws_result.reason  # 降级原因如实给出
        assert len(calls["wecom"]) == 1
        assert len(calls["email"]) == 1


# ---- 场景 7：unknown 兜底 ----------------------------------------------------


class TestFixFlowUnknown:
    async def test_unknown_fallback_no_throw(self) -> None:
        notifier, _ = _recording_notifier()
        ctx = FlowContext(notifier=notifier)
        rec = _failed_record("mysterious transient glitch", exit_code="42:0")
        result = await run_fix_flow(rec, ctx)

        assert result.classification.category == "unknown"
        assert result.channel == "fallback"
        assert result.fix.command == ""
        assert result.fix.commands == []
        assert result.fix.note  # 兜底提示文案非空
        # 推送仍尝试三通道且不抛
        assert len(result.notifications) == 3


# ---- 场景 8-9：scheduler 到点触发监测 → alert → 推送 --------------------------

# 25 条排队（每条等待 40 分钟）+ 2 条运行 → 排队数 >20 且平均等待 >30min
_RAW_SQUEUE_BUSY = "\n".join(
    ["JOBID PARTITION NAME USER ST TIME NODES NODELIST(REASON)"]
    + [f"{i} Students train stu PD 40:00 1 (Resources)" for i in range(1, 26)]
    + ["901 Students run stu R 1:00:00 1 anode01", "902 Students run stu R 30:00 1 anode02"]
)

# 10 idle + 2 mix → 空闲占比 ≈ 83% > 60% 阈值
_RAW_SINFO_IDLE = (
    "PARTITION AVAIL TIMELIMIT NODES STATE NODELIST\n"
    "Students up infinite 10 idle anode[01-10]\n"
    "Students up infinite 2 mix anode[11-12]"
)


class TestSchedulerMonitorPush:
    async def test_queue_alert_via_scheduler(self) -> None:
        """场景 8：tick 到 10 → queue_monitor 触发 → 拥堵预警推送。"""
        notifier, calls = _recording_notifier()
        ctx = FlowContext(
            notifier=notifier,
            queue_monitor=QueueMonitor(source=lambda: parse_squeue(_RAW_SQUEUE_BUSY)),
        )
        sched = build_monitor_scheduler(ctx)
        for _ in range(10):
            await sched.step()

        assert sched.jobs["queue_monitor"].run_count == 1
        events = [n.event for n in notifier.sent]
        assert events.count("queue_alert") == 3  # 三通道各一次
        assert len(calls["wecom"]) == 1
        assert "排队拥堵" in notifier.sent[0].message
        # ws 已调用但降级（notifier.sent 有 ws 记录且通道无广播器）
        ws_notes = [n for n in notifier.sent if n.channel == "ws"]
        assert len(ws_notes) == 1

    async def test_idle_alert_via_scheduler(self) -> None:
        """场景 9：tick 到 15 → idle_detector 触发 → 空闲预警推送。"""
        notifier, _ = _recording_notifier()
        ctx = FlowContext(
            notifier=notifier,
            idle_detector=IdleDetector(source=lambda: parse_sinfo(_RAW_SINFO_IDLE)),
        )
        sched = build_monitor_scheduler(ctx)
        for _ in range(15):
            await sched.step()

        assert sched.jobs["idle_detector"].run_count == 1
        idle_notes = [n for n in notifier.sent if n.event == "idle_alert"]
        assert len(idle_notes) == 3
        assert "空闲占比" in idle_notes[0].message

    async def test_tick_counts_align_d_semantics(self) -> None:
        """60 tick：queue_monitor 触发 6 次、idle_detector 4 次（对齐 D 语义）。"""
        ctx = FlowContext()
        sched = build_monitor_scheduler(ctx)
        for _ in range(60):
            await sched.step()
        assert sched.jobs["queue_monitor"].run_count == 6
        assert sched.jobs["idle_detector"].run_count == 4

    async def test_normal_queue_no_alert_no_push(self) -> None:
        """边界：正常队列（5 条排队）不预警、不推送。"""
        notifier, calls = _recording_notifier()
        raw = "\n".join(
            ["JOBID PARTITION NAME USER ST TIME NODES NODELIST(REASON)"]
            + [f"{i} Students train stu PD 5:00 1 (Resources)" for i in range(1, 6)]
        )
        ctx = FlowContext(
            notifier=notifier,
            queue_monitor=QueueMonitor(source=lambda: parse_squeue(raw)),
        )
        result = await run_monitor_checks(ctx)
        assert result.queue_report.alert is False
        assert result.notifications == []
        assert calls["wecom"] == []


# ---- 场景 10：HTTP 端到端（TestClient） ---------------------------------------


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    """模块级 TestClient（后台调度开关默认关，startup 无副作用）。"""
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def injected_flow_ctx() -> Iterator[None]:
    """给 /api/flow 注入确定性 FlowContext（注入 notifier），用例后还原。"""
    notifier, _ = _recording_notifier()
    original = routes_flow._flow_ctx
    routes_flow._flow_ctx = FlowContext(notifier=notifier)
    try:
        yield
    finally:
        routes_flow._flow_ctx = original


class TestHttpFlowEndpoints:
    def test_diagnose_fix_full_chain(
        self, client: TestClient, injected_flow_ctx: None
    ) -> None:
        """场景 10：mock 作业 1010（磁盘满）全链路 200，data_source 如实标 mock。"""
        r = client.post("/api/flow/diagnose-fix", params={"job_id": "1010"})
        assert r.status_code == 200
        j = r.json()
        assert j["data_source"] == "mock"  # 如实标注，不当真实呈现
        assert j["diagnosis"]["subtype"] == "disk_full"
        assert j["diagnosis"]["channel"] == "rule"
        assert j["fix"]["has_command"]
        assert "du -sh" in j["fix"]["command"]
        # 三通道推送结果如实返回：wecom/email 注入送达，ws 降级
        by_ch = {n["channel"]: n for n in j["notifications"]}
        assert set(by_ch) == {"wecom_bot", "email", "ws"}
        assert by_ch["wecom_bot"]["delivered"] is True
        assert by_ch["email"]["delivered"] is True
        assert by_ch["ws"]["delivered"] is False
        assert by_ch["ws"]["reason"]

    def test_diagnose_fix_not_found(self, client: TestClient) -> None:
        r = client.post("/api/flow/diagnose-fix", params={"job_id": "9999"})
        assert r.status_code == 404

    def test_diagnose_fix_invalid_id(self, client: TestClient) -> None:
        r = client.post("/api/flow/diagnose-fix", params={"job_id": "abc"})
        assert r.status_code == 422

    def test_checks_trigger_without_source(self, client: TestClient) -> None:
        """checks/trigger：数据源未接入 → 如实标 mock，空报告不误报。"""
        r = client.post("/api/flow/checks/trigger")
        assert r.status_code == 200
        j = r.json()
        assert j["data_source"] == "mock"
        assert j["queue"]["alert"] is False
        assert j["idle"]["alert"] is False
        assert j["notifications"] == []

    def test_scheduler_status(self, client: TestClient) -> None:
        """scheduler/status：开关默认关、未运行、两项任务已注册（10/15 分钟）。"""
        r = client.get("/api/flow/scheduler/status")
        assert r.status_code == 200
        j = r.json()
        assert j["enabled"] is False
        assert j["running"] is False
        jobs = {job["name"]: job for job in j["jobs"]}
        assert jobs["queue_monitor"]["interval_minutes"] == 10
        assert jobs["idle_detector"]["interval_minutes"] == 15


# ---- 边界：零凭证默认链路（不抛、全降级） --------------------------------------


class TestNoCredentialDegradation:
    async def test_default_context_no_credentials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """默认 FlowContext（无任何注入/凭证）：链路跑通、三通道全降级不抛。"""
        monkeypatch.delenv("WECHAT_BOT_WEBHOOK", raising=False)
        monkeypatch.delenv("SMTP_HOST", raising=False)
        monkeypatch.delenv("SMTP_USER", raising=False)
        monkeypatch.delenv("SMTP_PASSWORD", raising=False)
        result = await run_fix_flow(_failed_record("Permission denied"))
        assert len(result.notifications) == 3
        assert all(not n.delivered for n in result.notifications)
        assert all(n.reason for n in result.notifications)
