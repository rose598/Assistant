"""历史作业数据样本验证测试.

验证 data/historical_jobs.csv 的数据质量：
- 记录数量 ≥ 200
- 字段完整性
- 数据分布合理性
- 时间逻辑一致性
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

DATA_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "historical_jobs.csv"
REQUIRED_FIELDS = [
    "job_id",
    "user",
    "job_name",
    "partition",
    "qos",
    "ncpus",
    "ngpus",
    "req_mem",
    "timelimit",
    "submit_time",
    "start_time",
    "end_time",
    "state",
    "exit_code",
    "task_type",
    "wait_time_seconds",
    "elapsed_time_seconds",
    "error_type",
    "weekday",
    "hour",
]
VALID_PARTITIONS = {"Students", "CPU-6530", "GPU-RTX5090"}
VALID_STATES = {"COMPLETED", "FAILED", "TIMEOUT", "CANCELLED"}
VALID_TASK_TYPES = {"deep_learning", "scientific_computing", "data_analysis", "general"}


@pytest.fixture(scope="module")
def records() -> list[dict[str, str]]:
    """加载 CSV 数据."""
    assert DATA_PATH.exists(), f"数据文件不存在: {DATA_PATH}"
    with open(DATA_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


class TestDataVolume:
    """数据量验证."""

    def test_record_count_at_least_200(self, records: list[dict[str, str]]) -> None:
        """至少 200 条记录."""
        assert len(records) >= 200, f"记录数不足: {len(records)}"

    def test_all_fields_present(self, records: list[dict[str, str]]) -> None:
        """所有必填字段存在."""
        for i, record in enumerate(records):
            for field in REQUIRED_FIELDS:
                assert field in record, f"记录 {i} 缺少字段: {field}"

    def test_no_empty_job_ids(self, records: list[dict[str, str]]) -> None:
        """job_id 不为空."""
        for record in records:
            assert record["job_id"].strip(), "job_id 为空"


class TestDataDistribution:
    """数据分布合理性."""

    def test_partition_distribution(self, records: list[dict[str, str]]) -> None:
        """各分区都有记录."""
        partitions = {r["partition"] for r in records}
        assert partitions == VALID_PARTITIONS, f"分区不完整: {partitions}"

    def test_state_distribution(self, records: list[dict[str, str]]) -> None:
        """状态分布合理（成功 > 50%）."""
        states: dict[str, int] = {}
        for r in records:
            states[r["state"]] = states.get(r["state"], 0) + 1
        completed = states.get("COMPLETED", 0)
        assert completed / len(records) >= 0.5, f"成功率过低: {completed}/{len(records)}"

    def test_task_type_distribution(self, records: list[dict[str, str]]) -> None:
        """4 种任务类型都有覆盖."""
        task_types = {r["task_type"] for r in records}
        assert task_types == VALID_TASK_TYPES, f"任务类型不完整: {task_types}"

    def test_each_partition_has_enough_records(self, records: list[dict[str, str]]) -> None:
        """每个分区至少 30 条."""
        partition_counts: dict[str, int] = {}
        for r in records:
            partition_counts[r["partition"]] = partition_counts.get(r["partition"], 0) + 1
        for p, count in partition_counts.items():
            assert count >= 30, f"分区 {p} 记录不足: {count}"

    def test_failed_records_have_error_type(self, records: list[dict[str, str]]) -> None:
        """失败作业有错误类型."""
        for r in records:
            if r["state"] == "FAILED":
                assert r["error_type"].strip(), f"FAILED 作业 {r['job_id']} 缺少 error_type"

    def test_completed_records_no_error(self, records: list[dict[str, str]]) -> None:
        """成功作业无错误类型."""
        for r in records:
            if r["state"] == "COMPLETED":
                assert not r[
                    "error_type"
                ].strip(), f"COMPLETED 作业 {r['job_id']} 不应有 error_type"


class TestDataConsistency:
    """数据逻辑一致性."""

    def test_valid_partition_values(self, records: list[dict[str, str]]) -> None:
        """分区值合法."""
        for r in records:
            assert r["partition"] in VALID_PARTITIONS, f"非法分区: {r['partition']}"

    def test_valid_state_values(self, records: list[dict[str, str]]) -> None:
        """状态值合法."""
        for r in records:
            assert r["state"] in VALID_STATES, f"非法状态: {r['state']}"

    def test_cpus_are_numeric(self, records: list[dict[str, str]]) -> None:
        """CPU 数量为数字."""
        for r in records:
            assert int(r["ncpus"]) > 0, f"CPU 数量无效: {r['ncpus']}"

    def test_gpus_are_numeric(self, records: list[dict[str, str]]) -> None:
        """GPU 数量为数字."""
        for r in records:
            assert int(r["ngpus"]) >= 0, f"GPU 数量无效: {r['ngpus']}"

    def test_gpu_partition_has_gpus(self, records: list[dict[str, str]]) -> None:
        """GPU 分区作业有 GPU."""
        for r in records:
            if r["partition"] == "GPU-RTX5090":
                assert int(r["ngpus"]) >= 1, f"GPU 分区作业 {r['job_id']} 没有 GPU"

    def test_cpu_partition_no_gpus(self, records: list[dict[str, str]]) -> None:
        """CPU 分区作业无 GPU."""
        for r in records:
            if r["partition"] == "CPU-6530":
                assert int(r["ngpus"]) == 0, f"CPU 分区作业 {r['job_id']} 有 GPU"

    def test_wait_time_non_negative(self, records: list[dict[str, str]]) -> None:
        """等待时间非负."""
        for r in records:
            assert int(r["wait_time_seconds"]) >= 0, f"等待时间为负: {r['job_id']}"

    def test_elapsed_time_positive(self, records: list[dict[str, str]]) -> None:
        """运行时长正数."""
        for r in records:
            assert int(r["elapsed_time_seconds"]) > 0, f"运行时长无效: {r['job_id']}"

    def test_time_ordering(self, records: list[dict[str, str]]) -> None:
        """时间顺序：submit ≤ start ≤ end."""
        for r in records:
            submit = r["submit_time"]
            start = r["start_time"]
            end = r["end_time"]
            assert submit <= start, f"时间顺序错误 submit>start: {r['job_id']}"
            assert start <= end, f"时间顺序错误 start>end: {r['job_id']}"

    def test_exit_code_format(self, records: list[dict[str, str]]) -> None:
        """exit_code 格式为 N:N."""
        for r in records:
            parts = r["exit_code"].split(":")
            assert len(parts) == 2, f"exit_code 格式错误: {r['exit_code']}"
            assert parts[0].isdigit() and parts[1].isdigit()

    def test_completed_exit_code_zero(self, records: list[dict[str, str]]) -> None:
        """成功作业 exit_code 为 0:0."""
        for r in records:
            if r["state"] == "COMPLETED":
                assert r["exit_code"] == "0:0", f"COMPLETED 作业 {r['job_id']} exit_code 不是 0:0"


class TestDataUsability:
    """数据可用性验证（推荐系统所需）."""

    def test_has_both_success_and_failure(self, records: list[dict[str, str]]) -> None:
        """同时包含成功和失败记录."""
        states = {r["state"] for r in records}
        assert "COMPLETED" in states
        assert "FAILED" in states

    def test_has_multiple_users(self, records: list[dict[str, str]]) -> None:
        """多用户数据."""
        users = {r["user"] for r in records}
        assert len(users) >= 10, f"用户数不足: {len(users)}"

    def test_has_varied_time_limits(self, records: list[dict[str, str]]) -> None:
        """多种时间限制."""
        limits = {r["timelimit"] for r in records}
        assert len(limits) >= 4, f"时间限制种类不足: {len(limits)}"

    def test_has_weekday_info(self, records: list[dict[str, str]]) -> None:
        """包含星期信息（用于排队预测）."""
        weekdays = {r["weekday"] for r in records}
        assert len(weekdays) >= 5, f"星期覆盖不足: {weekdays}"

    def test_has_hour_info(self, records: list[dict[str, str]]) -> None:
        """包含小时信息（用于排队预测）."""
        hours = {int(r["hour"]) for r in records}
        assert len(hours) >= 10, f"小时覆盖不足: {len(hours)}"
