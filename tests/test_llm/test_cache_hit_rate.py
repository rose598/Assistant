"""LLM 调用缓存命中率测试.

本模块测试 LLM 调用缓存的命中率：
- MD5(query + prompt) → response 缓存键生成
- 缓存有效期（30 分钟）
- 20 个常见问题 × 重复 2 次后命中率达到验收标准
- 不同问题不互相污染

验收标准：缓存命中率 >= 20%（计划中 B 给出的指标）。

遵循角色 D 测试惯例：由于 B 的 llm/cache.py 尚未实现（计划用 Redis），
这里使用自包含的内存版 MockCache 模拟，待 B 实现后替换。
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

CACHE_TTL_SECONDS = 1800  # 30 分钟
CACHE_HIT_TARGET = 0.20  # 目标命中率 >= 20%

# 20 个常见平台问题（模拟用户高频提问）
COMMON_QUESTIONS: list[str] = [
    "我的作业一直排队怎么办",
    "如何提交 GPU 训练作业",
    "CUDA out of memory 如何解决",
    "conda 命令找不到怎么办",
    "如何查看当前排队作业",
    "nvidia-smi 找不到 GPU",
    "QOSMaxWallDurationPerJobLimit 是什么意思",
    "如何取消一个作业",
    "用什么命令提交批处理作业",
    "分区选择哪个比较好",
    "作业没有日志文件怎么办",
    "Python 模块找不到如何处理",
    "如何看作业是否运行成功",
    "srun 交互式调试怎么用",
    "磁盘空间不足怎么办",
    "sbatch 脚本怎么编写",
    "作业报错 Driver mismatch 怎么处理",
    "如何设置运行时间限制",
    "GPU 与 CPU 分区有什么区别",
    "作业权限不足怎么办",
]


def cache_key(question: str, prompt_version: str = "v1") -> str:
    """生成缓存键（MD5(query + prompt)），模拟 B 的实现."""
    raw = f"{question}|prompt={prompt_version}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


class MockCache:
    """模拟 LLM 调用缓存（待 B 实现 llm/cache.py 后替换）.

    行为：
    - 键为 MD5(query + prompt)
    - 30 分钟内有效
    - 命中和未命中计数
    """

    def __init__(self, ttl: int = CACHE_TTL_SECONDS) -> None:
        self._store: dict[str, tuple[str, float]] = {}
        self.ttl = ttl
        self.hits = 0
        self.misses = 0

    def get(self, key: str, now: float | None = None) -> str | None:
        """按 key 取缓存；过期返回 None."""
        if now is None:
            now = time.time()
        entry = self._store.get(key)
        if entry is None:
            self.misses += 1
            return None
        value, ts = entry
        if now - ts > self.ttl:
            del self._store[key]
            self.misses += 1
            return None
        self.hits += 1
        return value

    def set(self, key: str, value: str, now: float | None = None) -> None:
        """写入缓存."""
        if now is None:
            now = time.time()
        self._store[key] = (value, now)

    @property
    def hit_rate(self) -> float:
        """当前命中率."""
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


class TestCacheKey:
    """缓存键生成测试."""

    def test_deterministic_key(self) -> None:
        """相同 query + prompt 生成相同 key."""
        assert cache_key("提交作业") == cache_key("提交作业")

    def test_different_question_different_key(self) -> None:
        """不同问题生成不同 key."""
        assert cache_key("提交作业") != cache_key("取消作业")

    def test_prompt_version_changes_key(self) -> None:
        """prompt 版本变化导致 key 变化."""
        assert cache_key("提交作业", "v1") != cache_key("提交作业", "v2")

    def test_key_is_md5_hex(self) -> None:
        """key 是 32 位 hex."""
        assert len(cache_key("x")) == 32
        assert all(c in "0123456789abcdef" for c in cache_key("x"))


class TestCacheBehavior:
    """缓存读写行为测试."""

    def test_miss_then_set_then_hit(self) -> None:
        """首次 miss，写入后再取命中."""
        store = MockCache()
        k = cache_key("提交作业")
        assert store.get(k) is None  # miss
        store.set(k, "respond")
        assert store.get(k) == "respond"  # hit

    def test_expires_after_ttl(self) -> None:
        """测试 30 分钟过期."""
        store = MockCache(ttl=1800)
        k = cache_key("提交作业")
        store.set(k, "r", now=0.0)
        assert store.get(k, now=1799.0) == "r"
        assert store.get(k, now=1801.0) is None  # 过期

    def test_same_query_returns_cached_value(self) -> None:
        """相同 query 应返回缓存的相同响应."""
        store = MockCache()
        k = cache_key("CUDA OOM 怎么办")
        store.set(k, "answer-1")
        assert store.get(k) == "answer-1"
        assert store.get(k) == "answer-1"


class TestCacheHitRate:
    """缓存命中率验收测试（20 问题 × 2 次）."""

    def test_hit_rate_after_repeat_queries(self) -> None:
        """20 个常见问题各问 2 次，命中率应达标."""
        store = MockCache()
        # 第一次全部 miss（写入缓存）
        for q in COMMON_QUESTIONS:
            k = cache_key(q)
            assert store.get(k) is None
            store.set(k, f"resp::{q}")

        # 第二次全部 hit
        for q in COMMON_QUESTIONS:
            store.get(cache_key(q))

        rate = store.hit_rate
        # 20 个 miss + 20 个 hit
        assert store.hits == 20
        assert store.misses == 20
        assert rate == 0.5
        # 满足验收标准 >= 20%
        assert rate >= CACHE_HIT_TARGET

    def test_unique_questions_have_low_hit_rate(self) -> None:
        """全部不同问题时命中率接近 0（不污染）."""
        store = MockCache()
        unique = [f"第{i}个独特问题" for i in range(20)]
        for q in unique:
            store.set(cache_key(q), "r")
        # 用不同的问题去查询，全部 miss
        for i in range(20):
            store.get(cache_key(f"另一个查询{i}"))
        assert store.hits == 0

    def test_repeat_2x_reaches_target(self) -> None:
        """用先前定义的目标命中率阈值做总体验收."""
        store = MockCache()
        rounds = 2
        for _ in range(rounds):
            for q in COMMON_QUESTIONS:
                k = cache_key(q)
                if store.get(k) is None:
                    store.set(k, "answer")
        # 第二轮起全部命中，命中率应远超 20%
        assert store.hit_rate >= CACHE_HIT_TARGET
        assert store.hit_rate > 0.3


class TestCacheReport:
    """生成缓存命中率测试报告."""

    def test_generate_report(self, tmp_path: Path) -> None:
        """生成缓存命中率报告（20 问题 × 2 次）."""
        store = MockCache()
        first_round_hits = 0
        second_round_hits = 0

        for i in range(1, 3):
            round_hits = 0
            for q in COMMON_QUESTIONS:
                k = cache_key(q)
                if store.get(k) is not None:
                    round_hits += 1
                else:
                    store.set(k, f"resp::{q}")
            if i == 1:
                first_round_hits = round_hits
            else:
                second_round_hits = round_hits

        report = {
            "summary": {
                "total_questions": len(COMMON_QUESTIONS),
                "rounds": 2,
                "first_round_hits": first_round_hits,
                "second_round_hits": second_round_hits,
                "overall_hit_rate": f"{store.hit_rate:.2%}",
                "target": f"{CACHE_HIT_TARGET:.0%}",
            },
            "questions": COMMON_QUESTIONS,
        }

        report_file = tmp_path / "cache_hit_rate_report.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        assert report_file.exists()
        assert store.hit_rate >= CACHE_HIT_TARGET
        assert second_round_hits == len(COMMON_QUESTIONS)
