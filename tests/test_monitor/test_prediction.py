"""空闲时段预测 IdlePrediction 测试.

覆盖（plan §第4周周二 + D 测试语义）:
- 7 天滑动窗口（feed 自动剪裁过期样本）。
- 冷启动默认 0.5。
- 时间加权：越近数据作用越大。
- forecast_next 未来 4 小时序列。
"""

from __future__ import annotations

import pytest

from src.monitor.prediction import IdlePrediction


class TestColdStart:
    """无历史数据."""

    def test_cold_start_default(self) -> None:
        pe = IdlePrediction(now_fn=lambda: 1_000_000.0)
        assert pe.predict(1_000_000.0) == pytest.approx(0.5)
        assert pe.history_count == 0

    def test_cold_start_custom(self) -> None:
        pe = IdlePrediction(cold_start=0.3, now_fn=lambda: 1_000_000.0)
        assert pe.predict(1_000_000.0) == pytest.approx(0.3)


class TestWindowAndPrune:
    """7 天滑动窗口剪裁."""

    def test_old_data_expired(self) -> None:
        now = 1_000_000.0
        pe = IdlePrediction(now_fn=lambda: now)
        pe.feed(now - 8 * 86400, 0.95)  # 8 天前 → 剪掉
        assert pe.history_count == 0
        assert pe.predict(now) == pytest.approx(0.5)  # 回退冷启动

    def test_fresh_data_kept(self) -> None:
        now = 1_000_000.0
        pe = IdlePrediction(now_fn=lambda: now)
        pe.feed(now - 3600, 0.8)
        assert pe.history_count == 1
        assert 0.0 < pe.predict(now) <= 1.0

    def test_leak_pruned_after_feed(self) -> None:
        now = 1_000_000.0
        pe = IdlePrediction(now_fn=lambda: now)
        pe.feed(now - 3 * 86400, 0.4)
        pe.feed(now - 9 * 86400, 0.9)  # 过期, 应只保留 1 条
        assert pe.history_count == 1


class TestWeighting:
    """时间加权: 越近权重越大."""

    def test_recent_dominates(self) -> None:
        now = 1_000_000.0
        pe = IdlePrediction(now_fn=lambda: now)
        # 旧数据高空闲(0.9), 新数据低空闲(0.1) → 预测应更接近 0.1
        pe.feed(now - 6 * 3600, 0.9)   # 6h 前
        pe.feed(now - 3600, 0.1)       # 1h 前
        pred = pe.predict(now)
        assert pred < 0.5
        assert pred > 0.0

    def test_no_history_but_weighted_constant(self) -> None:
        now = 1_000_000.0
        pe = IdlePrediction(now_fn=lambda: now)
        for h in range(5):
            pe.feed(now - (5 - h) * 3600, 0.6)
        assert pe.predict(now) == pytest.approx(0.6, abs=0.05)


class TestForecast:
    """未来多小时序列."""

    def test_forecast_next_returns_hours(self) -> None:
        now = 1_000_000.0
        pe = IdlePrediction(now_fn=lambda: now)
        pe.feed(now - 7200, 0.5)
        seq = pe.forecast_next(hours=4)
        assert len(seq) == 4
        for v in seq:
            assert 0.0 <= v <= 1.0

    def test_forecast_zero_hours(self) -> None:
        pe = IdlePrediction(now_fn=lambda: 1_000_000.0)
        assert pe.forecast_next(hours=0) == ()

    def test_forecast_cold_start(self) -> None:
        pe = IdlePrediction(now_fn=lambda: 1_000_000.0)
        seq = pe.forecast_next(hours=2)
        assert seq == (pytest.approx(0.5), pytest.approx(0.5))
