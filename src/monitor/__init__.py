"""监控模块：算力空闲检测 / 空闲时段预测 / 排队预警 / 推送。

第 4 周主动推送能力（plan §3.6）：
- ``IdleDetector`` / ``IdleReport`` / ``PartitionState``：算力空闲检测（idle_detector.py）
- ``IdlePrediction``：空闲时段预测（prediction.py）
- ``QueueMonitor`` / ``QueueReport`` / ``PartitionQueue``：排队拥堵预警（queue_monitor.py）
- ``Notifier`` / ``Notification`` / ``SendResult``：三通道推送（notifier.py）
- ``Scheduler`` / ``cron_to_minutes``：定时调度器（scheduler.py，零依赖自实现）
- ``AutoFixCmd`` / ``AutoFixResult``：一键修复命令（auto_fix_cmd.py）
"""

from src.monitor.auto_fix_cmd import (
    AutoFixCmd,
    AutoFixResult,
)
from src.monitor.idle_detector import (
    DataSource,
    IdleDetector,
    IdleReport,
    PartitionState,
)
from src.monitor.notifier import (
    CHANNELS,
    EmailChannel,
    Notification,
    Notifier,
    SendResult,
    WebSocketChannel,
    WeComBotChannel,
)
from src.monitor.prediction import (
    DEFAULT_COLD_START,
    DEFAULT_WINDOW_DAYS,
    IdlePrediction,
)
from src.monitor.queue_monitor import (
    PartitionQueue,
    QueueMonitor,
    QueueReport,
    parse_wait_seconds,
)
from src.monitor.scheduler import (
    JobSpec,
    Scheduler,
    cron_to_minutes,
)

__all__ = [
    "AutoFixCmd",
    "AutoFixResult",
    "CHANNELS",
    "DEFAULT_COLD_START",
    "DEFAULT_WINDOW_DAYS",
    "DataSource",
    "EmailChannel",
    "IdleDetector",
    "IdlePrediction",
    "IdleReport",
    "JobSpec",
    "Notification",
    "Notifier",
    "PartitionQueue",
    "PartitionState",
    "QueueMonitor",
    "QueueReport",
    "Scheduler",
    "SendResult",
    "WeComBotChannel",
    "WebSocketChannel",
    "cron_to_minutes",
    "parse_wait_seconds",
]
