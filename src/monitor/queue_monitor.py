"""排队拥堵预警模块.

第 4 周 A 交付物（plan §3.6 / 进度记录 §七）：统计 ``squeue`` 排队视图，
排队作业数 > ``QUEUE_CONGEST_THRESHOLD``（默认 20）或平均等待时间 >
``QUEUE_WAIT_THRESHOLD``（默认 30 分钟）时触发预警。

设计要点：
- **复用日志层**：直接消费 ``QueueEntry``（来自 ``parse_squeue`` /
  ``LogCommandClient.list_queue``），不重写 squeue 解析。
- **分区粒度**：``QueueReport.partitions`` 给出每个分区的排队/运行明细；
  整体排队数与平均等待用于预警。
- **数据源可注入**：既可传入已解析的 ``list[QueueEntry]``（纯函数式，便于测试），
  也可注入同步/异步数据源 ``callable -> list[QueueEntry]``（接真实 squeue / mock）。
- **阈值可配**：``queue_congest_threshold`` / ``queue_wait_threshold``（见 Config）。
- **鲁棒性**：空队列 / 数据源异常不抛错；无法解析的等待时长不计入平均等待。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from src.config import get_config
from src.log_analysis.commands import QueueEntry

# 视为"排队中"的状态（squeue %.2t 输出 PD；长名 PENDING 亦兼容）
_PENDING_STATES: tuple[str, ...] = ("PD", "PENDING")
# 视为"运行中"的状态
_RUNNING_STATES: tuple[str, ...] = ("R", "RUNNING")


def parse_wait_seconds(raw: str) -> float | None:
    """解析 Slurm 时长字符串为秒数；无法解析返回 None。

    支持常见格式：``M:SS`` / ``MM:SS``、``H:MM:SS`` / ``HH:MM:SS``、
    ``D-HH:MM:SS``；``UNLIMITED`` / ``INVALID`` / 空串等返回 None。
    """
    text = (raw or "").strip()
    if not text or text.upper() in {"UNLIMITED", "INVALID", "NOT_SET"}:
        return None
    days = 0.0
    if "-" in text:
        day_part, _, text = text.partition("-")
        if not day_part.isdigit():
            return None
        days = float(day_part)
    parts = text.split(":")
    if len(parts) > 3:
        return None
    try:
        values = [float(p) for p in parts]
    except ValueError:
        return None
    if any(v < 0 for v in values):
        return None
    seconds = 0.0
    for v in values:
        seconds = seconds * 60 + v
    return days * 86400 + seconds


@dataclass
class PartitionQueue:
    """单个分区的排队统计。"""

    partition: str
    pending: int = 0
    running: int = 0
    other: int = 0  # 收尾/其它状态(CG/CD 等)
    total: int = 0
    avg_wait_minutes: float = 0.0


@dataclass
class QueueReport:
    """一次排队拥堵检测的结果。"""

    partitions: list[PartitionQueue] = field(default_factory=list)
    total_jobs: int = 0
    pending_count: int = 0
    running_count: int = 0
    avg_wait_minutes: float = 0.0
    max_wait_minutes: float = 0.0
    alert: bool = False
    reasons: list[str] = field(default_factory=list)
    pending_threshold: int = 20
    wait_threshold_minutes: float = 30.0

    def by_partition(self, name: str) -> PartitionQueue | None:
        """按分区名取明细；不存在返回 None。"""
        for p in self.partitions:
            if p.partition == name:
                return p
        return None


# 数据源类型：同步/异步返回已解析排队条目
DataSource = Callable[[], Any]


class QueueMonitor:
    """排队拥堵预警器。

    ``pending_threshold``：排队作业数超过此值触发预警（默认取 Config，20）。
    ``wait_threshold_minutes``：平均等待分钟数超过此值触发预警（默认取 Config，30）。
    ``source``：同步/异步数据源（可选），接真实 ``LogCommandClient`` 或 mock；
    不传时用 ``summarize(entries)`` 手动喂入条目。
    """

    def __init__(
        self,
        pending_threshold: int | None = None,
        wait_threshold_minutes: float | None = None,
        source: DataSource | None = None,
    ) -> None:
        cfg = get_config()
        self.pending_threshold = (
            pending_threshold if pending_threshold is not None
            else int(getattr(cfg, "queue_congest_threshold", 20) or 20)
        )
        self.wait_threshold_minutes = (
            wait_threshold_minutes if wait_threshold_minutes is not None
            else float(getattr(cfg, "queue_wait_threshold", 30.0) or 30.0)
        )
        self._source = source

    def set_source(self, source: DataSource) -> None:
        """设置数据源（同步/异步 callable）。"""
        self._source = source

    # ---- 核心统计（纯函数，便于测试） ----
    def summarize(self, entries: Sequence[QueueEntry]) -> QueueReport:
        """把 squeue 条目列表折叠成分区统计 + 整体排队数/平均等待 + 预警判定。"""
        per: dict[str, PartitionQueue] = {}
        pending_waits: list[float] = []
        running = 0

        for entry in entries:
            part = entry.partition or "(未知分区)"
            pq = per.setdefault(part, PartitionQueue(partition=part))
            pq.total += 1
            state = (entry.state or "").strip().upper()
            if state in _PENDING_STATES:
                pq.pending += 1
                secs = parse_wait_seconds(entry.time)
                if secs is not None:
                    pending_waits.append(secs)
            elif state in _RUNNING_STATES:
                pq.running += 1
                running += 1
            else:
                pq.other += 1

        pending_total = sum(p.pending for p in per.values())
        avg_minutes = (
            sum(pending_waits) / len(pending_waits) / 60.0 if pending_waits else 0.0
        )
        max_minutes = max(pending_waits) / 60.0 if pending_waits else 0.0
        for pq in per.values():
            pq.avg_wait_minutes = round(pq_avg_wait(pq, entries), 1)

        reasons: list[str] = []
        if pending_total > self.pending_threshold:
            reasons.append(f"排队拥堵：{pending_total} 个作业等待（阈值 {self.pending_threshold}）")
        if avg_minutes > self.wait_threshold_minutes:
            reasons.append(
                f"平均等待 {avg_minutes:.0f} 分钟，超过 {self.wait_threshold_minutes:.0f} 分钟阈值"
            )

        return QueueReport(
            partitions=sorted(per.values(), key=lambda p: p.partition),
            total_jobs=len(entries),
            pending_count=pending_total,
            running_count=running,
            avg_wait_minutes=round(avg_minutes, 1),
            max_wait_minutes=round(max_minutes, 1),
            alert=bool(reasons),
            reasons=reasons,
            pending_threshold=self.pending_threshold,
            wait_threshold_minutes=self.wait_threshold_minutes,
        )

    # ---- 数据源接入 ----
    async def run(self) -> QueueReport:
        """从数据源拉取排队条目并检测；数据源为空/异常时返回空报告（不抛）。"""
        if self._source is None:
            return self._empty_report()
        try:
            result = self._source()
            if hasattr(result, "__await__"):
                result = await result
        except Exception:
            return self._empty_report()
        return self.summarize(result or [])

    def _empty_report(self) -> QueueReport:
        """无数据时的空报告（阈值仍带回，便于推送侧展示口径）。"""
        return QueueReport(
            pending_threshold=self.pending_threshold,
            wait_threshold_minutes=self.wait_threshold_minutes,
        )


def pq_avg_wait(pq: PartitionQueue, entries: Sequence[QueueEntry]) -> float:
    """单个分区的平均等待分钟数（仅统计该分区可解析时长的排队条目）。"""
    waits: list[float] = []
    for entry in entries:
        part = entry.partition or "(未知分区)"
        if part != pq.partition:
            continue
        if (entry.state or "").strip().upper() not in _PENDING_STATES:
            continue
        secs = parse_wait_seconds(entry.time)
        if secs is not None:
            waits.append(secs)
    return sum(waits) / len(waits) / 60.0 if waits else 0.0


__all__ = [
    "DataSource",
    "PartitionQueue",
    "QueueMonitor",
    "QueueReport",
    "parse_wait_seconds",
]
