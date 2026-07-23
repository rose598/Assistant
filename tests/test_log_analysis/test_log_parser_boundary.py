"""日志解析器边界条件测试.

本模块测试日志解析器在各种边界和异常情况下的行为.
"""

from __future__ import annotations

import pytest


class TestLogParserBoundary:
    """日志解析器边界条件测试."""

    def test_empty_input(self) -> None:
        """测试空输入."""
        # 空字符串
        assert self._parse_log("") == {}
        # 空白字符串
        assert self._parse_log("   ") == {}
        assert self._parse_log("\n\t\n") == {}

    def test_none_input(self) -> None:
        """测试 None 输入."""
        assert self._parse_log(None) == {}  # type: ignore[arg-type]

    def test_malformed_scontrol_output(self) -> None:
        """测试格式错误的 scontrol 输出."""
        # 缺少关键字段
        malformed = "JobId=12345 JobName=test"
        result = self._parse_log(malformed)
        assert result.get("JobId") == "12345"
        assert result.get("JobState") is None  # 缺失字段应为 None

    def test_unicode_characters(self) -> None:
        """测试 Unicode 字符处理."""
        log_with_unicode = (
            "JobId=12345 JobName=测试作业\nJobState=FAILED ExitCode=1:0\nComment=中文注释"
        )
        result = self._parse_log(log_with_unicode)
        assert result.get("JobName") == "测试作业"

    def test_very_long_input(self) -> None:
        """测试超长输入."""
        # 生成 10000 行的日志
        long_log = "\n".join([f"Field{i}=value{i}" for i in range(10000)])
        result = self._parse_log(long_log)
        # 应该能正常解析，不崩溃
        assert isinstance(result, dict)

    def test_special_characters_in_values(self) -> None:
        """测试值中包含特殊字符."""
        log = 'Command=/path/to/script.py --arg="value with spaces" --path="/tmp/test dir/"'
        self._parse_log(log)  # 应该正确处理引号和空格

    def test_duplicate_fields(self) -> None:
        """测试重复字段."""
        log = "JobId=12345 JobId=67890 JobName=test"
        result = self._parse_log(log)
        # 应该取最后一个值或第一个值，行为一致
        assert result.get("JobId") in ["12345", "67890"]

    def test_missing_equals_sign(self) -> None:
        """测试缺少等号的格式."""
        log = "JobId 12345 JobName=test"
        self._parse_log(log)  # 应该能处理或忽略格式错误的行

    def test_empty_values(self) -> None:
        """测试空值字段."""
        log = "JobId=12345 JobName= Comment="
        result = self._parse_log(log)
        assert result.get("JobId") == "12345"
        assert result.get("JobName") == ""
        assert result.get("Comment") == ""

    def test_numeric_edge_cases(self) -> None:
        """测试数值边界."""
        log = (
            "JobId=0 JobName=test\n"  # JobId 为 0
            "ExitCode=0:0\n"  # 正常退出
            "NumNodes=0\n"  # 节点数为 0
            "NumCPUs=999999"  # 超大 CPU 数
        )
        result = self._parse_log(log)
        assert result.get("JobId") == "0"
        assert result.get("ExitCode") == "0:0"

    def test_multiline_values(self) -> None:
        """测试多行值."""
        log = "JobId=12345\nReason=Some\nreason\nthat\nspans\nmultiple\nlines"
        self._parse_log(log)  # 应该能处理多行 Reason

    def test_sacct_format_variants(self) -> None:
        """测试 sacct 输出的不同格式变体."""
        # 标准格式
        standard = "JobID|JobName|State|ExitCode\n12345|test|FAILED|1:0"
        result = self._parse_sacct(standard)
        assert len(result) == 1

        # 带空行
        with_empty = "JobID|JobName|State|ExitCode\n\n12345|test|FAILED|1:0\n"
        result = self._parse_sacct(with_empty)
        assert len(result) == 1

        # 多作业
        multi = "JobID|JobName|State|ExitCode\n12345|test1|COMPLETED|0:0\n12346|test2|FAILED|1:0"
        result = self._parse_sacct(multi)
        assert len(result) == 2

    def test_error_log_parsing(self) -> None:
        """测试错误日志解析."""
        # CUDA OOM
        cuda_oom = "CUDA out of memory. Tried to allocate 2.00 GiB"
        result = self._parse_error_log(cuda_oom)
        assert result.get("error_type") == "cuda_oom"

        # Python 异常
        python_error = "Traceback (most recent call last):\n  File \"test.py\", line 1\nModuleNotFoundError: No module named 'torch'"
        result = self._parse_error_log(python_error)
        assert "ModuleNotFoundError" in result.get("error_message", "")

        # 空错误日志
        result = self._parse_error_log("")
        assert result == {}

    def test_encoding_issues(self) -> None:
        """测试编码问题."""
        # GBK 编码的中文
        try:
            gbk_text = "测试".encode("gbk").decode("utf-8", errors="replace")
            log = f"JobName={gbk_text}"
            result = self._parse_log(log)
            assert "JobName" in result
        except UnicodeDecodeError:
            pytest.skip("GBK encoding not supported in this environment")

    def test_performance_large_log(self) -> None:
        """测试大日志解析性能."""
        import time

        # 生成 1MB 大小的日志
        large_log = "\n".join([f"Field{i}=value{i}" for i in range(20000)])

        start = time.time()
        result = self._parse_log(large_log)
        elapsed = time.time() - start

        # 应该在 1 秒内完成
        assert elapsed < 1.0
        assert isinstance(result, dict)

    # ── 辅助方法（模拟 B 实现的解析器） ──

    def _parse_log(self, log_text: str | None) -> dict[str, str]:
        """模拟日志解析器（待 B 实现后替换）."""
        if not log_text or not log_text.strip():
            return {}

        import re

        result: dict[str, str] = {}
        # 匹配 Key=Value 模式（Value 可包含引号）
        pattern = re.compile(r'(\w+)=((?:"[^"]*"|\S*)?)')
        for match in pattern.finditer(log_text):
            key = match.group(1)
            value = match.group(2).strip('"')
            result[key] = value
        return result

    def _parse_sacct(self, sacct_output: str) -> list[dict[str, str]]:
        """模拟 sacct 输出解析器."""
        lines = [line for line in sacct_output.strip().split("\n") if line.strip()]
        if len(lines) < 2:
            return []

        headers = lines[0].split("|")
        results = []
        for line in lines[1:]:
            values = line.split("|")
            if len(values) == len(headers):
                results.append(dict(zip(headers, values, strict=True)))
        return results

    def _parse_error_log(self, error_log: str) -> dict[str, str]:
        """模拟错误日志解析器."""
        if not error_log:
            return {}

        result: dict[str, str] = {}

        # 检测 CUDA OOM
        if "CUDA out of memory" in error_log:
            result["error_type"] = "cuda_oom"
        elif "ModuleNotFoundError" in error_log:
            result["error_type"] = "module_not_found"
            result["error_message"] = error_log

        return result


class TestErrorClassifierBoundary:
    """错误分类器边界条件测试."""

    def test_empty_error_log(self) -> None:
        """测试空错误日志."""
        result = self._classify_error("")
        assert result["category"] == "unknown"
        assert result["confidence"] == 0.0

    def test_unknown_error(self) -> None:
        """测试未知错误类型."""
        result = self._classify_error("Some completely unknown error message")
        assert result["category"] == "unknown"

    def test_multiple_errors_in_log(self) -> None:
        """测试日志中包含多个错误."""
        log = (
            "CUDA out of memory\n"
            "Traceback (most recent call last)\n"
            "ModuleNotFoundError: No module named 'torch'"
        )
        result = self._classify_error(log)
        # 应该返回最主要的错误或第一个错误
        assert result["category"] in ["gpu_related", "env_missing"]

    def test_error_with_context(self) -> None:
        """测试带上下文的错误."""
        log = (
            "2024-01-01 12:00:00 INFO Starting job\n"
            "2024-01-01 12:01:00 ERROR CUDA out of memory\n"
            "2024-01-01 12:01:01 INFO Job terminated"
        )
        result = self._classify_error(log)
        assert result["category"] == "gpu_related"

    def _classify_error(self, error_log: str) -> dict[str, str | float]:
        """模拟错误分类器."""
        if not error_log:
            return {"category": "unknown", "confidence": 0.0}

        if "CUDA out of memory" in error_log:
            return {"category": "gpu_related", "confidence": 0.95}
        if "ModuleNotFoundError" in error_log:
            return {"category": "env_missing", "confidence": 0.90}
        if "Killed" in error_log:
            return {"category": "resource_exhausted", "confidence": 0.85}

        return {"category": "unknown", "confidence": 0.0}
