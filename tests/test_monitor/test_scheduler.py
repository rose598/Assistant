"""定时调度器 Scheduler 测试（零依赖自实现）.

覆盖（plan §第4周周四 + 严格对齐 D 的 MockScheduler 语义）:
- 复刻 D TestScheduler 两用例（真实数值断言，不改 D 测试文件）：
  tick 5 次 job_watcher(5) 触发 1 次、queue_monitor(10) 不触发；
  tick 60 次 queue_monitor run_count==6、job_watcher==12。
- tick 边界：恰在 interval 触发 / interval=1 每 tick 触发 / run_count 与 last_run。
- 注册校验：interval 非法（0/负/非整数/bool）抛 ValueError；同名覆盖。
- cron 最小解析：*/N 与 0 */H 两类支持，其余明确抛错；add_cron_job 注册。
- step 回调：同步/异步执行、单任务异常隔离不抛、last_error 记录。
- run_loop：max_ticks 退出、stop 退出、interval=1 回调按 tick 计数。
"""

from __future__ import annotations

import asyncio

import pytest

from src.monitor.scheduler import Scheduler, cron_to_minutes


class TestTickSemantics:
    """核心 tick 引擎（复刻 D TestScheduler 两用例 + 边界）."""

    def test_jobs_trigger_at_interval(self) -> None:
        # 复刻 D: tick 5 次（5 分钟）
        s = Scheduler()
        s.add_job("queue_monitor", 10)
        s.add_job("idle_detector", 15)
        s.add_job("job_watcher", 5)
        s.add_job("prediction", 60)

        triggered: dict[str, int] = {}
        for _ in range(5):
            for name in s.tick():
                triggered[name] = triggered.get(name, 0) + 1

        # job_watcher 间隔 5 → 触发 1 次；长间隔任务不应触发
        assert triggered.get("job_watcher", 0) == 1
        assert triggered.get("queue_monitor", 0) == 0
        assert triggered.get("idle_detector", 0) == 0
        assert triggered.get("prediction", 0) == 0

    def test_all_jobs_trigger_after_max_interval(self) -> None:
        # 复刻 D: tick 60 次
        s = Scheduler()
        s.add_job("queue_monitor", 10)
        s.add_job("job_watcher", 5)
        for _ in range(60):
            s.tick()
        assert s.jobs["queue_monitor"].run_count == 6  # 60 / 10
        assert s.jobs["job_watcher"].run_count == 12  # 60 / 5

    def test_first_trigger_at_exact_interval(self) -> None:
        s = Scheduler()
        s.add_job("x", 3)
        assert s.tick() == []   # tick 1
        assert s.tick() == []   # tick 2
        assert s.tick() == ["x"]  # tick 3
        assert s.jobs["x"].last_run == 3

    def test_interval_one_triggers_every_tick(self) -> None:
        s = Scheduler()
        s.add_job("fast", 1)
        for _ in range(4):
            assert s.tick() == ["fast"]
        assert s.jobs["fast"].run_count == 4
        assert s.ticks == 4

    def test_multiple_jobs_same_tick(self) -> None:
        s = Scheduler()
        s.add_job("a", 2)
        s.add_job("b", 5)
        triggered_all: list[str] = []
        for _ in range(10):
            triggered_all.extend(s.tick())
        assert triggered_all.count("a") == 5
        assert triggered_all.count("b") == 2


class TestRegistration:
    """注册校验与覆盖."""

    @pytest.mark.parametrize("bad", [0, -5, 2.5, "10", True])
    def test_invalid_interval_raises(self, bad: object) -> None:
        s = Scheduler()
        with pytest.raises(ValueError):
            s.add_job("x", bad)  # type: ignore[arg-type]

    def test_same_name_overwrites(self) -> None:
        s = Scheduler()
        s.add_job("x", 5)
        s.add_job("x", 2)
        assert s.jobs["x"].interval == 2
        assert len(s.jobs) == 1
        assert s.jobs["x"].run_count == 0  # 重新注册清零


class TestCronParsing:
    """cron 最小解析（够用即止）."""

    def test_every_n_minutes(self) -> None:
        assert cron_to_minutes("*/10 * * * *") == 10
        assert cron_to_minutes("*/15 * * * *") == 15
        assert cron_to_minutes("*/5 * * * *") == 5

    def test_every_n_hours(self) -> None:
        assert cron_to_minutes("0 */1 * * *") == 60
        assert cron_to_minutes("0 */2 * * *") == 120

    @pytest.mark.parametrize("bad", [
        "5 4 * * *",        # 指定时刻
        "*/10 * * *",       # 字段不足
        "*/10 3 * * *",     # 指定小时 + 分钟步进
        "*/0 * * * *",      # 非法间隔
        "*/x * * * *",      # 非数字
        "0 0 1 * *",        # 日期级
        "",                 # 空
    ])
    def test_unsupported_raises(self, bad: str) -> None:
        with pytest.raises(ValueError):
            cron_to_minutes(bad)

    def test_add_cron_job_registers_interval(self) -> None:
        s = Scheduler()
        s.add_cron_job("queue_monitor", "*/10 * * * *")
        s.add_cron_job("prediction", "0 */1 * * *")
        assert s.jobs["queue_monitor"].interval == 10
        assert s.jobs["prediction"].interval == 60

    def test_add_cron_job_invalid_raises(self) -> None:
        s = Scheduler()
        with pytest.raises(ValueError):
            s.add_cron_job("x", "30 8 * * 1")


class TestStepCallbacks:
    """step: tick + 回调执行（异常隔离）."""

    @pytest.mark.asyncio
    async def test_sync_callback_runs(self) -> None:
        hits: list[str] = []
        s = Scheduler()
        s.add_job("x", 1, callback=lambda: hits.append("x"))
        await s.step()
        await s.step()
        assert hits == ["x", "x"]

    @pytest.mark.asyncio
    async def test_async_callback_awaited(self) -> None:
        hits: list[str] = []

        async def cb() -> None:
            await asyncio.sleep(0)
            hits.append("async")

        s = Scheduler()
        s.add_job("x", 1, callback=cb)
        await s.step()
        assert hits == ["async"]
        assert s.jobs["x"].last_error == ""

    @pytest.mark.asyncio
    async def test_callback_error_isolated(self) -> None:
        def boom() -> None:
            raise RuntimeError("task exploded")

        hits: list[str] = []
        s = Scheduler()
        s.add_job("bad", 1, callback=boom)
        s.add_job("good", 1, callback=lambda: hits.append("ok"))
        triggered = await s.step()  # 不抛
        assert set(triggered) == {"bad", "good"}
        assert hits == ["ok"]  # 坏任务不影响好任务
        assert "RuntimeError" in s.jobs["bad"].last_error
        assert s.jobs["good"].last_error == ""

    @pytest.mark.asyncio
    async def test_no_callback_step_safe(self) -> None:
        s = Scheduler()
        s.add_job("x", 1)
        assert await s.step() == ["x"]


class TestRunLoop:
    """墙钟调度入口（短 tick_seconds 驱动）."""

    @pytest.mark.asyncio
    async def test_max_ticks_and_callback_count(self) -> None:
        hits: list[int] = []
        s = Scheduler()
        s.add_job("x", 1, callback=lambda: hits.append(1))
        done = await s.run_loop(tick_seconds=0.01, max_ticks=3)
        assert done == 3
        assert len(hits) == 3
        assert s.jobs["x"].run_count == 3

    @pytest.mark.asyncio
    async def test_stop_exits_loop(self) -> None:
        s = Scheduler()
        s.add_job("x", 1)

        async def stopper() -> None:
            await asyncio.sleep(0.05)
            s.stop()

        task = asyncio.create_task(s.run_loop(tick_seconds=0.01))
        stop_task = asyncio.create_task(stopper())
        done = await asyncio.wait_for(task, timeout=5)
        await stop_task
        assert done >= 2  # 至少跑了若干步后按 stop 退出

    @pytest.mark.asyncio
    async def test_interval_respected_in_loop(self) -> None:
        s = Scheduler()
        s.add_job("slow", 2)
        await s.run_loop(tick_seconds=0.01, max_ticks=5)
        assert s.jobs["slow"].run_count == 2  # tick 2, 4
