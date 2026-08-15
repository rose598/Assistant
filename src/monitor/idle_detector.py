"""算力空闲检测模块.

第 4 周周二 A 交付物（plan §3.6 / 进度记录 §七）：轮询 ``sinfo`` 输出，
统计各分区 idle/mix/comp/down/drng 节点数，计算空闲 GPU 节点占比，
超过阈值触发预警。

设计要点：
- **复用日志层**：直接消费 ``NodeState``（来自 ``parse_sinfo`` / ``LogCommandClient.list_nodes``），
  不重写 sinfo 解析。
- **分区粒度**：``IdleReport.partitions`` 给出每个分区的状态明细；整体空闲率用于预警。
- **数据源可注入**：既可传入已解析的 ``list[NodeState]``（纯函数式，便于测试），
  也可注入异步数据源 ``callable -> list[NodeState]``（接真实 sinfo / mock）。
- **阈值可配**：``idle_gpu_ratio_threshold``（默认 0.6，见 Config）。
- **鲁棒性**：空节点 / 未知状态不抛错；未知状态并入"busy"统计。

典型用法（异步接数据源）::

    from src.monitor.idle_detector import IdleDetector
    d = IdleDetector()
    report = await d.run()
    print(report.idle_ratio, report.alert, [p.partition for p in report.partitions])
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from src.config import get_config
from src.log_analysis.commands import NodeState

# 需要统计的状态类别；其余未知状态并入 "busy"（非空闲）
_TRACKED_STATES: tuple[str, ...] = ("idle", "mix", "comp", "down", "drng")
# "空闲"指哪些状态（其余视为占用）
_IDLE_STATES: tuple[str, ...] = ("idle",)


@dataclass
class PartitionState:
    """单个分区的空闲统计。"""

    partition: str
    idle: int = 0
    mix: int = 0
    comp: int = 0
    down: int = 0
    drng: int = 0
    busy: int = 0  # 其它占用态(alloc/reserved 等)
    total: int = 0

    @property
    def idle_ratio(self) -> float:
        """该分区空闲率（0-1；无节点返回 0）。"""
        return self.idle / self.total if self.total else 0.0


@dataclass
class IdleReport:
    """一次空闲检测的结果。"""

    partitions: list[PartitionState] = field(default_factory=list)
    total_nodes: int = 0
    idle_nodes: int = 0
    idle_ratio: float = 0.0
    alert: bool = False
    threshold: float = 0.6

    def by_partition(self, name: str) -> PartitionState | None:
        """按分区名取明细；不存在返回 None。"""
        for p in self.partitions:
            if p.partition == name:
                return p
        return None


# 数据源类型：异步返回已解析节点状态，或返回原始 sinfo 文本
DataSource = Callable[[], Any]


class IdleDetector:
    """算力空闲检测器。

    ``threshold``：空闲率超过此值触发 ``alert``（默认取 Config）。
    ``source``：异步数据源（可选），接真实 ``LogCommandClient`` 或 mock；
    不传时用 ``check(nodes)`` 手动喂入节点。
    """

    def __init__(
        self,
        threshold: float | None = None,
        source: DataSource | None = None,
    ) -> None:
        cfg = get_config()
        self.threshold = (
            threshold if threshold is not None
            else float(getattr(cfg, "idle_gpu_ratio_threshold", 0.6) or 0.6)
        )
        self._source = source

    def set_source(self, source: DataSource) -> None:
        """设置异步数据源。"""
        self._source = source

    # ---- 核心统计（纯函数，便于测试） ----
    def summarize(self, nodes: Sequence[NodeState]) -> IdleReport:
        """把节点状态列表折叠成分区统计 + 整体空闲率。"""
        per: dict[str, PartitionState] = {}
        total = 0
        idle = 0
        for node in nodes:
            part = node.partition or "(未知分区)"
            ps = per.setdefault(part, PartitionState(partition=part))
            state = (node.state or "").strip().lower()
            count = max(node.nodes, 1)  # nodes 至少 1（一行即至少一个节点）
            ps.total += count
            total += count
            if state in _IDLE_STATES:
                ps.idle += count
                idle += count
            elif state == "mix":
                ps.mix += count
            elif state == "comp":
                ps.comp += count
            elif state == "down":
                ps.down += count
            elif state == "drng":
                ps.drng += count
            else:
                ps.busy += count

        ratio = idle / total if total else 0.0
        return IdleReport(
            partitions=sorted(per.values(), key=lambda p: p.partition),
            total_nodes=total,
            idle_nodes=idle,
            idle_ratio=round(ratio, 3),
            alert=ratio > self.threshold,
            threshold=self.threshold,
        )

    # ---- 数据源接入 ----
    async def run(self) -> IdleReport:
        """从数据源拉取节点状态并检测；数据源为空/异常时返回空报告（不抛）。"""
        if self._source is None:
            return IdleReport(threshold=self.threshold)
        try:
            result = self._source()
            if hasattr(result, "__await__"):
                # DataSource 返回 Any；运行时可能是协程，需 await
                result = await result
        except Exception:
            return IdleReport(threshold=self.threshold)
        return self.summarize(result or [])


__all__ = [
    "DataSource",
    "IdleDetector",
    "IdleReport",
    "PartitionState",
]
