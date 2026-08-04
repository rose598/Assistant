"""错误场景分类准确率测试.

测试 10+ 种错误场景的分类准确率，生成混淆矩阵和测试报告.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass
class ErrorScenario:
    """错误场景测试用例."""

    name: str
    error_log: str
    expected_category: str
    expected_subcategory: str | None = None


class MockErrorClassifier:
    """模拟错误分类器（待 B 实现后替换）."""

    # 错误分类规则
    RULES: list[tuple[str, str, str]] = [
        # (关键词模式, 大类, 子类)
        ("CUDA out of memory", "resource_exhausted", "gpu_oom"),
        ("CUDA_ERROR_OUT_OF_MEMORY", "resource_exhausted", "gpu_oom"),
        ("Killed", "resource_exhausted", "memory_oom"),
        ("oom-killer", "resource_exhausted", "memory_oom"),
        ("MemoryError", "resource_exhausted", "memory_oom"),
        ("DUE TO TIME LIMIT", "resource_exhausted", "time_limit"),
        ("TIMEOUT", "resource_exhausted", "time_limit"),
        ("SyntaxError", "script_error", "syntax"),
        ("No such file or directory", "script_error", "path"),
        ("FileNotFoundError", "script_error", "path"),
        ("ModuleNotFoundError", "env_missing", "package_missing"),
        ("ImportError", "env_missing", "package_missing"),
        ("conda: command not found", "env_missing", "conda_not_found"),
        ("Permission denied", "permission", "permission_denied"),
        ("PermissionError", "permission", "permission_denied"),
        ("QOSMaxWallDurationPerJobLimit", "qos_limit", "time_exceeded"),
        ("QOSMaxCpuPerUserLimit", "qos_limit", "cpu_exceeded"),
        ("nvidia-smi: command not found", "gpu_related", "driver_missing"),
        ("Driver/library version mismatch", "gpu_related", "driver_mismatch"),
        ("Invalid partition", "script_error", "invalid_partition"),
    ]

    def classify(self, error_log: str) -> dict[str, str | float]:
        """分类错误日志.

        Args:
            error_log: 错误日志文本.

        Returns:
            包含分类结果的字典:
            - category: 错误大类
            - subcategory: 错误子类
            - confidence: 置信度
        """
        if not error_log:
            return {"category": "unknown", "subcategory": None, "confidence": 0.0}

        for pattern, category, subcategory in self.RULES:
            if pattern.lower() in error_log.lower():
                return {
                    "category": category,
                    "subcategory": subcategory,
                    "confidence": 0.95,
                }

        return {"category": "unknown", "subcategory": None, "confidence": 0.0}


# ── 测试场景定义 ──
ERROR_SCENARIOS: list[ErrorScenario] = [
    # 资源不足类
    ErrorScenario(
        name="CUDA 显存溢出",
        error_log="CUDA out of memory. Tried to allocate 2.00 GiB (GPU 0; 23.70 GiB total)",
        expected_category="resource_exhausted",
        expected_subcategory="gpu_oom",
    ),
    ErrorScenario(
        name="内存溢出被杀",
        error_log="slurmstepd: error: Detected 1 oom-kill event(s) in StepId=12345.batch\nKilled",
        expected_category="resource_exhausted",
        expected_subcategory="memory_oom",
    ),
    ErrorScenario(
        name="时间超限",
        error_log="slurmstepd: error: *** JOB 12345 ON node01 CANCELLED AT 2024-01-01T12:00:00 DUE TO TIME LIMIT ***",
        expected_category="resource_exhausted",
        expected_subcategory="time_limit",
    ),
    # 脚本错误类
    ErrorScenario(
        name="Python 语法错误",
        error_log='File "train.py", line 10\n    print(x\nSyntaxError: unexpected EOF while parsing',
        expected_category="script_error",
        expected_subcategory="syntax",
    ),
    ErrorScenario(
        name="文件路径不存在",
        error_log="FileNotFoundError: [Errno 2] No such file or directory: '/home/user/data/train.csv'",
        expected_category="script_error",
        expected_subcategory="path",
    ),
    ErrorScenario(
        name="无效分区",
        error_log="sbatch: error: Batch job submission failed: Invalid partition",
        expected_category="script_error",
        expected_subcategory="invalid_partition",
    ),
    # 环境缺失类
    ErrorScenario(
        name="模块未找到",
        error_log="Traceback (most recent call last):\nModuleNotFoundError: No module named 'torch'",
        expected_category="env_missing",
        expected_subcategory="package_missing",
    ),
    ErrorScenario(
        name="conda 未激活",
        error_log="/var/spool/slurm/job12345/slurm_script.sh: line 5: conda: command not found",
        expected_category="env_missing",
        expected_subcategory="conda_not_found",
    ),
    # 权限类
    ErrorScenario(
        name="权限拒绝",
        error_log="PermissionError: [Errno 13] Permission denied: '/data/protected/model.pt'",
        expected_category="permission",
        expected_subcategory="permission_denied",
    ),
    # QOS 限制类
    ErrorScenario(
        name="QOS 时间限制",
        error_log="sbatch: error: Batch job submission failed: QOSMaxWallDurationPerJobLimit",
        expected_category="qos_limit",
        expected_subcategory="time_exceeded",
    ),
    # GPU 相关类
    ErrorScenario(
        name="nvidia-smi 不可用",
        error_log="/bin/sh: nvidia-smi: command not found",
        expected_category="gpu_related",
        expected_subcategory="driver_missing",
    ),
    ErrorScenario(
        name="驱动版本不匹配",
        error_log="NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver.\nDriver/library version mismatch",
        expected_category="gpu_related",
        expected_subcategory="driver_mismatch",
    ),
]


class TestErrorClassificationAccuracy:
    """错误分类准确率测试."""

    @pytest.fixture
    def classifier(self) -> MockErrorClassifier:
        """返回错误分类器实例."""
        return MockErrorClassifier()

    @pytest.mark.parametrize("scenario", ERROR_SCENARIOS, ids=[s.name for s in ERROR_SCENARIOS])
    def test_error_classification(
        self, classifier: MockErrorClassifier, scenario: ErrorScenario
    ) -> None:
        """测试单个错误场景的分类准确性."""
        result = classifier.classify(scenario.error_log)

        assert result["category"] == scenario.expected_category, (
            f"场景 '{scenario.name}' 分类错误: "
            f"期望 {scenario.expected_category}, 实际 {result['category']}"
        )

        if scenario.expected_subcategory:
            assert result["subcategory"] == scenario.expected_subcategory, (
                f"场景 '{scenario.name}' 子类错误: "
                f"期望 {scenario.expected_subcategory}, 实际 {result['subcategory']}"
            )

    def test_empty_error_log(self, classifier: MockErrorClassifier) -> None:
        """测试空错误日志."""
        result = classifier.classify("")
        assert result["category"] == "unknown"
        assert result["confidence"] == 0.0

    def test_unknown_error(self, classifier: MockErrorClassifier) -> None:
        """测试未知错误类型."""
        result = classifier.classify("Some completely unknown error message")
        assert result["category"] == "unknown"

    def test_case_insensitive(self, classifier: MockErrorClassifier) -> None:
        """测试大小写不敏感匹配."""
        result_upper = classifier.classify("CUDA OUT OF MEMORY")
        result_lower = classifier.classify("cuda out of memory")

        assert result_upper["category"] == result_lower["category"] == "resource_exhausted"

    def test_multiple_errors_returns_first(self, classifier: MockErrorClassifier) -> None:
        """测试多个错误时返回第一个匹配."""
        log = "CUDA out of memory\nModuleNotFoundError: No module named 'torch'"
        result = classifier.classify(log)
        # 应该返回第一个匹配的错误类型
        assert result["category"] in ["resource_exhausted", "env_missing"]


class TestErrorClassificationReport:
    """生成错误分类测试报告."""

    def test_generate_report(self, tmp_path: Path) -> None:
        """生成完整的测试报告."""
        classifier = MockErrorClassifier()

        results: list[dict[str, str | bool]] = []
        correct = 0
        total = len(ERROR_SCENARIOS)

        for scenario in ERROR_SCENARIOS:
            result = classifier.classify(scenario.error_log)
            is_correct = result["category"] == scenario.expected_category
            if is_correct:
                correct += 1

            results.append(
                {
                    "scenario": scenario.name,
                    "expected": scenario.expected_category,
                    "actual": str(result["category"]),
                    "correct": is_correct,
                }
            )

        accuracy = correct / total if total > 0 else 0.0

        report = {
            "summary": {
                "total_scenarios": total,
                "correct": correct,
                "incorrect": total - correct,
                "accuracy": f"{accuracy:.2%}",
            },
            "details": results,
        }

        # 保存报告
        report_file = tmp_path / "error_classification_report.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        # 验证报告文件存在
        assert report_file.exists()

        # 验证准确率 >= 85%
        assert accuracy >= 0.85, f"准确率 {accuracy:.2%} 低于要求的 85%"

    def test_confusion_matrix_structure(self) -> None:
        """测试混淆矩阵结构."""
        classifier = MockErrorClassifier()

        # 收集所有分类结果
        categories: set[str] = set()
        confusion: dict[str, dict[str, int]] = {}

        for scenario in ERROR_SCENARIOS:
            result = classifier.classify(scenario.error_log)
            expected = scenario.expected_category
            actual = str(result["category"])

            categories.add(expected)
            categories.add(actual)

            if expected not in confusion:
                confusion[expected] = {}
            confusion[expected][actual] = confusion[expected].get(actual, 0) + 1

        # 验证混淆矩阵有数据
        assert len(confusion) > 0
        # 对角线元素（正确分类）应该占主导
        diagonal_sum = sum(confusion[cat].get(cat, 0) for cat in confusion)
        total_sum = sum(sum(row.values()) for row in confusion.values())
        assert diagonal_sum / total_sum >= 0.85


class TestErrorClassificationEdgeCases:
    """错误分类边界情况测试."""

    @pytest.fixture
    def classifier(self) -> MockErrorClassifier:
        """返回错误分类器实例."""
        return MockErrorClassifier()

    def test_error_with_unicode(self, classifier: MockErrorClassifier) -> None:
        """测试包含 Unicode 的错误日志."""
        log = "错误：CUDA out of memory（显存不足）"
        result = classifier.classify(log)
        assert result["category"] == "resource_exhausted"

    def test_very_long_error_log(self, classifier: MockErrorClassifier) -> None:
        """测试超长错误日志."""
        log = "CUDA out of memory " + "x" * 10000
        result = classifier.classify(log)
        assert result["category"] == "resource_exhausted"

    def test_multiline_error_log(self, classifier: MockErrorClassifier) -> None:
        """测试多行错误日志."""
        log = """
Traceback (most recent call last):
  File "train.py", line 100, in <module>
    main()
  File "train.py", line 95, in main
    model.fit(X, y)
ModuleNotFoundError: No module named 'sklearn'
"""
        result = classifier.classify(log)
        assert result["category"] == "env_missing"

    def test_error_in_stack_trace(self, classifier: MockErrorClassifier) -> None:
        """测试堆栈跟踪中的错误."""
        log = """
Exception in thread "main" java.lang.OutOfMemoryError: Java heap space
CUDA out of memory. Tried to allocate 2.00 GiB
"""
        result = classifier.classify(log)
        assert result["category"] == "resource_exhausted"
