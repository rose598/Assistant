"""监测任务与调度器的接线（第 4 周周五集成）.

``build_monitor_scheduler``：把 queue_monitor / idle_detector 注册进
零依赖 ``Scheduler``，间隔取自 Config 的 ``SCHEDULER_QUEUE_INTERVAL`` /
``SCHEDULER_IDLE_INTERVAL``（经 ``cron_to_minutes`` 解析，默认 10/15 分钟）。

回调语义（到点执行 → 拿 alert → 走 Notifier 推送）：
- ``queue_monitor``：``run()`` → ``alert`` 时按 ``ctx.channels`` 逐通道推送 ``queue_alert``；
- ``idle_detector``：``run()`` → ``alert`` 时推送 ``idle_alert``。

说明（依赖方向）：本模块属 ``src/flow`` 编排层，单向依赖 ``src/monitor``，
避免 monitor 包反向依赖 flow；``tick()/step()`` 语义仍对齐 D 的 MockScheduler，
测试可用确定性 tick 驱动，不依赖墙钟。
"""

from __future__ import annotations

from src.config import SCHEDULER_IDLE_INTERVAL, SCHEDULER_QUEUE_INTERVAL
from src.flow.pipeline_flow import (
    EVENT_IDLE_ALERT,
    EVENT_QUEUE_ALERT,
    FlowContext,
    idle_alert_message,
    queue_alert_message,
)
from src.monitor.scheduler import Scheduler, cron_to_minutes

__all__ = ["JOB_IDLE", "JOB_QUEUE", "build_monitor_scheduler"]

# 注册任务名（与 D 的 TestScheduler 用例口径一致）
JOB_QUEUE = "queue_monitor"
JOB_IDLE = "idle_detector"


def build_monitor_scheduler(
    ctx: FlowContext | None = None, scheduler: Scheduler | None = None
) -> Scheduler:
    """注册两项监测任务并返回 Scheduler（ctx/scheduler 均可注入，便于测试）。"""
    ctx = ctx or FlowContext()
    sched = scheduler or Scheduler()

    async def _queue_job() -> None:
        report = await ctx.get_queue_monitor().run()
        if report.alert:
            await _push_all(ctx, EVENT_QUEUE_ALERT, queue_alert_message(report), "P1")

    async def _idle_job() -> None:
        report = await ctx.get_idle_detector().run()
        if report.alert:
            await _push_all(ctx, EVENT_IDLE_ALERT, idle_alert_message(report), "P2")

    sched.add_job(JOB_QUEUE, cron_to_minutes(SCHEDULER_QUEUE_INTERVAL), callback=_queue_job)
    sched.add_job(JOB_IDLE, cron_to_minutes(SCHEDULER_IDLE_INTERVAL), callback=_idle_job)
    return sched


async def _push_all(ctx: FlowContext, event: str, message: str, priority: str) -> None:
    """按 ctx.channels 逐通道推送；单通道失败由 Notifier 内部降级，不抛。"""
    notifier = ctx.get_notifier()
    for ch in ctx.channels:
        await notifier.send(event, ch, message, priority)
