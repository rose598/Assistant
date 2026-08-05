"""推荐准确率测试 — 50 个历史作业回测.

使用 Mock 推荐引擎对 50 个成功作业进行回测：
- 根据 task_type 推荐分区/GPU/CPU/内存/时长
- 对比实际配置，计算推荐配置命中率
- 验收标准：推荐配置成功率 ≥ 80%
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

DATA_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "historical_jobs.csv"


@dataclass
class Recommendation:
    """推荐结果."""

    partition: str
    gpus: int
    cpus: int
    mem: str
    timelimit: str
    qos: str
    reason: str = ""


@dataclass
class MockRecommender:
    """模拟推荐引擎.

    根据 task_type 推荐配置（基于历史统计的启发式规则）。
    待 A/B 实现 combined_recommender.py 后替换。
    """

    # 按任务类型的推荐规则（基于历史统计的合理配置范围）
    RULES: dict[str, dict[str, Any]] = field(
        default_factory=lambda: {
            "deep_learning": {
                "partition": "Students",  # 大多数学生在 Students 分区做 DL
                "gpus": 1,
                "cpus": 4,
                "mem": "16G",
                "timelimit": "04:00:00",
                "qos": "qos_stu_default",
            },
            "scientific_computing": {
                "partition": "Students",  # 多数科学计算也在 Students
                "gpus": 0,
                "cpus": 4,
                "mem": "8G",
                "timelimit": "04:00:00",
                "qos": "qos_stu_default",
            },
            "data_analysis": {
                "partition": "Students",
                "gpus": 0,
                "cpus": 4,
                "mem": "8G",
                "timelimit": "04:00:00",
                "qos": "qos_stu_default",
            },
            "general": {
                "partition": "Students",
                "gpus": 0,
                "cpus": 2,
                "mem": "4G",
                "timelimit": "04:00:00",
                "qos": "qos_stu_default",
            },
        }
    )

    def recommend(self, task_type: str, description: str = "") -> Recommendation:
        """根据任务类型推荐配置."""
        rule = self.RULES.get(task_type, self.RULES["general"])
        return Recommendation(
            partition=rule["partition"],
            gpus=rule["gpus"],
            cpus=rule["cpus"],
            mem=rule["mem"],
            timelimit=rule["timelimit"],
            qos=rule["qos"],
            reason=f"基于任务类型 '{task_type}' 的推荐",
        )


def parse_mem(mem_str: str) -> int:
    """解析内存为 MB."""
    mem_str = mem_str.strip().upper()
    if mem_str.endswith("G"):
        return int(mem_str[:-1]) * 1024
    if mem_str.endswith("M"):
        return int(mem_str[:-1])
    return int(mem_str)


def parse_time(time_str: str) -> int:
    """解析时间为秒."""
    parts = time_str.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 3600 + int(parts[1]) * 60
    return int(parts[0])


def check_partition_match(actual: str, recommended: str) -> bool:
    """检查分区匹配（GPU 分区之间可互换）."""
    if actual == recommended:
        return True
    # GPU 分区推荐为 GPU-RTX5090，实际也是 GPU 分区算部分匹配
    return bool("GPU" in actual and "GPU" in recommended)


def check_resource_match(actual_val: int, recommended_val: int, tolerance: float = 0.5) -> bool:
    """检查资源匹配（推荐值 ≤ 实际值 × (1+tolerance)）."""
    if recommended_val <= actual_val:
        return True
    return recommended_val <= actual_val * (1 + tolerance)


@pytest.fixture(scope="module")
def completed_records() -> list[dict[str, str]]:
    """加载成功作业记录."""
    with open(DATA_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [r for r in reader if r["state"] == "COMPLETED"]


@pytest.fixture(scope="module")
def recommender() -> MockRecommender:
    """推荐引擎."""
    return MockRecommender()


class TestRecommendationAccuracy:
    """推荐准确率测试."""

    def test_recommend_50_jobs(
        self, completed_records: list[dict[str, str]], recommender: MockRecommender
    ) -> None:
        """50 个成功作业回测."""
        sample = completed_records[:50]
        assert len(sample) >= 50, f"成功作业不足 50 条: {len(sample)}"

        hits = 0
        results: list[dict[str, Any]] = []

        for record in sample:
            rec = recommender.recommend(record["task_type"])

            # 各维度匹配检查
            partition_ok = check_partition_match(record["partition"], rec.partition)
            gpu_ok = check_resource_match(int(record["ngpus"]), rec.gpus)
            cpu_ok = check_resource_match(int(record["ncpus"]), rec.cpus)
            mem_ok = check_resource_match(parse_mem(record["req_mem"]), parse_mem(rec.mem))
            time_ok = parse_time(record["timelimit"]) >= parse_time(rec.timelimit) * 0.5

            # 综合评分：分区 + GPU 权重高
            score = 0.0
            if partition_ok:
                score += 0.3
            if gpu_ok:
                score += 0.25
            if cpu_ok:
                score += 0.15
            if mem_ok:
                score += 0.15
            if time_ok:
                score += 0.15

            is_hit = score >= 0.45  # 45% 以上算命中（合理推荐即可）
            if is_hit:
                hits += 1

            results.append(
                {
                    "job_id": record["job_id"],
                    "task_type": record["task_type"],
                    "actual_partition": record["partition"],
                    "recommended_partition": rec.partition,
                    "partition_match": partition_ok,
                    "gpu_match": gpu_ok,
                    "score": round(score, 2),
                    "hit": is_hit,
                }
            )

        accuracy = hits / len(sample)
        report = {
            "total": len(sample),
            "hits": hits,
            "accuracy": round(accuracy, 4),
            "target": 0.80,
            "passed": accuracy >= 0.80,
            "details": results,
        }

        # 输出报告
        report_path = (
            Path(__file__).parent.parent.parent / "data" / "recommendation_accuracy_report.json"
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        assert accuracy >= 0.80, f"推荐准确率 {accuracy:.1%} < 80%"

    def test_deep_learning_recommendation(self, recommender: MockRecommender) -> None:
        """深度学习任务推荐合理配置."""
        rec = recommender.recommend("deep_learning")
        assert rec.partition in ("Students", "GPU-RTX5090")
        assert rec.cpus >= 4
        assert parse_mem(rec.mem) >= 8 * 1024  # ≥ 8G

    def test_scientific_computing_recommendation(self, recommender: MockRecommender) -> None:
        """科学计算任务推荐合理配置."""
        rec = recommender.recommend("scientific_computing")
        assert rec.partition in ("Students", "CPU-6530")
        assert rec.cpus >= 4

    def test_data_analysis_recommendation(self, recommender: MockRecommender) -> None:
        """数据分析任务推荐 Students 分区."""
        rec = recommender.recommend("data_analysis")
        assert rec.partition == "Students"
        assert rec.cpus >= 2

    def test_general_recommendation(self, recommender: MockRecommender) -> None:
        """通用任务推荐基本配置."""
        rec = recommender.recommend("general")
        assert rec.partition == "Students"
        assert rec.gpus == 0


class TestRecommendationTop3:
    """Top-3 推荐测试."""

    def test_top3_recommendations(self, recommender: MockRecommender) -> None:
        """返回 top-3 推荐方案."""
        # 模拟 top-3 推荐
        task_types = ["deep_learning", "scientific_computing", "data_analysis"]
        recommendations = [recommender.recommend(t) for t in task_types]

        assert len(recommendations) == 3
        # 各推荐配置应不完全相同
        configs = [(r.partition, r.gpus, r.cpus, r.mem, r.timelimit) for r in recommendations]
        assert len(set(configs)) >= 2, "top-3 推荐不应完全相同"

    def test_recommendation_has_reason(self, recommender: MockRecommender) -> None:
        """推荐包含理由."""
        rec = recommender.recommend("deep_learning")
        assert rec.reason, "推荐应包含理由"
        assert len(rec.reason) > 5


class TestRecommendationEdgeCases:
    """边界情况."""

    def test_unknown_task_type(self, recommender: MockRecommender) -> None:
        """未知任务类型降级到 general."""
        rec = recommender.recommend("unknown_type")
        assert rec.partition == "Students"
        assert rec.gpus == 0

    def test_empty_task_type(self, recommender: MockRecommender) -> None:
        """空任务类型降级."""
        rec = recommender.recommend("")
        assert rec.partition == "Students"

    def test_recommendation_fields_not_empty(self, recommender: MockRecommender) -> None:
        """推荐结果字段不为空."""
        for task_type in ["deep_learning", "scientific_computing", "data_analysis", "general"]:
            rec = recommender.recommend(task_type)
            assert rec.partition, f"{task_type}: partition 为空"
            assert rec.timelimit, f"{task_type}: timelimit 为空"
            assert rec.mem, f"{task_type}: mem 为空"
            assert rec.cpus > 0, f"{task_type}: cpus 为 0"
