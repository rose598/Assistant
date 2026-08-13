"""监控模块：算力空闲检测 / 空闲时段预测 / 排队预警 / 推送。

第 4 周 active 推送能力（plan §3.6）：
- ``IdleDetector`` / ``IdleReport`` / ``PartitionState``：算力空闲检测（idle_detector.py）
- ``IdlePrediction``：空闲时段预测（prediction.py）

queue_monitor / notifier / scheduler 由后续第 4 周任务补齐。
"""

from src.monitor.idle_detector import (
    DataSource,
    IdleDetector,
    IdleReport,
    PartitionState,
)
from src.monitor.prediction import (
    DEFAULT_COLD_START,
    DEFAULT_WINDOW_DAYS,
    IdlePrediction,
)

__all__ = [
    "DEFAULT_COLD_START",
    "DEFAULT_WINDOW_DAYS",
    "DataSource",
    "IdleDetector",
    "IdlePrediction",
    "IdleReport",
    "PartitionState",
]
