"""后台墙钟调度启动幂等守卫回归测试（第 4 周缺陷修复）。

背景：Starlette/FastAPI 某些版本（实测 0.139.2 / 1.3.1）会把 router 级
``on_event("startup")`` 触发两次，导致 ``start_background_task`` 被连调两次时
若不同幂等，会在 scheduler 单例上跑起 2 个 ``run_loop``、``ticks`` 计数 2×、
任务触发周期减半。本测试验证守卫：无论调用几次，后台循环只启动一个。

为避免真实 60s run_loop 污染同进程其它测试，注入一个 run_loop 会阻塞在
``asyncio.Event`` 的桩 scheduler（保持 pending 状态），使幂等判定有意义且确定。
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest
import pytest_asyncio

from src.api import routes_flow
from src.monitor.scheduler import Scheduler


class _BlockingScheduler(Scheduler):
    """run_loop 阻塞在事件上（保持 pending），用于确定性幂等测试。"""

    def __init__(self) -> None:
        super().__init__()
        self._gate = asyncio.Event()

    async def run_loop(self, tick_seconds: float = 60.0, **_: object) -> int:
        await self._gate.wait()  # 一直 pending，除非被取消
        return 0

    def release(self) -> None:
        self._gate.set()


@pytest_asyncio.fixture
async def blocking_scheduler() -> _BlockingScheduler:
    """注入阻塞 run_loop 的 scheduler，并用后还原 get_flow_scheduler。"""
    sched = _BlockingScheduler()
    original = routes_flow.get_flow_scheduler
    routes_flow.get_flow_scheduler = lambda: sched  # type: ignore[assignment]
    try:
        yield sched
    finally:
        routes_flow.get_flow_scheduler = original


class TestBackgroundTaskGuard:
    @pytest.mark.asyncio
    async def test_start_background_task_is_idempotent(
        self, blocking_scheduler: _BlockingScheduler
    ) -> None:
        """连续调用两次 start_background_task，只应启动一个后台循环。"""
        routes_flow._flow_bg_loop = None
        try:
            routes_flow.start_background_task()
            first = routes_flow._flow_bg_loop
            assert first is not None, "首次调用应启动后台循环"

            # 第二次调用（模拟框架对 router on_event 的双触发）应被幂等守卫短路
            routes_flow.start_background_task()
            assert routes_flow._flow_bg_loop is first, "幂等守卫失败：重复启动了新循环"
        finally:
            task = routes_flow._flow_bg_loop
            routes_flow._flow_bg_loop = None
            blocking_scheduler.release()
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

    @pytest.mark.asyncio
    async def test_background_task_not_cancelled_by_guard(
        self, blocking_scheduler: _BlockingScheduler
    ) -> None:
        """守卫短路后，已启动的循环保持 pending（不被错误取消/覆盖）。"""
        routes_flow._flow_bg_loop = None
        try:
            routes_flow.start_background_task()
            routes_flow.start_background_task()
            routes_flow.start_background_task()
            assert routes_flow._flow_bg_loop is not None
            assert not routes_flow._flow_bg_loop.done(), "后台循环被错误取消"
        finally:
            task = routes_flow._flow_bg_loop
            routes_flow._flow_bg_loop = None
            blocking_scheduler.release()
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
