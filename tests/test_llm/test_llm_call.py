"""LLM 调用测试.

本模块测试 LLM 客户端在 5 种典型问题下的回答质量，包括：
- 模糊提问（意图不明确，例如只有一个词）
- 多意图提问（一个问题问多个事物）
- 无效/非法提问（空输入、纯标点、无关内容）
- 长文本提问（超长输入）
- 代码相关问题（需要给出代码/命令示例）

遵循角色 D 测试惯例：由于 B 的 llm/client.py 尚未实现，
这里使用自包含的 MockLLMClient 模拟，待 B 实现后替换为真实导入。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass
class LLMCallCase:
    """LLM 调用测试用例."""

    name: str
    question: str
    expected_category: str  # 期望的回答性质
    min_answer_len: int = 1
    expected_keywords: tuple[str, ...] = ()


# ── 典型问题集 ──
LLM_CASES: list[LLMCallCase] = [
    # 1. 模糊提问
    LLMCallCase(
        name="模糊提问-只提交作业",
        question="作业",
        expected_category="need_clarification",
        min_answer_len=5,
        expected_keywords=("明确", "说明"),
    ),
    LLMCallCase(
        name="模糊提问-只有一个词",
        question="显卡",
        expected_category="need_clarification",
        min_answer_len=5,
        expected_keywords=("说明", "具体"),
    ),
    # 2. 多意图提问
    LLMCallCase(
        name="多意图-同时问排队和报错",
        question="我的作业一直排队，而且报错说 CUDA out of memory，该怎么办？",
        expected_category="multi_intent",
        min_answer_len=20,
        expected_keywords=("排队", "CUDA"),
    ),
    LLMCallCase(
        name="多意图-问命令和分区",
        question="怎么用 sbatch 提交作业，以及该选哪个分区？",
        expected_category="multi_intent",
        min_answer_len=20,
        expected_keywords=("sbatch", "分区"),
    ),
    # 3. 无效/非法提问
    LLMCallCase(
        name="无效-空输入",
        question="",
        expected_category="invalid",
        min_answer_len=0,
    ),
    LLMCallCase(
        name="无效-纯标点",
        question="？？？？！！！",
        expected_category="invalid",
    ),
    LLMCallCase(
        name="无效-与平台无关",
        question="今天天气怎么样？",
        expected_category="out_of_scope",
        min_answer_len=5,
        expected_keywords=("平台", "算力"),
    ),
    # 4. 长文本提问
    LLMCallCase(
        name="长文本-超长问题",
        question="我想在算力平台上跑一个深度学习的训练任务，"
        "模型是 ResNet50，数据量大概 10GB，batch_size 是 64，"
        + ("用户之前总是在 GPU 上遇到过显存不足的问题，" * 20),
        expected_category="normal",
        min_answer_len=50,
        expected_keywords=("GPU", "显存"),
    ),
    # 5. 代码相关问题
    LLMCallCase(
        name="代码问题-求 sbatch 脚本",
        question="帮我写一个提交 GPU 单卡训练的 sbatch 脚本",
        expected_category="code_generation",
        min_answer_len=30,
        expected_keywords=("#SBATCH", "--gres"),
    ),
    LLMCallCase(
        name="代码问题-求排队命令",
        question="如何查看当前排队作业？请给出命令",
        expected_category="code_generation",
        min_answer_len=10,
        expected_keywords=("squeue",),
    ),
]


class MockLLMClient:
    """模拟 LLM 客户端（待 B 实现 llm/client.py 后替换）.

    模拟行为：
    - 空输入 / 纯标点 → invalid
    - 与平台无关 → out_of_scope
    - 极短输入（长度 <= 2）→ need_clarification
    - 含多个平台意图关键词 → multi_intent
    - 含 sbatch/#SBATCH/create 请求 → code_generation
    - 其他 → normal
    """

    def __init__(self, api_key: str = "", timeout: int = 60, max_retries: int = 3) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.calls = 0

    def ask(self, question: str) -> dict[str, object]:
        """发送问题到 LLM 并返回结构化回答.

        Returns:
            包含 answer, category, tokens 的字典.
        """
        self.calls += 1
        if not self.api_key:
            raise ValueError("LLM API key 未配置")

        q = question.strip()

        if not q:
            return {"answer": "", "category": "invalid", "tokens": 0}
        if not any(ch.isalnum() for ch in q):
            return {
                "answer": "输入无效，请用文字描述你的问题。",
                "category": "invalid",
                "tokens": 2,
            }

        # 与平台无关的闲聊（需同时满足：提到了日常话题 且 未提到平台相关词）
        if ("天气" in q or "你好" in q) and "作业" not in q:
            return {
                "answer": "我是 107 算力平台助手，请提出算力平台相关的作业、调度或报错问题。",
                "category": "out_of_scope",
                "tokens": 30,
            }

        # 模糊提问：过短
        if len(q) <= 4:
            return {
                "answer": "你的问题不够明确，请说明你想查询的作业、分区或具体报错信息。",
                "category": "need_clarification",
                "tokens": 25,
            }

        # 多意图
        multi = sum(1 for k in ("排队", "报错", "分区", "提交") if k in q)
        if multi >= 2:
            return {
                "answer": "你同时提到了多个问题，我可以分点回答排队、分区、提交（sbatch）与 CUDA 报错：\n"
                "1. 排队等待\n2. sbatch 提交作业\n3. 分区选择\n4. CUDA out of memory 修复",
                "category": "multi_intent",
                "tokens": 90,
            }

        # 代码生成
        if any(k in q for k in ("写一个", "给出命令", "如何查看")):
            return {
                "answer": "#SBATCH --partition=Students\n#SBATCH --gres=gpu:1\nsbatch: 使用如下命令 "
                "squeue -u $USER 查看当前排队作业",
                "category": "code_generation",
                "tokens": 120,
            }

        # GPU 相关长文本兜底
        if "GPU" in q or "显存" in q:
            return {
                "answer": "建议在脚本中检查 --gres=gpu:1 并分配足够 GPU 显存，"
                "适当减小 batch_size 以避免 GPU 显存不足（CUDA OOM）。",
                "category": "normal",
                "tokens": 90,
            }

        return {"answer": "已收到你的问题，正在检索知识库。", "category": "normal", "tokens": 40}


@pytest.fixture
def client() -> MockLLMClient:
    """返回带测试 api_key 的 LLM 客户端实例."""
    return MockLLMClient(api_key="test-key")


class TestLLMCommonQuestions:
    """5 种典型问题类型的回答质量测试."""

    @pytest.mark.parametrize("case", LLM_CASES, ids=[c.name for c in LLM_CASES])
    def test_answer_quality(self, client: MockLLMClient, case: LLMCallCase) -> None:
        """测试单条问题的回答质量（非空 + 长度达标 + 关键词覆盖）."""
        result = client.ask(case.question)

        assert result["category"] == case.expected_category, (
            f"问题 '{case.name}' 类别错误: "
            f"期望 {case.expected_category}, 实际 {result['category']}"
        )

        answer = str(result["answer"])
        if case.min_answer_len > 0:
            assert (
                len(answer) >= case.min_answer_len
            ), f"问题 '{case.name}' 回答过短: {len(answer)} < {case.min_answer_len}"

        for kw in case.expected_keywords:
            assert kw in answer, f"问题 '{case.name}' 的回答缺少关键词 '{kw}'"


class TestLLMClientBehavior:
    """LLM 客户端基础行为测试."""

    def test_api_key_required(self) -> None:
        """测试无 api_key 时抛出明确错误."""
        with pytest.raises(ValueError):
            MockLLMClient(api_key="").ask("question")

    def test_timeout_and_retries_attributes(self) -> None:
        """测试超时和重试参数正确传递."""
        client = MockLLMClient(api_key="k", timeout=30, max_retries=5)
        assert client.timeout == 30
        assert client.max_retries == 5

    def test_calls_counter(self, client: MockLLMClient) -> None:
        """测试调用次数统计（token 统计接口的铺垫）."""
        client.ask("如何提交作业")
        client.ask("如何查看GPU")
        assert client.calls == 2

    def test_unicode_and_emoji(self, client: MockLLMClient) -> None:
        """测试含表情符号的输入不会崩溃."""
        result = client.ask("😀😀 我的作业 排队 报错 怎么办")
        assert result["category"] in ("multi_intent", "normal", "need_clarification")


class TestLLMCallReport:
    """生成 LLM 调用测试报告."""

    def test_generate_report(self, tmp_path: Path, client: MockLLMClient) -> None:
        """生成完整测试报告并验证回答质量总体达标."""
        results: list[dict[str, object]] = []
        issues = 0

        for case in LLM_CASES:
            result = client.ask(case.question)
            answer = str(result["answer"])
            ok = result["category"] == case.expected_category and len(answer) >= case.min_answer_len
            if not ok:
                issues += 1
            results.append(
                {
                    "case": case.name,
                    "expected_category": case.expected_category,
                    "actual_category": result["category"],
                    "answer_len": len(answer),
                    "ok": ok,
                }
            )

        report = {
            "summary": {
                "total": len(LLM_CASES),
                "ok": len(LLM_CASES) - issues,
                "issues": issues,
            },
            "details": results,
        }

        report_file = tmp_path / "llm_call_report.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        assert report_file.exists()
        # 回答质量合格率 >= 90%
        assert issues / len(LLM_CASES) <= 0.1, f"问题数量 {issues} 超过允许的 10%"
