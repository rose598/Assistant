"""空闲时段预测模块.

第 4 周周二 A 交付物（plan §3.6 / 进度记录 §七）：基于 **7 天滑动窗口** 的历史
空闲率数据，预测未来（如 4 小时）空闲趋势。

设计要点：
- **7 天滑动窗口**：``feed`` 时按当前时间剪裁掉 7 天前的数据（内存占用有界）。
- **时间加权平均**：越近的数据对预测影响越大（1/age 权重），契合"近期趋势更重要"。
- **冷启动**：无历史数据时返回默认值 0.5（既不悲观也不激进，可配）。
- **近期点稀疏保护**：权重下限避免"太旧单点"权重爆炸。
- **整体预测 + 未来多小时序列**：``predict`` 给单点；``forecast_next`` 给未来 N 小时逐时序列。

典型用法（周期 feed 空闲率）::

    from src.monitor.prediction import IdlePrediction
    pe = IdlePrediction()
    pe.feed(ts1, 0.3); pe.feed(ts2, 0.4)
    seq = pe.forecast_next(hours=4)   # [(ts, idle_pct) x 4]
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from src.config import get_config

# 7 天窗口（秒）
DEFAULT_WINDOW_DAYS = 7

# 冷启动默认空闲率（无历史时使用）
DEFAULT_COLD_START = 0.5


@dataclass
class _Sample:
    """一条历史空闲率采样。"""

    ts: float
    idle_pct: float


class IdlePrediction:
    """空闲时段预测引擎（7 天滑动窗口 + 时间加权平均）。"""

    def __init__(
        self,
        window_days: int | None = None,
        cold_start: float | None = None,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        cfg = get_config()
        self._window_secs = (
            int(window_days or DEFAULT_WINDOW_DAYS) * 86400
            if window_days is not None
            else int(getattr(cfg, "prediction_window_secs", 0) or DEFAULT_WINDOW_DAYS * 86400)
        )
        self._cold_start = (
            float(cold_start) if cold_start is not None
            else float(getattr(cfg, "prediction_cold_start", 0) or DEFAULT_COLD_START)
        )
        # now_fn 可注入时钟便于测试；默认取真实时间
        self._now_fn = now_fn or time.time
        self._history: list[_Sample] = []

    def _now(self) -> float:
        """当前时间（可注入）。"""
        return self._now_fn()

    def feed(self, timestamp: float, idle_pct: float) -> None:
        """记录一条历史空闲率；同时剪裁最近窗口之外的数据。"""
        self._history.append(_Sample(timestamp, float(idle_pct)))
        cutoff = self._now() - self._window_secs
        self._history = [s for s in self._history if s.ts >= cutoff]

    def predict(self, target_ts: float) -> float:
        """预测指定时刻的空闲率（0-1）。无历史时返回冷启动默认。"""
        if not self._history:
            return self._cold_start
        weighted = 0.0
        weight_sum = 0.0
        for s in self._history:
            # 年龄（小时），下限 1h 防止新点权重无限爆炸
            age_hours = max((self._now() - s.ts) / 3600.0, 1.0)
            w = 1.0 / age_hours
            weighted += s.idle_pct * w
            weight_sum += w
        return weighted / weight_sum if weight_sum else self._cold_start

    def forecast_next(self, hours: int = 4, step_hours: float = 1.0) -> tuple[float, ...]:
        """预测未来 ``hours`` 小时（步长 step_hours）的空闲率序列。

        返回每个时点的预测空闲率；调用方自行叠加时间戳。
        """
        now = self._now()
        result: list[float] = []
        for i in range(max(0, hours)):
            target = now + (i + 1) * step_hours * 3600.0
            result.append(round(self.predict(target), 3))
        return tuple(result)

    @property
    def history_count(self) -> int:
        """当前窗口内的样本数。"""
        return len(self._history)


__all__ = [
    "DEFAULT_COLD_START",
    "DEFAULT_WINDOW_DAYS",
    "IdlePrediction",
]
