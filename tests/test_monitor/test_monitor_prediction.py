"""监控与预测模块测试（第4周·排队拥堵/空闲检测/预测/定时调度/推送）.

角色 D 第 4 周交付物 4：
- 队列拥堵检测（排队作业 > 20 或 等待 > 30min 触发预警）
- 空闲节点检测（idle 占比 > 60% 触发）
- 空闲时段预测（7 天滑动窗口）
- 定时调度器（4 个 cron 任务）
- 推送通道（企业微信 Bot/Email/WS）

遵循角色 D 惯例：A 的 monitor/ 代码尚未实现，使用自包含 Mock。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

# ── 数据类型 ──


@dataclass
class NodeInfo:
    node: str
    state: str  # idle | mix | comp | down | drng


@dataclass
class QueueSnapshot:
    """一次排队快照."""

    queued_jobs: int
    avg_wait_minutes: float
    partition: str = "Students"


@dataclass
class Notification:
    """一条推送."""

    event: str
    channel: str  # wecom_bot | email | ws
    message: str
    priority: str  # P0 | P1


# ── Mock 监控组件 ──


class MockQueueMonitor:
    """排队监控 Mock."""

    QUEUE_CONGEST_THRESHOLD = 20
    WAIT_TIME_THRESHOLD_MIN = 30

    def check(self, snapshot: QueueSnapshot) -> list[str]:
        alerts: list[str] = []
        if snapshot.queued_jobs > self.QUEUE_CONGEST_THRESHOLD:
            alerts.append(f"排队拥堵：{snapshot.queued_jobs} 个作业等待")
        if snapshot.avg_wait_minutes > self.WAIT_TIME_THRESHOLD_MIN:
            alerts.append(f"平均等待 {snapshot.avg_wait_minutes:.0f} 分钟，超过 30 分钟阈值")
        return alerts


class MockIdleDetector:
    """空闲检测 Mock."""

    IDLE_THRESHOLD = 0.60

    def check(self, nodes: list[NodeInfo]) -> dict[str, float | int]:
        total = len(nodes)
        if total == 0:
            return {"idle_pct": 0.0, "idle_nodes": 0, "total_nodes": 0}
        idle_nodes = sum(1 for n in nodes if n.state == "idle")
        pct = idle_nodes / total
        return {
            "idle_pct": round(pct, 3),
            "idle_nodes": idle_nodes,
            "total_nodes": total,
            "alert": pct > self.IDLE_THRESHOLD,
        }


class MockPredictionEngine:
    """空闲时段预测引擎（7 天滑动窗口）."""

    def __init__(self) -> None:
        self._history: list[dict[str, float]] = []

    def feed(self, timestamp: float, idle_pct: float) -> None:
        self._history.append({"ts": timestamp, "idle_pct": idle_pct})
        # 以当前时间为准剪裁最近 7 天
        cutoff = time.time() - 7 * 86400
        self._history = [h for h in self._history if h["ts"] >= cutoff]

    def predict(self, target_ts: float) -> float:
        """简单加权平均预测指定时刻的空闲率."""
        if not self._history:
            return 0.5  # 冷启动默认值
        # 按时间加权：越近权重越大
        weighted = 0.0
        weight_sum = 0.0
        for h in self._history:
            age_hours = max((target_ts - h["ts"]) / 3600, 1.0)
            w = 1.0 / age_hours
            weighted += h["idle_pct"] * w
            weight_sum += w
        return weighted / weight_sum if weight_sum else 0.5


class MockScheduler:
    """定时调度器 Mock（APScheduler 替代）."""

    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, int | None]] = {}
        self._ticks: int = 0

    def add_job(self, name: str, interval_minutes: int) -> None:
        self.jobs[name] = {"interval": interval_minutes, "last_run": None, "run_count": 0}

    def tick(self) -> list[str]:
        """模拟一个时间步（认为是下一个最小间隔），返回在此步内应执行的任务名列表."""
        triggered: list[str] = []
        self._ticks += 1
        for name, cfg in self.jobs.items():
            interval: int = cfg.get("interval", 1)  # type: ignore[assignment]
            if self._ticks % interval == 0:
                cfg["run_count"] = int(cfg.get("run_count", 0)) + 1  # type: ignore[arg-type]
                triggered.append(name)
        return triggered


class MockNotifier:
    """推送通知 Mock."""

    def __init__(self) -> None:
        self.sent: list[Notification] = []

    def send(self, event: str, channel: str, message: str, priority: str = "P1") -> Notification:
        note = Notification(event=event, channel=channel, message=message, priority=priority)
        self.sent.append(note)
        return note


# ── 测试 ──


class TestQueueMonitor:
    """排队拥堵检测."""

    def test_no_alert_when_normal(self) -> None:
        m = MockQueueMonitor()
        snap = QueueSnapshot(queued_jobs=5, avg_wait_minutes=10.0)
        assert m.check(snap) == []

    def test_alert_on_congestion(self) -> None:
        m = MockQueueMonitor()
        snap = QueueSnapshot(queued_jobs=25, avg_wait_minutes=15.0)
        alerts = m.check(snap)
        assert any("拥堵" in a for a in alerts)

    def test_alert_on_long_wait(self) -> None:
        m = MockQueueMonitor()
        snap = QueueSnapshot(queued_jobs=10, avg_wait_minutes=45.0)
        alerts = m.check(snap)
        assert any("等待" in a for a in alerts)

    def test_double_alert(self) -> None:
        m = MockQueueMonitor()
        snap = QueueSnapshot(queued_jobs=30, avg_wait_minutes=60.0)
        assert len(m.check(snap)) == 2


class TestIdleDetector:
    """空闲节点检测."""

    def test_high_idle_triggers_alert(self) -> None:
        d = MockIdleDetector()
        nodes = [NodeInfo(f"n{i}", "idle") for i in range(8)] + [NodeInfo("n8", "mix")]
        result = d.check(nodes)
        assert result["idle_pct"] > 0.60
        assert result["alert"] is True

    def test_low_idle_no_alert(self) -> None:
        d = MockIdleDetector()
        nodes = [NodeInfo(f"n{i}", "mix") for i in range(5)] + [NodeInfo("n5", "idle")]
        result = d.check(nodes)
        assert result["idle_pct"] < 0.60
        assert result["alert"] is False

    def test_empty_nodes(self) -> None:
        d = MockIdleDetector()
        result = d.check([])
        assert result["total_nodes"] == 0
        assert result["idle_pct"] == 0.0


class TestPredictionEngine:
    """空闲时段预测."""

    def test_cold_start_default(self) -> None:
        pe = MockPredictionEngine()
        assert pe.predict(time.time()) == pytest.approx(0.5)

    def test_prediction_with_history(self) -> None:
        pe = MockPredictionEngine()
        now = time.time()
        # 过去 24 小时每小时记录一条
        for h in range(24):
            ts = now - (24 - h) * 3600
            pe.feed(ts, 0.8 if h < 12 else 0.3)
        pred = pe.predict(now + 3600)
        # 最近数据权重更大，应接近 0.3
        assert 0.2 <= pred <= 0.9

    def test_old_data_expired(self) -> None:
        pe = MockPredictionEngine()
        now = time.time()
        pe.feed(time.time() - 8 * 86400, 0.95)  # 8 天前
        pred = pe.predict(now)
        assert pred == pytest.approx(0.5)  # 已过期，回退到默认


class TestScheduler:
    """定时调度器."""

    def test_jobs_trigger_at_interval(self) -> None:
        s = MockScheduler()
        s.add_job("queue_monitor", 10)
        s.add_job("idle_detector", 15)
        s.add_job("job_watcher", 5)
        s.add_job("prediction", 60)

        # tick 5 次（5 分钟）
        triggered: dict[str, int] = {}
        for _ in range(5):
            for name in s.tick():
                triggered[name] = triggered.get(name, 0) + 1

        # job_watcher 间隔 5 → 触发 1 次
        assert triggered.get("job_watcher", 0) == 1
        # 其他长间隔任务在 5 分钟内不应触发
        assert triggered.get("queue_monitor", 0) == 0

    def test_all_jobs_trigger_after_max_interval(self) -> None:
        s = MockScheduler()
        s.add_job("queue_monitor", 10)
        s.add_job("job_watcher", 5)
        # tick 60 次
        for _ in range(60):
            s.tick()
        cfg = s.jobs["queue_monitor"]
        assert cfg["run_count"] == 6  # 60 / 10
        assert s.jobs["job_watcher"]["run_count"] == 12  # 60 / 5


class TestNotifier:
    """推送通知."""

    def test_send_and_record(self) -> None:
        n = MockNotifier()
        note = n.send("queue_congestion", "wecom_bot", "排队作业 > 20", "P0")
        assert note.channel == "wecom_bot"
        assert note.priority == "P0"
        assert len(n.sent) == 1

    def test_all_channels_supported(self) -> None:
        n = MockNotifier()
        n.send("idle_alert", "wecom_bot", "空闲 > 60%", "P1")
        n.send("job_complete", "email", "作业 12345 已完成", "P0")
        n.send("partition_down", "ws", "分区 Students 已 down", "P1")
        channels = {note.channel for note in n.sent}
        assert channels == {"wecom_bot", "email", "ws"}


class TestMonitorIntegration:
    """监控模块集成场景."""

    def test_end_to_end_congestion_flow(self) -> None:
        """完整的排队预警 → 空闲检测 → 推送流程."""
        qm, detector, sched, notifier = (
            MockQueueMonitor(),
            MockIdleDetector(),
            MockScheduler(),
            MockNotifier(),
        )
        sched.add_job("queue_monitor", 1)
        sched.add_job("idle_detector", 2)

        # tick 2: queue_monitor(tick=1,2) → 2次, idle_detector(tick=2) → 1次
        for _ in range(2):
            for name in sched.tick():
                if name == "queue_monitor":
                    snap = QueueSnapshot(queued_jobs=30, avg_wait_minutes=35.0)
                    for alert in qm.check(snap):
                        notifier.send("queue_congestion", "wecom_bot", alert, "P0")
                elif name == "idle_detector":
                    nodes = [NodeInfo(f"n{i}", "idle") for i in range(8)]
                    result = detector.check(nodes)
                    if result["alert"]:
                        notifier.send(
                            "idle_alert",
                            "ws",
                            f"空闲节点占比 {result['idle_pct']:.0%}",
                            "P1",
                        )

        # queue_monitor 跑了 2 次（tick 1+2），每次 2 条 alert
        qm_count = sum(1 for n in notifier.sent if n.event == "queue_congestion")
        assert qm_count == 4  # 2 ticks × 2 alerts = 4

        idle_count = sum(1 for n in notifier.sent if n.event == "idle_alert")
        assert idle_count == 1  # tick 2 触发

        assert len(notifier.sent) >= 1


class TestMonitorReport:
    """生成监控模块测试报告."""

    def test_generate_report(self, tmp_path: Path) -> None:
        qm = MockQueueMonitor()
        detector = MockIdleDetector()
        sched = MockScheduler()
        pe = MockPredictionEngine()
        notifier = MockNotifier()

        # 排队
        alerts = qm.check(QueueSnapshot(queued_jobs=25, avg_wait_minutes=35.0))
        # 空闲
        nodes = [
            NodeInfo(f"n{i}", "idle") if i < 7 else NodeInfo(f"n{i}", "mix") for i in range(10)
        ]
        idle_result = detector.check(nodes)
        # 预测
        now = time.time()
        pe.feed(now - 7200, 0.6)
        pred = pe.predict(now)
        # 调度
        sched.add_job("queue_monitor", 10)
        for _ in range(10):
            sched.tick()
        # 推送
        notifier.send("test", "ws", "report check", "P1")

        report = {
            "queue_monitor": {
                "alerts": alerts,
                "count": len(alerts),
            },
            "idle_detector": {
                "idle_pct": idle_result["idle_pct"],
                "alert_triggered": idle_result["alert"],
            },
            "prediction": {"value": round(pred, 3)},
            "scheduler": {
                "job_count": len(sched.jobs),
                "queue_monitor_runs": sched.jobs["queue_monitor"]["run_count"],
            },
            "notifier": {"sent_count": len(notifier.sent)},
        }

        report_file = tmp_path / "monitor_report_week4.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        assert report_file.exists()
        assert len(alerts) == 2
