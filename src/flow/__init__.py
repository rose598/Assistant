"""端到端流程编排层（第 4 周周五集成）.

- ``pipeline_flow``：作业失败→诊断分类→一键修复命令→推送 全链路编排
  （``run_fix_flow`` / ``run_monitor_checks``，依赖经 ``FlowContext`` 注入）。
- ``flow_scheduler``：queue_monitor / idle_detector 与零依赖 Scheduler 的接线
  （``build_monitor_scheduler``，回调到点检测→alert→三通道推送）。

依赖方向：``src.flow`` → ``src.monitor`` / ``src.log_analysis``（单向，不回指）。
"""

from src.flow.flow_scheduler import (
    JOB_IDLE,
    JOB_QUEUE,
    build_monitor_scheduler,
)
from src.flow.pipeline_flow import (
    EVENT_IDLE_ALERT,
    EVENT_JOB_FIX,
    EVENT_QUEUE_ALERT,
    FixFlowResult,
    FlowContext,
    MonitorCheckResult,
    channel_of,
    idle_alert_message,
    queue_alert_message,
    run_fix_flow,
    run_monitor_checks,
)

__all__ = [
    "EVENT_IDLE_ALERT",
    "EVENT_JOB_FIX",
    "EVENT_QUEUE_ALERT",
    "JOB_IDLE",
    "JOB_QUEUE",
    "FixFlowResult",
    "FlowContext",
    "MonitorCheckResult",
    "build_monitor_scheduler",
    "channel_of",
    "idle_alert_message",
    "queue_alert_message",
    "run_fix_flow",
    "run_monitor_checks",
]
