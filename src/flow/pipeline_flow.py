"""端到端流程编排层（第 4 周周五集成）.

把本周各模块串成两条链路（纯编排，不含 FastAPI/网络副作用）：

- **一键修复链路** ``run_fix_flow``：作业记录（日志解析产物）→
  诊断分类（DualLogClassifier 规则优先+LLM兜底）→ 一键修复命令（AutoFixCmd）→
  三通道推送（Notifier）。
- **主动监测链路** ``run_monitor_checks``：queue_monitor / idle_detector 各检测一次，
  alert 时经 Notifier 按 ``ctx.channels`` 逐通道推送。

设计要点（与 A 侧既有模块一致）：
- 全部依赖经 ``FlowContext`` 构造注入（分类器/修复器/Notifier/监测器/通道集合），
  缺省惰性构造默认实例——无凭证/无数据源也优雅降级，任何环节不抛。
- 推送结果如实带回（含未送达原因），由调用方呈现，不假装送达。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.log_analysis.classifier import ErrorClassification
from src.log_analysis.commands import JobRecord
from src.log_analysis.llm_log_classifier import DualLogClassifier
from src.monitor.auto_fix_cmd import AutoFixCmd, AutoFixResult
from src.monitor.idle_detector import IdleDetector, IdleReport
from src.monitor.notifier import CHANNELS, Notifier, SendResult
from src.monitor.queue_monitor import QueueMonitor, QueueReport

__all__ = [
    "EVENT_IDLE_ALERT",
    "EVENT_JOB_FIX",
    "EVENT_QUEUE_ALERT",
    "FixFlowResult",
    "FlowContext",
    "MonitorCheckResult",
    "channel_of",
    "idle_alert_message",
    "queue_alert_message",
    "run_fix_flow",
    "run_monitor_checks",
]

# 推送事件名（跨链路统一）
EVENT_JOB_FIX = "job_fix"
EVENT_QUEUE_ALERT = "queue_alert"
EVENT_IDLE_ALERT = "idle_alert"


def channel_of(cls: ErrorClassification) -> str:
    """由分类结果推断来源通道: rule / llm / fallback（与 routes_jobs 口径一致）。"""
    if any(s.startswith("LLM") for s in cls.signals_hit):
        return "llm"
    if not cls.is_known or cls.category == "unknown":
        return "fallback"
    return "rule"


@dataclass
class FlowContext:
    """流程全部依赖的注入点；未注入的组件惰性创建默认实例（零配置可跑）。"""

    classifier: DualLogClassifier | None = None
    auto_fix: AutoFixCmd | None = None
    notifier: Notifier | None = None
    queue_monitor: QueueMonitor | None = None
    idle_detector: IdleDetector | None = None
    channels: tuple[str, ...] = CHANNELS

    def get_classifier(self) -> DualLogClassifier:
        if self.classifier is None:
            self.classifier = DualLogClassifier()
        return self.classifier

    def get_auto_fix(self) -> AutoFixCmd:
        if self.auto_fix is None:
            self.auto_fix = AutoFixCmd()
        return self.auto_fix

    def get_notifier(self) -> Notifier:
        if self.notifier is None:
            self.notifier = Notifier()
        return self.notifier

    def get_queue_monitor(self) -> QueueMonitor:
        if self.queue_monitor is None:
            self.queue_monitor = QueueMonitor()
        return self.queue_monitor

    def get_idle_detector(self) -> IdleDetector:
        if self.idle_detector is None:
            self.idle_detector = IdleDetector()
        return self.idle_detector


# ---- 一键修复链路 -------------------------------------------------------------


@dataclass
class FixFlowResult:
    """一次"作业失败→诊断→修复命令→推送"全链路的结果。"""

    record: JobRecord
    classification: ErrorClassification
    fix: AutoFixResult
    channel: str  # rule / llm / fallback
    notifications: list[SendResult] = field(default_factory=list)


def _fix_message(record: JobRecord, fix: AutoFixResult) -> str:
    """构造推送消息文本（有命令给命令，无命令给兜底指引）。"""
    job = record.job_id or "<作业ID>"
    if fix.has_command:
        return f"作业 {job} 诊断为【{fix.label}】，一键修复命令：{fix.command}"
    return f"作业 {job} 诊断为【{fix.label}】。{fix.note}"


async def run_fix_flow(
    record: JobRecord, ctx: FlowContext | None = None
) -> FixFlowResult:
    """执行一键修复全链路：分类 → 命令 → 逐通道推送（不抛）。"""
    ctx = ctx or FlowContext()
    cls = await ctx.get_classifier().aclassify(record)
    fix = ctx.get_auto_fix().generate(cls)
    priority = "P1" if fix.has_command else "P2"
    message = _fix_message(record, fix)
    notifier = ctx.get_notifier()
    notifications = [
        await notifier.send(EVENT_JOB_FIX, ch, message, priority)
        for ch in ctx.channels
    ]
    return FixFlowResult(
        record=record,
        classification=cls,
        fix=fix,
        channel=channel_of(cls),
        notifications=notifications,
    )


# ---- 主动监测链路 -------------------------------------------------------------


@dataclass
class MonitorCheckResult:
    """一次"监测→预警→推送"链路的结果（两项监测各自独立，互不阻塞）。"""

    queue_report: QueueReport
    idle_report: IdleReport
    notifications: list[SendResult] = field(default_factory=list)


def queue_alert_message(report: QueueReport) -> str:
    reasons = "；".join(report.reasons) if report.reasons else "排队异常"
    return f"{reasons}（排队 {report.pending_count}/运行 {report.running_count}）"


def idle_alert_message(report: IdleReport) -> str:
    return (
        f"算力空闲占比 {report.idle_ratio:.0%} 达到阈值 {report.threshold:.0%}"
        f"（{report.idle_nodes}/{report.total_nodes} 节点空闲），可错峰提交作业"
    )


async def run_monitor_checks(ctx: FlowContext | None = None) -> MonitorCheckResult:
    """跑一次排队拥堵 + 空闲检测；alert 时逐通道推送（无数据源/无凭证均降级不抛）。"""
    ctx = ctx or FlowContext()
    queue_report = await ctx.get_queue_monitor().run()
    idle_report = await ctx.get_idle_detector().run()
    notifier = ctx.get_notifier()
    notifications: list[SendResult] = []
    if queue_report.alert:
        msg = queue_alert_message(queue_report)
        notifications.extend(
            [await notifier.send(EVENT_QUEUE_ALERT, ch, msg, "P1") for ch in ctx.channels]
        )
    if idle_report.alert:
        msg = idle_alert_message(idle_report)
        notifications.extend(
            [await notifier.send(EVENT_IDLE_ALERT, ch, msg, "P2") for ch in ctx.channels]
        )
    return MonitorCheckResult(
        queue_report=queue_report,
        idle_report=idle_report,
        notifications=notifications,
    )
