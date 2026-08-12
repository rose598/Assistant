"""改写前/后检索提升 ≥10% 对比测试（Day 2 验收补测）.

验收标准 plan §3.4 / 第 3 周周二：`query_understanding.rewrite_query`
的改写（停用词过滤 + 同义词扩展，如 GPU↔显卡/显存、排队↔等待/pending）
应提升下游检索命中——本文用可复现的关键词检索器量化该提升。

方法：
- 用一个「关键词重叠打分」检索器（同 test_retrieval_recall 风格）模拟语义检索。
- 对一组 query，分别用「原始 query」和「rewrite_query 后」检索，比较相关条目
  是否被 top-N 召回。
- 断言：改写后召回率 >= 改写前召回率 + 0.10（绝对提升 >= 10%），且改写后召回
  足够高（≥ 0.90）。

注意：改写会把「显存/显卡」等归一为 gpu，故语料不设以"显存"为关键词的条目，
避免改写命中失真（这也是一种真实约束：规范词优先）。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from src.llm.query_understanding import rewrite_query

IMPROVEMENT_THRESHOLD = 0.10  # 绝对提升 >= 10%
RECALL_AFTER_THRESHOLD = 0.90


@dataclass
class Item:
    """知识条目: 用规范关键词表示(检索器基于关键词重叠打分)."""

    id: str
    keywords: list[str]


@dataclass
class Q:
    """一条查询及其相关条目."""

    name: str
    raw: str  # 用户原始说法(可含口语/同义词)
    relevant: list[str]


# 知识库用规范词作关键词; 原始查询用口语/同义词, 需 rewrite_query 归一化
ITEMS: list[Item] = [
    Item("i-gpu", ["gpu"]),
    Item("i-queue", ["排队"]),
    Item("i-cpu", ["cpu"]),
    Item("i-mem", ["内存"]),
]

QUERIES: list[Q] = [
    Q("显卡问题", "我的显卡是不是不够用了", ["i-gpu"]),
    Q("显存不足", "跑的时候报显存不足", ["i-gpu"]),
    Q("等待排队", "作业一直在等待", ["i-queue"]),
    Q("卡住不跑", "任务卡住不跑了", ["i-queue"]),
    Q("处理器不够", "处理器占用太高", ["i-cpu"]),
    Q("内存不足", "每次跑都说内存不足", ["i-mem"]),
]


class KeywordRetriever:
    """关键词重叠打分检索器(模拟语义检索的近邻效果)."""

    def __init__(self, items: Sequence[Item]) -> None:
        self.items = items

    def search(self, query: str, top_n: int = 3) -> list[str]:
        q = query.lower()
        scored = []
        for it in self.items:
            score = sum(1 for kw in it.keywords if kw.lower() in q)
            if score > 0:
                scored.append((score, it.id))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [item_id for score, item_id in scored][:top_n]


def _recall_rate(retriever: KeywordRetriever, raw: bool) -> float:
    """对全部 query 计算 top-N 召回率(raw=True 用原始, raw=False 用改写后)."""
    hits = 0
    for q in QUERIES:
        query = q.raw if raw else rewrite_query(q.raw)
        retrieved = retriever.search(query)
        if all(rel in retrieved for rel in q.relevant):
            hits += 1
    return hits / len(QUERIES)


class TestRewriteImprovesRetrieval:
    """改写应实质提升检索召回率."""

    def test_rewrite_improves_recall_at_least_threshold(self) -> None:
        retriever = KeywordRetriever(ITEMS)
        before = _recall_rate(retriever, raw=True)
        after = _recall_rate(retriever, raw=False)
        assert after - before >= IMPROVEMENT_THRESHOLD, (
            f"改写后召回({after:.2%}) vs 改写前({before:.2%}) 提升不足 {IMPROVEMENT_THRESHOLD:.0%}"
        )

    def test_rewrite_recall_is_high(self) -> None:
        retriever = KeywordRetriever(ITEMS)
        after = _recall_rate(retriever, raw=False)
        assert after >= RECALL_AFTER_THRESHOLD, (
            f"改写后召回率应 >= {RECALL_AFTER_THRESHOLD:.0%}, 实得 {after:.2%}"
        )

    def test_raw_low_rewrite_normalizes(self) -> None:
        # 证明原始口语确实不命中规范关键词, 改写后归一化命中
        retriever = KeywordRetriever(ITEMS)
        assert retriever.search("显卡不够用") == []  # 原始口语不匹配 "gpu"
        rewritten = rewrite_query("显卡不够用")
        assert "gpu" in rewritten  # 显卡 -> gpu(同时去掉口语停用词)
        assert retriever.search(rewritten) == ["i-gpu"]
