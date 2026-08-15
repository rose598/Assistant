"""定时调度器模块（零依赖自实现，APScheduler 后续可选替换）.

第 4 周 A 交付物（plan §3.6 / 进度记录 §七）。两层设计：

- **核心层（确定性 tick 引擎）**：语义严格对齐 D 的 ``MockScheduler``
  （tests/test_monitor/test_monitor_prediction.py TestScheduler 口径）：
  ``add_job(name, interval_minutes)`` 注册；``tick()`` 逻辑时钟前进一个最小时间步
  （视为 1 分钟），``_ticks`` 先自增再按 ``ticks % interval == 0`` 触发，
  返回本步应触发的任务名列表；``run_count`` 累计、``last_run`` 记录触发 tick 号。
- **真实层（墙钟入口）**：``step()`` = tick + 执行回调（同步/异步，单任务异常隔离，
  不拖垮调度循环）；``run_loop(tick_seconds=60)`` 墙钟驱动，默认 1 tick = 1 分钟，
  下一触发点按**绝对时刻对齐**（起点 + n×间隔），避免 sleep 漂移累积
  （plan 验收口径：调度时间误差 ≤ 5s，待真实环境集成后验收）。

cron 字符串只做**最小解析**（``add_cron_job`` 便利入口）：仅支持 Config
``SCHEDULER_*_INTERVAL`` 实际用到的 ``*/N * * * *`` 与 ``0 */H * * *`` 两类，
其余明确抛 ValueError（不静默猜）。``add_job(interval_minutes)`` 仍是主接口。
"""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

__all__ = ["JobCallback", "JobSpec", "Scheduler", "cron_to_minutes"]

# 任务回调：同步或异步无参 callable
JobCallback = Callable[[], Any]


@dataclass
class JobSpec:
    """单个定时任务的注册信息与执行统计（条目字段对齐 D MockScheduler.jobs）。"""

    name: str
    interval: int  # 触发间隔（分钟 / tick 数）
    callback: JobCallback | None = None
    run_count: int = 0
    last_run: int | None = None  # 最近一次触发的 tick 号
    last_error: str = ""  # 最近一次回调异常（隔离记录，不打断调度）


def cron_to_minutes(expr: str) -> int:
    """最小 cron 解析（够用即止，仅覆盖本项目用到的两类模式）。

    - ``*/N * * * *`` → 每 N 分钟（返回 N）
    - ``0 */H * * *`` → 每 H 小时（返回 H×60 分钟）

    其余模式（指定时刻/日期/星期等）**明确抛 ValueError**，不静默猜；
    需要完整 cron 语义时换 APScheduler（门面不变）。
    """
    parts = (expr or "").split()
    if len(parts) != 5:
        raise ValueError(f"不支持的 cron 表达式: {expr!r}")
    minute, hour, dom, mon, dow = parts
    if dom != "*" or mon != "*" or dow != "*":
        raise ValueError(f"不支持的 cron 表达式（仅支持分钟/小时级通配）: {expr!r}")
    if hour == "*" and minute.startswith("*/"):
        return _parse_positive(minute[2:], expr)
    if minute == "0" and hour.startswith("*/"):
        return _parse_positive(hour[2:], expr) * 60
    raise ValueError(f"不支持的 cron 表达式: {expr!r}")


def _parse_positive(text: str, expr: str) -> int:
    """解析正整数间隔；非法即抛。"""
    if not text.isdigit() or int(text) < 1:
        raise ValueError(f"cron 间隔值非法: {text!r}（表达式 {expr!r}）")
    return int(text)


class Scheduler:
    """轻量定时调度器（零依赖）。

    用法::

        s = Scheduler()
        s.add_job("queue_monitor", 10, callback=check_queue)   # 或 add_cron_job(name, "*/10 * * * *")
        triggered = s.tick()          # 确定性逻辑时钟（测试/模拟）
        await s.run_loop(tick_seconds=60)  # 墙钟真实调度（1 tick = 1 分钟）

    说明：``tick()`` 纯逻辑推进不执行回调（与 D MockScheduler 一致）；
    回调执行统一走 ``step()``（异常隔离）。同名任务重复注册覆盖旧任务。
    """

    def __init__(self) -> None:
        self.jobs: dict[str, JobSpec] = {}
        self._ticks = 0
        self._stop = False

    @property
    def ticks(self) -> int:
        """当前逻辑时钟（已 tick 次数）。"""
        return self._ticks

    # ---- 注册 ----
    def add_job(
        self,
        name: str,
        interval_minutes: int,
        callback: JobCallback | None = None,
    ) -> None:
        """注册任务；interval 必须为 ≥1 的整数（1 表示每 tick 触发）。"""
        if not isinstance(interval_minutes, int) or isinstance(interval_minutes, bool):
            raise ValueError(f"interval_minutes 必须为整数: {interval_minutes!r}")
        if interval_minutes < 1:
            raise ValueError(f"interval_minutes 必须 ≥ 1: {interval_minutes}")
        self.jobs[name] = JobSpec(name=name, interval=interval_minutes, callback=callback)

    def add_cron_job(
        self,
        name: str,
        cron_expr: str,
        callback: JobCallback | None = None,
    ) -> None:
        """便利入口：按 cron 串注册（仅支持 cron_to_minutes 的两类模式）。"""
        self.add_job(name, cron_to_minutes(cron_expr), callback)

    # ---- 核心 tick 引擎（确定性，语义对齐 D MockScheduler） ----
    def tick(self) -> list[str]:
        """逻辑时钟前进一个最小时间步，返回本步触发的任务名列表。

        与 D MockScheduler 一致：``_ticks`` 先自增；``ticks % interval == 0`` 触发；
        累计 ``run_count`` 并记录 ``last_run``。**不执行回调**（回调走 step）。
        """
        self._ticks += 1
        triggered: list[str] = []
        for name, job in self.jobs.items():
            if self._ticks % job.interval == 0:
                job.run_count += 1
                job.last_run = self._ticks
                triggered.append(name)
        return triggered

    # ---- 回调执行（异常隔离） ----
    async def step(self) -> list[str]:
        """tick 一步并执行触发任务的回调；单任务异常隔离（记录 last_error，不抛）。"""
        triggered = self.tick()
        for name in triggered:
            job = self.jobs[name]
            if job.callback is None:
                continue
            try:
                result = job.callback()
                if inspect.isawaitable(result):
                    await result
                job.last_error = ""
            except Exception as exc:
                job.last_error = f"{type(exc).__name__}: {exc}"
        return triggered

    # ---- 墙钟调度入口 ----
    def stop(self) -> None:
        """请求停止 run_loop（当前步执行完后退出）。"""
        self._stop = True

    async def run_loop(
        self,
        tick_seconds: float = 60.0,
        max_ticks: int | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> int:
        """墙钟调度循环：每 ``tick_seconds`` 秒驱动一个 tick（默认 1 tick = 1 分钟）。

        下一触发点按绝对时刻对齐（起点 + n×tick_seconds），避免 sleep 漂移累积。
        ``max_ticks`` 到达或 ``stop()`` 后退出，返回实际执行的 tick 数。
        """
        self._stop = False
        done = 0
        next_at = clock()
        while not self._stop:
            await self.step()
            done += 1
            if max_ticks is not None and done >= max_ticks:
                break
            next_at += tick_seconds
            delay = next_at - clock()
            if delay > 0:
                await asyncio.sleep(delay)
        return done
