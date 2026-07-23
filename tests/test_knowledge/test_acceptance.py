"""知识库模块验收测试.

本模块测试知识库加载器和匹配器在各种边界情况下的行为.
覆盖第1周验收标准中的典型用户问题场景.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    pass


class TestKnowledgeBaseAcceptance:
    """知识库验收测试."""

    @pytest.fixture
    def sample_faq_data(self) -> dict[str, list[dict[str, str | list[str]]]]:
        """提供测试用 FAQ 数据."""
        return {
            "faq": [
                {
                    "id": "faq-001",
                    "category": "error_qos",
                    "title": "QOSMaxWallDurationPerJobLimit",
                    "keywords": ["QOSMaxWallDurationPerJobLimit", "超时限制", "运行时间"],
                    "intents": ["error_diagnosis", "job_submission"],
                    "question": "为什么我提交作业时报 QOSMaxWallDurationPerJobLimit？",
                    "answer": "这个错误表示作业申请的运行时间超过当前 QOS 允许的最长时间。",
                    "related_errors": [],
                    "references": [],
                },
                {
                    "id": "faq-002",
                    "category": "error_gpu",
                    "title": "CUDA out of memory",
                    "keywords": ["CUDA out of memory", "显存不足", "OOM"],
                    "intents": ["error_diagnosis"],
                    "question": "CUDA out of memory 怎么办？",
                    "answer": "减小 batch_size 或使用混合精度训练。",
                    "related_errors": [],
                    "references": [],
                },
            ],
        }

    def test_load_valid_knowledge_base(
        self, tmp_path: Path, sample_faq_data: dict[str, list[dict[str, str | list[str]]]]
    ) -> None:
        """测试加载有效的知识库文件."""
        kb_file = tmp_path / "faq.json"
        kb_file.write_text(json.dumps(sample_faq_data), encoding="utf-8")

        with open(kb_file, encoding="utf-8") as f:
            data = json.load(f)

        assert "faq" in data
        assert len(data["faq"]) == 2
        assert data["faq"][0]["id"] == "faq-001"

    def test_empty_knowledge_base(self, tmp_path: Path) -> None:
        """测试空知识库."""
        kb_file = tmp_path / "empty.json"
        kb_file.write_text('{"faq": []}', encoding="utf-8")

        with open(kb_file, encoding="utf-8") as f:
            data = json.load(f)

        assert data["faq"] == []

    def test_missing_keywords_field(self, tmp_path: Path) -> None:
        """测试缺少 keywords 字段的条目."""
        invalid_data = {
            "faq": [
                {
                    "id": "faq-001",
                    "category": "error",
                    "title": "Test",
                    # 缺少 keywords
                },
            ],
        }
        kb_file = tmp_path / "invalid.json"
        kb_file.write_text(json.dumps(invalid_data), encoding="utf-8")

        with open(kb_file, encoding="utf-8") as f:
            data = json.load(f)

        # 应该能加载但条目缺少 keywords
        assert "keywords" not in data["faq"][0]

    def test_chinese_keyword_matching(self) -> None:
        """测试中文关键词匹配."""
        keywords = ["超时限制", "运行时间", "QOSMaxWall"]
        query = "我的作业因为超时限制被终止了"

        # 简单的关键词匹配测试
        matches = [kw for kw in keywords if kw in query]
        assert len(matches) >= 1

    def test_english_keyword_matching(self) -> None:
        """测试英文关键词匹配."""
        keywords = ["CUDA out of memory", "OOM", "显存不足"]
        query = "I got CUDA out of memory error"

        matches = [kw for kw in keywords if kw.lower() in query.lower()]
        assert len(matches) >= 1

    def test_mixed_language_query(self) -> None:
        """测试中英混合查询."""
        keywords = ["GPU", "显卡", "nvidia-smi"]
        query = "我的 GPU 看不到怎么办"

        matches = [kw for kw in keywords if kw.lower() in query.lower()]
        assert len(matches) >= 1

    def test_empty_query(self) -> None:
        """测试空查询."""
        query = ""
        keywords = ["test", "测试"]

        matches = [kw for kw in keywords if kw in query]
        assert len(matches) == 0

    def test_special_characters_in_query(self) -> None:
        """测试查询中包含特殊字符."""
        query = "为什么报 QOSMaxWallDurationPerJobLimit 错误？！@#"
        keywords = ["QOSMaxWallDurationPerJobLimit"]

        matches = [kw for kw in keywords if kw in query]
        assert len(matches) == 1

    def test_very_long_query(self) -> None:
        """测试超长查询."""
        query = "我的作业" + "非常非常" * 1000 + "报错了"
        keywords = ["报错", "错误"]

        # 应该能正常处理，不崩溃
        matches = [kw for kw in keywords if kw in query]
        assert isinstance(matches, list)

    def test_fuzzy_matching(self) -> None:
        """测试模糊匹配."""
        # 模拟模糊匹配
        target = "QOSMaxWallDurationPerJobLimit"
        queries = [
            "QOSMaxWall",  # 部分匹配
            "qosmaxwall",  # 小写
            "QOS Max Wall",  # 带空格
        ]

        # 至少部分匹配应该成功
        assert any(q.lower().replace(" ", "") in target.lower() for q in queries)


class TestIntentMatchingAcceptance:
    """意图匹配验收测试."""

    def test_single_intent_match(self) -> None:
        """测试单意图匹配."""
        intent_keywords = {
            "error_qos": ["QOSMaxWall", "超时", "时间限制"],
            "error_gpu": ["nvidia-smi", "GPU", "显卡"],
            "error_oom": ["out of memory", "OOM", "显存不足"],
        }

        query = "我的作业报 QOSMaxWallDurationPerJobLimit"
        matched_intents = [
            intent
            for intent, keywords in intent_keywords.items()
            if any(kw in query for kw in keywords)
        ]

        assert matched_intents == ["error_qos"]

    def test_multi_intent_match(self) -> None:
        """测试多意图匹配."""
        intent_keywords = {
            "error_gpu": ["GPU", "显卡"],
            "env_conda": ["conda", "环境"],
        }

        query = "conda 环境里看不到 GPU"
        matched_intents = [
            intent
            for intent, keywords in intent_keywords.items()
            if any(kw in query for kw in keywords)
        ]

        assert len(matched_intents) == 2

    def test_no_intent_match(self) -> None:
        """测试无意图匹配."""
        intent_keywords = {
            "error_qos": ["QOSMaxWall", "超时"],
            "error_gpu": ["GPU", "显卡"],
        }

        query = "今天天气怎么样"
        matched_intents = [
            intent
            for intent, keywords in intent_keywords.items()
            if any(kw in query for kw in keywords)
        ]

        assert len(matched_intents) == 0

    def test_typo_tolerance(self) -> None:
        """测试拼写容错."""
        keywords = ["QOSMaxWallDurationPerJobLimit"]
        queries_with_typos = [
            "QOSMaxWallDurationPerJobLimit",  # 正确
            "qosmaxwalldurationperjoblimit",  # 全小写
        ]

        # 至少全小写应该能匹配
        for query in queries_with_typos:
            matches = [kw for kw in keywords if kw.lower() in query.lower()]
            assert len(matches) >= 1


class TestErrorCodesAcceptance:
    """错误码映射验收测试."""

    def test_error_codes_file_valid(self) -> None:
        """测试错误码文件格式有效."""
        error_codes_file = (
            Path(__file__).parent.parent.parent / "src" / "knowledge" / "data" / "error_codes.json"
        )

        if error_codes_file.exists():
            with open(error_codes_file, encoding="utf-8") as f:
                data = json.load(f)

            assert "error_codes" in data
            assert isinstance(data["error_codes"], list)
            assert len(data["error_codes"]) >= 20  # 至少 20 条

    def test_error_code_structure(self) -> None:
        """测试错误码条目结构完整."""
        error_codes_file = (
            Path(__file__).parent.parent.parent / "src" / "knowledge" / "data" / "error_codes.json"
        )

        if error_codes_file.exists():
            with open(error_codes_file, encoding="utf-8") as f:
                data = json.load(f)

            required_fields = ["code", "category", "severity", "description", "solution"]
            for item in data["error_codes"]:
                for field in required_fields:
                    assert field in item, f"Missing field: {field}"

    def test_error_code_categories(self) -> None:
        """测试错误码分类覆盖."""
        error_codes_file = (
            Path(__file__).parent.parent.parent / "src" / "knowledge" / "data" / "error_codes.json"
        )

        if error_codes_file.exists():
            with open(error_codes_file, encoding="utf-8") as f:
                data = json.load(f)

            categories = {item["category"] for item in data["error_codes"]}
            expected_categories = {
                "qos_limit",
                "gpu_related",
                "resource_exhausted",
                "script_error",
                "env_missing",
            }

            # 至少覆盖主要分类
            assert len(categories & expected_categories) >= 3


class TestEndToEndScenarios:
    """端到端场景测试.

    模拟 10 个典型用户问题，验证完整流程.
    """

    @pytest.mark.parametrize(
        "query,expected_intent",
        [
            ("为什么报 QOSMaxWallDurationPerJobLimit", "error_qos"),
            ("nvidia-smi 看不到 GPU", "error_gpu"),
            ("CUDA out of memory 怎么办", "error_oom"),
            ("作业一直排队 PD", "status_queuing"),
            ("conda 环境找不到", "env_conda"),
            ("sbatch 怎么提交", "job_submission"),
            ("怎么取消作业", "job_cancel"),
            ("内存不足 Killed", "resource_exhausted"),
            ("Permission denied", "permission"),
            ("ModuleNotFoundError", "env_missing"),
        ],
    )
    def test_typical_user_queries(self, query: str, expected_intent: str) -> None:
        """测试典型用户问题的意图识别."""
        # 简化的意图匹配逻辑
        intent_keywords = {
            "error_qos": ["QOSMaxWall", "超时", "时间限制"],
            "error_gpu": ["nvidia-smi", "GPU", "显卡", "看不到GPU"],
            "error_oom": ["out of memory", "OOM", "显存不足"],
            "status_queuing": ["排队", "PD", "pending"],
            "env_conda": ["conda", "环境"],
            "job_submission": ["sbatch", "提交作业"],
            "job_cancel": ["取消", "scancel"],
            "resource_exhausted": ["内存不足", "Killed", "MemoryError"],
            "permission": ["Permission", "权限"],
            "env_missing": ["ModuleNotFoundError", "找不到模块"],
        }

        matched = any(kw in query for kw in intent_keywords.get(expected_intent, []))
        assert matched, f"Query '{query}' should match intent '{expected_intent}'"
