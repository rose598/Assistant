"""算力空闲检测 IdleDetector 测试.

覆盖（plan §第4周周二 + D 测试语义）:
- 空闲率计算与阈值预警（> 0.6 触发）。
- 各分区 idle/mix/comp/down/drng 明细。
- 空节点 / 未知状态兜底（不抛）。
- 复用 parse_sinfo: 原始 sinfo 文本 → 上报。
- 异步数据源接入与异常降级。
"""

from __future__ import annotations

import pytest

from src.log_analysis.commands import NodeState, parse_sinfo
from src.monitor.idle_detector import IdleDetector, IdleReport

# sinfo -N -o "%P %T %D" 输出样例（header + 数据行）
_SINFO_RAW = (
    "PARTITION AVAIL NODES STATE NODELIST\n"
    "Students up 26 idle anode[01-10]\n"
    "Students up 12 mix anode[11-18]\n"
    "Students up 4 down anode[19-22]\n"
    "CPU-6530 up 40 idle cn[01-20]\n"
    "GPU-RTX5090 up 8 comp gpu01\n"
    "GPU-RTX5090 up 2 drng gpu02\n"
)


def _nodes() -> list[NodeState]:
    """直接构造节点状态列表（覆盖多状态）. """
    return [
        NodeState(partition="Students", state="idle", nodes=8),
        NodeState(partition="Students", state="mix", nodes=12),
        NodeState(partition="Students", state="down", nodes=4),
        NodeState(partition="CPU-6530", state="idle", nodes=10),
        NodeState(partition="CPU-6530", state="comp", nodes=30),
    ]


class TestIdleRatio:
    """空闲率与预警."""

    def test_high_idle_triggers_alert(self) -> None:
        d = IdleDetector(threshold=0.6)
        nodes = [NodeState("Students", state="idle", nodes=8),
                 NodeState("Students", state="mix", nodes=2)]
        report = d.summarize(nodes)
        assert report.idle_ratio == pytest.approx(0.8)
        assert report.alert is True
        assert report.total_nodes == 10
        assert report.idle_nodes == 8

    def test_low_idle_no_alert(self) -> None:
        d = IdleDetector(threshold=0.6)
        nodes = [NodeState("Students", state="mix", nodes=9),
                 NodeState("Students", state="idle", nodes=1)]
        report = d.summarize(nodes)
        assert report.idle_ratio == pytest.approx(0.1)
        assert report.alert is False

    def test_empty_nodes_no_alert(self) -> None:
        d = IdleDetector(threshold=0.6)
        report = d.summarize([])
        assert report.total_nodes == 0
        assert report.idle_ratio == 0.0
        assert report.alert is False

    def test_threshold_from_config(self) -> None:
        # 默认 0.6；此处验证阈值生效（0.6 空闲率恰不触发, 除非 threshold 更小）
        d = IdleDetector(threshold=0.5)
        nodes = [NodeState("P", state="idle", nodes=5),
                 NodeState("P", state="mix", nodes=5)]  # 0.5
        assert d.summarize(nodes).alert is False
        nodes2 = [NodeState("P", state="idle", nodes=6),
                  NodeState("P", state="mix", nodes=4)]  # 0.6 → >0.5 触发
        assert d.summarize(nodes2).alert is True


class TestPartitionBreakdown:
    """各分区明细."""

    def test_per_partition_counts(self) -> None:
        d = IdleDetector(threshold=0.6)
        report = d.summarize(_nodes())
        ps = report.by_partition("Students")
        assert ps is not None
        assert ps.idle == 8 and ps.mix == 12 and ps.down == 4
        assert ps.total == 24
        assert ps.idle_ratio == pytest.approx(8 / 24)

    def test_overall_ratio_across_partitions(self) -> None:
        d = IdleDetector(threshold=0.6)
        report = d.summarize(_nodes())
        # idle=8+10=18, total=8+12+4+10+30=64
        assert report.idle_ratio == pytest.approx(18 / 64, abs=1e-3)
        assert report.alert is False

    def test_unknown_state_goes_busy(self) -> None:
        d = IdleDetector(threshold=0.6)
        nodes = [NodeState("P", state="alloc", nodes=7),
                 NodeState("P", state="reserved", nodes=3)]
        report = d.summarize(nodes)
        ps = report.by_partition("P")
        assert ps is not None
        assert ps.busy == 10  # alloc/reserved 归 busy
        assert ps.idle == 0
        assert ps.total == 10


class TestSinfoIntegration:
    """复用 parse_sinfo: 原始 sinfo 文本 → IdleReport."""

    def test_from_sinfo_raw(self) -> None:
        d = IdleDetector(threshold=0.6)
        nodes = parse_sinfo(_SINFO_RAW)
        report = d.summarize(nodes)
        assert report.total_nodes > 0
        assert report.by_partition("Students") is not None
        assert report.by_partition("CPU-6530") is not None
        assert report.by_partition("GPU-RTX5090") is not None

    def test_sinfo_empty_parses(self) -> None:
        d = IdleDetector(threshold=0.6)
        report = d.summarize(parse_sinfo(""))
        assert report.total_nodes == 0


class TestDataSource:
    """异步 / 同步数据源接入与降级."""

    @pytest.mark.asyncio
    async def test_async_source(self) -> None:
        d = IdleDetector(threshold=0.6)

        async def source() -> list[NodeState]:
            return [NodeState("P", state="idle", nodes=5),
                    NodeState("P", state="busy_state_unknown", nodes=5)]

        d.set_source(source)
        report = await d.run()
        assert report.total_nodes == 10
        assert report.idle_ratio == pytest.approx(0.5)
        assert report.alert is False

    @pytest.mark.asyncio
    async def test_source_raises_returns_empty(self) -> None:
        d = IdleDetector(threshold=0.6)

        def source() -> list[NodeState]:
            raise RuntimeError("sinfo down")

        d.set_source(source)
        report = await d.run()
        assert report.total_nodes == 0
        assert isinstance(report, IdleReport)

    @pytest.mark.asyncio
    async def test_no_source_returns_empty(self) -> None:
        d = IdleDetector(threshold=0.6)
        report = await d.run()
        assert report.total_nodes == 0
