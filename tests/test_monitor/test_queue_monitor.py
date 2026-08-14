"""排队拥堵预警 QueueMonitor 测试.

覆盖（plan §第4周周三 + D 测试语义 MockQueueMonitor）:
- 排队数 > 20 触发预警；平均等待 > 30min 触发预警；双条件同时触发。
- 低于阈值不触发；运行中作业不计入排队数。
- 各分区排队明细与分区平均等待。
- Slurm 时长解析（M:SS / HH:MM:SS / D-HH:MM:SS / 非法值）。
- 复用 parse_squeue: 原始 squeue 文本 → 上报。
- 同步/异步数据源接入与异常降级。
"""

from __future__ import annotations

import pytest

from src.log_analysis.commands import QueueEntry, parse_squeue
from src.monitor.queue_monitor import QueueMonitor, QueueReport, parse_wait_seconds

# squeue -o "%.18i %.9P %.30j %.8u %.2t %.10M %.6D %R" 输出样例
_SQUEUE_RAW = (
    "JOBID PARTITION NAME USER ST TIME NODES NODELIST(REASON)\n"
    "36001 Students train alice PD 0:45 1 (Priority)\n"
    "36002 Students train bob PD 1:10:00 1 (Resources)\n"
    "36003 Students sim carol R 2:03 1 anode01\n"
    "36004 CPU-6530 calc dave PD 20:00 1 (QOSMaxCpuPerUserLimit)\n"
)


def _pd(job_id: str, time: str = "5:00", partition: str = "Students") -> QueueEntry:
    """构造一个排队(PD)条目."""
    return QueueEntry(job_id=job_id, partition=partition, state="PD", time=time)


def _running(job_id: str, time: str = "5:00", partition: str = "Students") -> QueueEntry:
    """构造一个运行(R)条目."""
    return QueueEntry(job_id=job_id, partition=partition, state="R", time=time)


class TestCongestAlert:
    """排队数 / 平均等待阈值预警."""

    def test_pending_over_threshold_triggers_alert(self) -> None:
        m = QueueMonitor(pending_threshold=20, wait_threshold_minutes=30)
        entries = [_pd(str(i), time="1:00") for i in range(21)]  # 21 > 20
        report = m.summarize(entries)
        assert report.pending_count == 21
        assert report.alert is True
        assert any("排队拥堵" in r for r in report.reasons)

    def test_pending_at_threshold_no_alert(self) -> None:
        m = QueueMonitor(pending_threshold=20, wait_threshold_minutes=30)
        entries = [_pd(str(i), time="1:00") for i in range(20)]  # 恰等于阈值
        report = m.summarize(entries)
        assert report.pending_count == 20
        assert report.alert is False
        assert report.reasons == []

    def test_avg_wait_over_threshold_triggers_alert(self) -> None:
        m = QueueMonitor(pending_threshold=20, wait_threshold_minutes=30)
        # 平均等待 (10+40+50)/3 ≈ 33.3 > 30
        entries = [_pd("1", "10:00"), _pd("2", "40:00"), _pd("3", "0:50:00")]
        report = m.summarize(entries)
        assert report.avg_wait_minutes == pytest.approx(33.3, abs=0.1)
        assert report.alert is True
        assert any("平均等待" in r for r in report.reasons)

    def test_both_conditions_both_reasons(self) -> None:
        m = QueueMonitor(pending_threshold=2, wait_threshold_minutes=30)
        entries = [_pd("1", "1:00:00"), _pd("2", "1:00:00"), _pd("3", "1:00:00")]
        report = m.summarize(entries)
        assert report.alert is True
        assert len(report.reasons) == 2

    def test_low_queue_no_alert(self) -> None:
        m = QueueMonitor(pending_threshold=20, wait_threshold_minutes=30)
        report = m.summarize([_pd("1", "5:00"), _running("2")])
        assert report.alert is False
        assert report.pending_count == 1
        assert report.running_count == 1

    def test_running_jobs_not_counted_pending(self) -> None:
        m = QueueMonitor(pending_threshold=1, wait_threshold_minutes=30)
        entries = [_running(str(i)) for i in range(10)]
        report = m.summarize(entries)
        assert report.pending_count == 0
        assert report.running_count == 10
        assert report.alert is False

    def test_empty_entries_no_alert(self) -> None:
        m = QueueMonitor()
        report = m.summarize([])
        assert report.total_jobs == 0
        assert report.pending_count == 0
        assert report.avg_wait_minutes == 0.0
        assert report.alert is False

    def test_thresholds_from_config_defaults(self) -> None:
        # 不显式传阈值 → 取 Config 默认 20 / 30
        m = QueueMonitor()
        assert m.pending_threshold == 20
        assert m.wait_threshold_minutes == pytest.approx(30.0)


class TestPartitionBreakdown:
    """各分区明细."""

    def test_per_partition_counts(self) -> None:
        m = QueueMonitor(pending_threshold=20, wait_threshold_minutes=30)
        entries = [
            _pd("1", "10:00", "Students"),
            _pd("2", "20:00", "Students"),
            _running("3", partition="Students"),
            _pd("4", "1:00:00", "CPU-6530"),
        ]
        report = m.summarize(entries)
        stu = report.by_partition("Students")
        cpu = report.by_partition("CPU-6530")
        assert stu is not None and cpu is not None
        assert stu.pending == 2 and stu.running == 1 and stu.total == 3
        assert stu.avg_wait_minutes == pytest.approx(15.0)
        assert cpu.pending == 1
        assert cpu.avg_wait_minutes == pytest.approx(60.0)

    def test_max_wait_overall(self) -> None:
        m = QueueMonitor(pending_threshold=20, wait_threshold_minutes=30)
        entries = [_pd("1", "5:00"), _pd("2", "1:30:00")]
        report = m.summarize(entries)
        assert report.max_wait_minutes == pytest.approx(90.0)

    def test_unknown_state_goes_other(self) -> None:
        m = QueueMonitor()
        entries = [
            QueueEntry(job_id="1", partition="P", state="CG", time="1:00"),
            QueueEntry(job_id="2", partition="P", state="PD", time="2:00"),
        ]
        report = m.summarize(entries)
        ps = report.by_partition("P")
        assert ps is not None
        assert ps.other == 1 and ps.pending == 1

    def test_unparseable_time_excluded_from_avg(self) -> None:
        m = QueueMonitor(pending_threshold=20, wait_threshold_minutes=30)
        entries = [_pd("1", "10:00"), _pd("2", "UNLIMITED"), _pd("3", "")]
        report = m.summarize(entries)
        assert report.pending_count == 3
        assert report.avg_wait_minutes == pytest.approx(10.0)  # 仅 1 条可解析


class TestParseWaitSeconds:
    """Slurm 时长字符串解析."""

    def test_mm_ss(self) -> None:
        assert parse_wait_seconds("5:30") == pytest.approx(330.0)

    def test_hh_mm_ss(self) -> None:
        assert parse_wait_seconds("1:10:00") == pytest.approx(4200.0)

    def test_day_hh_mm_ss(self) -> None:
        assert parse_wait_seconds("1-02:00:00") == pytest.approx(93600.0)

    def test_invalid_values(self) -> None:
        assert parse_wait_seconds("UNLIMITED") is None
        assert parse_wait_seconds("INVALID") is None
        assert parse_wait_seconds("") is None
        assert parse_wait_seconds("abc") is None
        assert parse_wait_seconds("1:2:3:4") is None


class TestSqueueIntegration:
    """复用 parse_squeue: 原始 squeue 文本 → QueueReport."""

    def test_from_squeue_raw(self) -> None:
        m = QueueMonitor(pending_threshold=20, wait_threshold_minutes=30)
        report = m.summarize(parse_squeue(_SQUEUE_RAW))
        assert report.total_jobs == 4
        assert report.pending_count == 3
        assert report.running_count == 1
        # 等待: 0:45 + 1:10:00 + 20:00 → (0.75+70+20)/3 ≈ 30.25 > 30 触发
        assert report.alert is True
        assert report.by_partition("Students") is not None
        assert report.by_partition("CPU-6530") is not None

    def test_squeue_empty_parses(self) -> None:
        m = QueueMonitor()
        report = m.summarize(parse_squeue(""))
        assert report.total_jobs == 0
        assert report.alert is False


class TestDataSource:
    """同步 / 异步数据源接入与降级."""

    @pytest.mark.asyncio
    async def test_async_source(self) -> None:
        m = QueueMonitor(pending_threshold=1, wait_threshold_minutes=30)

        async def source() -> list[QueueEntry]:
            return [_pd("1", "5:00"), _pd("2", "6:00")]

        m.set_source(source)
        report = await m.run()
        assert report.pending_count == 2
        assert report.alert is True

    @pytest.mark.asyncio
    async def test_sync_source(self) -> None:
        m = QueueMonitor(pending_threshold=20, wait_threshold_minutes=30)

        def source() -> list[QueueEntry]:
            return [_pd("1", "5:00")]

        m.set_source(source)
        report = await m.run()
        assert report.pending_count == 1
        assert report.alert is False

    @pytest.mark.asyncio
    async def test_source_raises_returns_empty(self) -> None:
        m = QueueMonitor()

        def source() -> list[QueueEntry]:
            raise RuntimeError("squeue down")

        m.set_source(source)
        report = await m.run()
        assert report.pending_count == 0
        assert report.alert is False
        assert isinstance(report, QueueReport)

    @pytest.mark.asyncio
    async def test_source_none_returns_empty(self) -> None:
        m = QueueMonitor()
        report = await m.run()
        assert report.pending_count == 0
        assert report.alert is False
        # 空报告仍带回默认阈值口径
        assert report.pending_threshold == 20
        assert report.wait_threshold_minutes == pytest.approx(30.0)
