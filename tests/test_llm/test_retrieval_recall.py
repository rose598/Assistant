"""检索召回率测试.

本模块测试 RAG 知识库检索的召回率，验收标准：
- top-3 召回率 >= 90%
- top-5 召回率 >= 95%

遵循角色 D 测试惯例：由于 B 的 llm/vector_store.py / rag_engine.py 尚未实现，
这里使用自包含的 MockVectorStore 模拟向量检索，待 B 实现后替换为真实导入。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

RECALL_TOP3_THRESHOLD = 0.90
RECALL_TOP5_THRESHOLD = 0.95


@dataclass
class KnowledgeItem:
    """知识库条目."""

    id: str
    keywords: list[str]


@dataclass
class RecallQuery:
    """召回率测试查询."""

    name: str
    query: str
    relevant_ids: list[str]  # 该查询相关的知识条目 id（ground truth）


# ── 知识库（模拟，含中文条目） ──
KNOWLEDGE_BASE: list[KnowledgeItem] = [
    KnowledgeItem("faq-001", ["QOSMaxWallDurationPerJobLimit", "超时", "运行时间"]),
    KnowledgeItem("faq-002", ["QOSMaxCpuPerUserLimit", "CPU限额", "资源上限"]),
    KnowledgeItem("faq-003", ["CUDA out of memory", "显存不足", "OOM"]),
    KnowledgeItem("faq-004", ["nvidia-smi", "找不到GPU", "驱动"]),
    KnowledgeItem("faq-005", ["Driver/library", "版本不匹配", "驱动"]),
    KnowledgeItem("faq-006", ["排队", "PD", "pending", "等待"]),
    KnowledgeItem("faq-007", ["conda", "未激活", "环境"]),
    KnowledgeItem("faq-008", ["ModuleNotFoundError", "找不到模块", "包未安装"]),
    KnowledgeItem("faq-009", ["sbatch", "提交作业", "批处理"]),
    KnowledgeItem("faq-010", ["scancel", "取消任务"]),
    KnowledgeItem("faq-011", ["squeue", "查看作业", "排队列表"]),
    KnowledgeItem("faq-012", ["分区", "partition", "权限"]),
    KnowledgeItem("faq-013", ["日志", "没有日志文件", "空日志"]),
    KnowledgeItem("faq-014", ["语法错误", "SyntaxError", "脚本"]),
    KnowledgeItem("faq-015", ["路径错误", "No such file", "文件不存在"]),
    KnowledgeItem("faq-016", ["srun", "交互式", "--pty"]),
    KnowledgeItem("faq-017", ["磁盘空间", "不足", "存储"]),
    KnowledgeItem("faq-018", ["刷新分区", "节点状态", "idle"]),
    KnowledgeItem("faq-019", ["GitHub连不上", "网络", "上传"]),
    KnowledgeItem("faq-020", ["求助信息", "提供什么信息", "报错详情"]),
]


class MockVectorStore:
    """模拟向量数据库（待 B 实现 vector_store.py 后替换）.

    基于关键词重叠度做简单排序，模拟 embedding 语义检索的近邻效果。
    top_n 返回按得分降序的条目 id 列表。
    """

    def __init__(self, items: list[KnowledgeItem]) -> None:
        self.items = items

    def _score(self, item: KnowledgeItem, query: str) -> int:
        """基于关键词子串重叠打分，模拟语义检索的近邻效果."""
        q_lower = query.lower()
        score = 0
        for kw in item.keywords:
            if kw.lower() in q_lower:
                score += 1
        return score

    def search(self, query: str, top_n: int = 5) -> list[str]:
        """返回 top_n 个最相关条目的 id."""
        scored = [(self._score(item, query), item.id) for item in self.items]
        # 稳定排序：按得分降序，同分按 id 排序
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [item_id for score, item_id in scored[:top_n]]


# ── 测试查询（ground truth 由知识库定义） ──
RECALL_QUERIES: list[RecallQuery] = [
    RecallQuery(
        "QOS时间超限",
        "提交作业报 QOSMaxWallDurationPerJobLimit 超时限制 运行时间 怎么办",
        ["faq-001"],
    ),
    RecallQuery("CUDA 显存不足", "CUDA out of memory 显存不足 OOM 如何解决", ["faq-003"]),
    RecallQuery(
        "驱动不匹配",
        "nvidia-smi 找不到 GPU 驱动版本不匹配 Driver/library mismatch",
        ["faq-004", "faq-005"],
    ),
    RecallQuery("作业排队", "作业一直排队 PD pending 等待很久怎么办", ["faq-006"]),
    RecallQuery("conda 环境", "conda 未激活 找不到环境 怎么办", ["faq-007"]),
    RecallQuery("模块缺失", "ModuleNotFoundError 找不到模块 包未安装", ["faq-008"]),
    RecallQuery("提交批处理", "怎么用 sbatch 提交批处理作业", ["faq-009"]),
    RecallQuery("查看作业", "用 squeue 查看当前排队作业列表", ["faq-011", "faq-006"]),
    RecallQuery("分区权限", "分区选择 权限不足 partition 怎么办", ["faq-012"]),
    RecallQuery("日志缺失", "没有日志文件 日志为空 怎么办", ["faq-013"]),
    RecallQuery("脚本语法", "shell 脚本 语法错误 SyntaxError 怎么检查", ["faq-014"]),
    RecallQuery("路径错误", "路径错误 No such file 文件不存在 cd 失败", ["faq-015"]),
    RecallQuery("交互式调试", "如何用 srun --pty 交互式调试作业", ["faq-016"]),
    RecallQuery("磁盘空间", "磁盘空间不足 存储不够 怎么办", ["faq-017"]),
    RecallQuery("求助信息", "向管理员求助时应该提供什么信息 报错详情", ["faq-020"]),
]


@pytest.fixture
def store() -> MockVectorStore:
    """返回模拟向量库实例."""
    return MockVectorStore(KNOWLEDGE_BASE)


class TestRetrievalRecall:
    """检索召回率验收测试."""

    def _recall_at_n(self, store: MockVectorStore, q: RecallQuery, n: int) -> bool:
        """返回 top-n 结果是否覆盖该查询的全部相关条目."""
        retrieved = store.search(q.query, top_n=n)
        return all(rel in retrieved for rel in q.relevant_ids)

    @pytest.mark.parametrize("query", RECALL_QUERIES, ids=[q.name for q in RECALL_QUERIES])
    def test_top3_recall(self, store: MockVectorStore, query: RecallQuery) -> None:
        """每个查询 top-3 必须命中全部相关条目."""
        assert self._recall_at_n(store, query, 3), f"top-3 未召回查询 '{query.name}' 的全部相关条目"

    @pytest.mark.parametrize("query", RECALL_QUERIES, ids=[q.name for q in RECALL_QUERIES])
    def test_top5_recall(self, store: MockVectorStore, query: RecallQuery) -> None:
        """每个查询 top-5 必须命中全部相关条目（更宽松但要求更高覆盖率）."""
        assert self._recall_at_n(store, query, 5), f"top-5 未召回查询 '{query.name}' 的全部相关条目"

    def test_top3_recall_rate(self, store: MockVectorStore) -> None:
        """整体 top-3 召回率 >= 90%."""
        hit = sum(1 for q in RECALL_QUERIES if self._recall_at_n(store, q, 3))
        rate = hit / len(RECALL_QUERIES)
        assert (
            rate >= RECALL_TOP3_THRESHOLD
        ), f"top-3 召回率 {rate:.2%} < {RECALL_TOP3_THRESHOLD:.0%}"

    def test_top5_recall_rate(self, store: MockVectorStore) -> None:
        """整体 top-5 召回率 >= 95%."""
        hit = sum(1 for q in RECALL_QUERIES if self._recall_at_n(store, q, 5))
        rate = hit / len(RECALL_QUERIES)
        assert (
            rate >= RECALL_TOP5_THRESHOLD
        ), f"top-5 召回率 {rate:.2%} < {RECALL_TOP5_THRESHOLD:.0%}"


class TestRetrievalReport:
    """生成检索召回率测试报告."""

    def test_generate_recall_report(self, tmp_path: Path, store: MockVectorStore) -> None:
        """生成召回率测试报告（含逐查询 top-3/top-5 明细）."""
        details: list[dict[str, object]] = []
        top3_hits = 0
        top5_hits = 0

        for q in RECALL_QUERIES:
            ret3 = store.search(q.query, top_n=3)
            ret5 = store.search(q.query, top_n=5)
            hit3 = all(rel in ret3 for rel in q.relevant_ids)
            hit5 = all(rel in ret5 for rel in q.relevant_ids)
            top3_hits += int(hit3)
            top5_hits += int(hit5)
            details.append(
                {
                    "query": q.name,
                    "relevant": q.relevant_ids,
                    "top3": ret3,
                    "top5": ret5,
                    "hit_top3": hit3,
                    "hit_top5": hit5,
                }
            )

        total = len(RECALL_QUERIES)
        report = {
            "summary": {
                "total_queries": total,
                "top3_recall": f"{top3_hits / total:.2%}",
                "top5_recall": f"{top5_hits / total:.2%}",
                "top3_threshold": f"{RECALL_TOP3_THRESHOLD:.0%}",
                "top5_threshold": f"{RECALL_TOP5_THRESHOLD:.0%}",
            },
            "details": details,
        }

        report_file = tmp_path / "retrieval_recall_report.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        assert report_file.exists()
        assert top3_hits / total >= RECALL_TOP3_THRESHOLD
        assert top5_hits / total >= RECALL_TOP5_THRESHOLD
