"""/api/ask 压力测试脚本 (第 2 周周五计划任务).

对本地 FastAPI 应用的 /api/ask 端点做并发压测, 输出 P50/P95/P99 延迟与吞吐.
用法:
    python scripts/benchmark.py [--url BASE] [--concurrency N] [--total N]

默认针对本地 uvicorn (http://127.0.0.1:8000), 需要先启动服务:
    uvicorn src.main:app
"""

from __future__ import annotations

import argparse
import asyncio
import time
from collections.abc import Coroutine
from typing import Any

import httpx

QUERIES: list[str] = [
    "CUDA out of memory",
    "作业一直排队怎么办",
    "如何提交 GPU 作业",
    "QOSMaxWallDurationPerJobLimit",
    "conda 找不到模块",
    "作业失败了",
    "如何申请更大算力",
    "nvidia-smi 看不到 GPU",
]


def parse_args() -> argparse.Namespace:
    """解析命令行参数."""
    parser = argparse.ArgumentParser(description="107-Agent /api/ask 压测")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="服务地址")
    parser.add_argument("--concurrency", type=int, default=20, help="并发数")
    parser.add_argument("--total", type=int, default=100, help="总请求数")
    return parser.parse_args()


async def _one_call(
    client: httpx.AsyncClient, url: str, latencies: list[float]
) -> None:
    """单个请求, 记录延迟."""
    question = QUERIES[0]  # 固定负载, 便于对比
    start = time.perf_counter()
    r = await client.post(f"{url}/api/ask", json={"question": question})
    elapsed = (time.perf_counter() - start) * 1000
    latencies.append(elapsed)
    if r.status_code != 200:
        latencies.append(elapsed + 10_000)  # 失败请求拉高延迟标记


async def _run(url: str, concurrency: int, total: int) -> list[float]:
    """并发执行 total 个请求, 返回延迟列表(ms)."""
    latencies: list[float] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks: list[Coroutine[Any, Any, None]] = []
        for _ in range(total):
            tasks.append(_one_call(client, url, latencies))
            if len(tasks) >= concurrency:
                await asyncio.gather(*tasks)
                tasks.clear()
        if tasks:
            await asyncio.gather(*tasks)
    return latencies


def _percentile(sorted_v: list[float], p: float) -> float:
    """计算排序列表的百分位."""
    if not sorted_v:
        return 0.0
    idx = min(len(sorted_v) - 1, int(p / 100 * len(sorted_v)))
    return sorted_v[idx]


def main() -> None:
    """压测入口并打印报告."""
    args = parse_args()
    print(f"压测: {args.url} | 并发 {args.concurrency} | 总请求 {args.total}")
    wall_start = time.perf_counter()
    latencies = asyncio.run(_run(args.url, args.concurrency, args.total))
    wall_s = time.perf_counter() - wall_start
    latencies.sort()
    n = len(latencies)
    p50 = _percentile(latencies, 50)
    p95 = _percentile(latencies, 95)
    p99 = _percentile(latencies, 99)
    rps = n / wall_s if wall_s > 0 else 0
    print(f"请求数  : {n}")
    print(f"P50     : {p50:.1f} ms")
    print(f"P95     : {p95:.1f} ms")
    print(f"P99     : {p99:.1f} ms")
    print(f"吞吐    : {rps:.0f} req/s")


if __name__ == "__main__":
    main()
