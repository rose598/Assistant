"""监控模块：算力空闲检测 / 空闲时段预测 / 排队预警 / 推送。

第 4 周主动推送能力（plan §3.6）：
- ``IdleDetector`` / ``IdleReport`` / ``PartitionState``：算力空闲检测（idle_detector.py）
- ``IdlePrediction``：空闲时段预测（prediction.py）
- ``QueueMonitor`` / ``QueueReport`` / ``PartitionQueue``：排队拥堵预警（queue_monitor.py）
- ``Notifier`` / ``Notification`` / ``SendResult``：三通道推送（notifier.py）

scheduler 由后续第 4 周任务补齐。
"""

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

__all__ = [
    "CHANNELS",
    "DEFAULT_COLD_START",
    "DEFAULT_WINDOW_DAYS",
    "DataSource",
    "EmailChannel",
    "IdleDetector",
    "IdlePrediction",
    "IdleReport",
    "Notification",
    "Notifier",
    "PartitionQueue",
    "PartitionState",
    "QueueMonitor",
    "QueueReport",
    "SendResult",
    "WeComBotChannel",
    "WebSocketChannel",
    "parse_wait_seconds",
]
