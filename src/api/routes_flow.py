"""/api/flow 端到端流程集成端点（第 4 周周五集成）.

- POST /api/flow/diagnose-fix    作业失败→诊断分类→一键修复命令→推送（全链路）
- POST /api/flow/checks/trigger  手动触发排队拥堵 + 空闲检测（alert → 三通道推送）
- GET  /api/flow/scheduler/status 调度任务注册与运行状态

数据来源如实标注（对齐 routes_jobs 口径，不把 mock 当真实呈现）：
- diagnose-fix：配置了 ssh_host/ssh_user → ``"ssh"``；否则 MockExecutor 降级 → ``"mock"``。
- checks/trigger：监测数据源已接入 → ``"configured"``；未接入 → ``"mock"``
  （此时返回空报告、不误报预警）。

后台墙钟调度受 Config ``background_scheduler_enabled`` 总开关控制（默认关）：
关闭时**不注册任何 startup/shutdown 事件**（完全 no-op，不启动后台任务）；
测试一律用确定性 ``tick()/step()`` 驱动，不依赖墙钟。
"""

from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.api.routes_jobs import JobInfo
from src.config import get_config
from src.flow.flow_scheduler import build_monitor_scheduler
from src.flow.pipeline_flow import FlowContext, run_fix_flow, run_monitor_checks
from src.log_analysis.commands import LogCommandClient
from src.log_analysis.mock_executor import MockExecutor
from src.monitor.notifier import SendResult
from src.monitor.scheduler import Scheduler

router = APIRouter(prefix="/api/flow", tags=["flow"])


# ---- 响应模型 ----------------------------------------------------------------


class FlowDiagnosis(BaseModel):
    """诊断分类结果（含来源通道）。"""

    is_failed: bool
    category: str = "unknown"
    subtype: str = "unknown"
    label: str = ""
    confidence: float = 0.0
    channel: str = "rule"  # rule / llm / fallback


class FlowFix(BaseModel):
    """一键修复命令结果。"""

    has_command: bool
    command: str = ""
    commands: list[str] = []
    note: str = ""


class FlowNotify(BaseModel):
    """单通道推送结果（如实标注是否送达）。"""

    channel: str
    delivered: bool
    reason: str = ""


class FlowDiagnoseResponse(BaseModel):
    """diagnose-fix 全链路响应。"""

    job: JobInfo
    diagnosis: FlowDiagnosis
    fix: FlowFix
    notifications: list[FlowNotify] = []
    data_source: str = "mock"


class ChecksQueue(BaseModel):
    """排队拥堵检测结果摘要。"""

    alert: bool
    pending_count: int = 0
    avg_wait_minutes: float = 0.0
    reasons: list[str] = []


class ChecksIdle(BaseModel):
    """空闲检测结果摘要。"""

    alert: bool
    idle_ratio: float = 0.0
    idle_nodes: int = 0
    total_nodes: int = 0


class ChecksResponse(BaseModel):
    """checks/trigger 响应。"""

    queue: ChecksQueue
    idle: ChecksIdle
    notifications: list[FlowNotify] = []
    data_source: str = "mock"


class SchedulerJobInfo(BaseModel):
    """单个调度任务的状态。"""

    name: str
    interval_minutes: int
    run_count: int = 0
    last_run: int | None = None


class SchedulerStatus(BaseModel):
    """调度器状态（后台开关 / 运行中 / 逻辑时钟 / 任务明细）。"""

    enabled: bool
    running: bool
    ticks: int
    jobs: list[SchedulerJobInfo] = []


# ---- 共享单例（惰性） ----------------------------------------------------------

_flow_ctx: FlowContext | None = None
_flow_scheduler: Scheduler | None = None
_flow_bg_loop: asyncio.Task[int] | None = None


def get_flow_context() -> FlowContext:
    """流程上下文单例（组件缺省惰性构造；测试可整体替换）。"""
    global _flow_ctx
    if _flow_ctx is None:
        _flow_ctx = FlowContext()
    return _flow_ctx


def get_flow_scheduler() -> Scheduler:
    """监测调度器单例（注册 queue_monitor / idle_detector 两项任务）。"""
    global _flow_scheduler
    if _flow_scheduler is None:
        _flow_scheduler = build_monitor_scheduler(get_flow_context())
    return _flow_scheduler


def _build_command_client() -> LogCommandClient:
    """构建命令客户端: SSH 可用则用 SSH, 否则 mock 降级（同 routes_jobs 口径）。"""
    cfg = get_config()
    if cfg.ssh_host and cfg.ssh_user:
        from src.log_analysis.ssh_client import SSHClient

        return LogCommandClient(SSHClient(host=cfg.ssh_host, user=cfg.ssh_user))
    return LogCommandClient(MockExecutor())


def _to_notify(results: list[SendResult]) -> list[FlowNotify]:
    """把 SendResult 列表转为响应模型。"""
    return [
        FlowNotify(channel=r.channel, delivered=r.delivered, reason=r.reason)
        for r in results
    ]


# ---- 端点 --------------------------------------------------------------------


@router.post("/diagnose-fix", response_model=FlowDiagnoseResponse)
async def diagnose_and_fix(job_id: str) -> FlowDiagnoseResponse:
    """作业失败→诊断分类→一键修复命令→三通道推送（全链路）。"""
    job_id = job_id.strip()
    if not job_id:
        raise HTTPException(status_code=422, detail="job_id 不能为空")
    numeric = "".join(ch for ch in job_id if ch.isdigit())
    if not numeric:
        raise HTTPException(status_code=422, detail=f"无效的 job_id: {job_id}")

    cfg = get_config()
    data_source = "ssh" if (cfg.ssh_host and cfg.ssh_user) else "mock"

    try:
        rec = await _build_command_client().get_job(int(numeric))
    except Exception:
        raise HTTPException(status_code=502, detail="查询作业失败") from None
    if rec is None:
        raise HTTPException(status_code=404, detail=f"作业 {job_id} 不存在")

    result = await run_fix_flow(rec, get_flow_context())
    cls = result.classification
    return FlowDiagnoseResponse(
        job=JobInfo(
            job_id=rec.job_id or "",
            job_name=rec.job_name or "",
            job_state=rec.job_state or "",
            exit_code=rec.exit_code or "",
            partition=rec.partition or "",
            qos=rec.qos or "",
            node_list=rec.node_list or "",
        ),
        diagnosis=FlowDiagnosis(
            is_failed=rec.is_failed,
            category=cls.category,
            subtype=cls.subtype,
            label=cls.label,
            confidence=cls.confidence,
            channel=result.channel,
        ),
        fix=FlowFix(
            has_command=result.fix.has_command,
            command=result.fix.command,
            commands=result.fix.commands,
            note=result.fix.note,
        ),
        notifications=_to_notify(result.notifications),
        data_source=data_source,
    )


@router.post("/checks/trigger", response_model=ChecksResponse)
async def trigger_checks() -> ChecksResponse:
    """手动触发一次排队拥堵 + 空闲检测（alert 时经三通道推送）。"""
    ctx = get_flow_context()
    result = await run_monitor_checks(ctx)
    # 数据源口径：任一监测器接了真实数据源才算 configured，否则是 mock（空报告）
    q_src = getattr(ctx.get_queue_monitor(), "_source", None)
    i_src = getattr(ctx.get_idle_detector(), "_source", None)
    data_source = "configured" if (q_src or i_src) else "mock"
    qr, ir = result.queue_report, result.idle_report
    return ChecksResponse(
        queue=ChecksQueue(
            alert=qr.alert,
            pending_count=qr.pending_count,
            avg_wait_minutes=qr.avg_wait_minutes,
            reasons=qr.reasons,
        ),
        idle=ChecksIdle(
            alert=ir.alert,
            idle_ratio=ir.idle_ratio,
            idle_nodes=ir.idle_nodes,
            total_nodes=ir.total_nodes,
        ),
        notifications=_to_notify(result.notifications),
        data_source=data_source,
    )


@router.get("/scheduler/status", response_model=SchedulerStatus)
async def scheduler_status() -> SchedulerStatus:
    """调度器状态：后台开关 / 是否在跑 / 逻辑时钟 / 任务注册与触发计数。"""
    sched = get_flow_scheduler()
    return SchedulerStatus(
        enabled=bool(get_config().background_scheduler_enabled),
        running=_flow_bg_loop is not None and not _flow_bg_loop.done(),
        ticks=sched.ticks,
        jobs=[
            SchedulerJobInfo(
                name=name,
                interval_minutes=spec.interval,
                run_count=spec.run_count,
                last_run=spec.last_run,
            )
            for name, spec in sched.jobs.items()
        ],
    )


# ---- 后台墙钟调度注册（开关关闭时完全 no-op） ----------------------------------


def start_background_task() -> None:
    """启动后台墙钟调度循环（1 tick = 1 分钟），幂等：已启动则直接复用。

    说明：Starlette/FastAPI 某些版本（实测 0.139.2 / 1.3.1）会把 router 级
    ``on_event("startup")`` 触发两次（include_router 合并事件时挂两份），
    导致 scheduler 单例上跑起 2 个 ``run_loop``、``ticks`` 计数 2×、任务触发周期减半。
    本函数对 ``_flow_bg_loop`` 做幂等守卫：无论框架触发几次，后台循环只启动一个。
    """
    global _flow_bg_loop
    if _flow_bg_loop is not None and not _flow_bg_loop.done():
        return
    _flow_bg_loop = asyncio.create_task(get_flow_scheduler().run_loop(tick_seconds=60.0))


if get_config().background_scheduler_enabled:

    @router.on_event("startup")
    async def _start_background_scheduler() -> None:
        """启动后台墙钟调度循环（幂等，防框架对 router on_event 的双触发）。"""
        start_background_task()

    @router.on_event("shutdown")
    async def _stop_background_scheduler() -> None:
        """停止后台调度循环并等待退出。"""
        global _flow_bg_loop
        if _flow_bg_loop is not None:
            _flow_bg_loop.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await _flow_bg_loop
            _flow_bg_loop = None
