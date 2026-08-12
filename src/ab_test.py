"""A/B 测试框架（对比纯关键词 vs LLM 增强）。

第 3 周周三/周五交付物（A 职责）：为"纯关键词匹配"与"LLM 增强"两条问答通道
提供可复现的对照实验，输出各分支的准确率与满意度，供方案选型决策。

设计要点（不绑定具体模型，保持通用）：
- ``pipeline_a`` / ``pipeline_b``：两条通道的``(question) -> answer``打分函数，
  由调用方注入（可接知识库关键词、可接真实/ mock LLM）。
- ``judge``：判定单条回答是否正确``(answer, expected) -> bool``；
  ``scorer``（可选）：给回答打 0~1 满意度``(answer, expected) -> float``。
- 对每组 (pipeline, question, expected) 各跑一遍，统计准确率与平均分，
  并给出胜出方与相对提升。
- 纯同步、无 IO，便于在测试与压测中稳定复现。

典型用法：用一个含标准答案的题目集，A = 关键词通道，B = LLM 通道，
对比两条通道的 accuracy_a / accuracy_b 即得结论。
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

Answer = Any
JudgeFn = Callable[[Answer, Answer], bool]
ScorerFn = Callable[[Answer, Answer], float]
PipelineFn = Callable[[str], Answer]


@dataclass
class ABTrial:
    """单题在某个分支下的结果."""

    branch: str
    question: str
    expected: Answer
    predicted: Answer
    correct: bool
    score: float | None = None


@dataclass
class ABResult:
    """一次 A/B 实验的汇总."""

    total: int = 0
    correct_a: int = 0
    correct_b: int = 0
    total_score_a: float = 0.0
    total_score_b: float = 0.0
    outcomes: list[ABTrial] = field(default_factory=list)

    @property
    def accuracy_a(self) -> float:
        return _ratio(self.correct_a, self.total)

    @property
    def accuracy_b(self) -> float:
        return _ratio(self.correct_b, self.total)

    @property
    def mean_score_a(self) -> float:
        return _mean(self.total_score_a, self.total)

    @property
    def mean_score_b(self) -> float:
        return _mean(self.total_score_b, self.total)

    @property
    def winner(self) -> str | None:
        """按准确率判定胜出方；无意义时返回 None."""
        if self.total == 0:
            return None
        if self.accuracy_a == self.accuracy_b:
            return None if self.accuracy_a == 0.0 else "tie"
        return "A" if self.accuracy_a > self.accuracy_b else "B"

    @property
    def improvement(self) -> float:
        """胜出方相对另一方的准确率绝对提升（0~1），用于量化收益."""
        return abs(self.accuracy_a - self.accuracy_b)

    def breakdown(self, branch: str) -> list[ABTrial]:
        """按分支筛选明细."""
        return [t for t in self.outcomes if t.branch == branch]


def _ratio(part: int, total: int) -> float:
    return round(part / total, 4) if total else 0.0


def _mean(total: float, n: int) -> float:
    return round(total / n, 4) if n else 0.0


def run_ab_test(
    questions: list[str],
    expected: list[Answer],
    pipeline_a: PipelineFn,
    pipeline_b: PipelineFn,
    judge: JudgeFn,
    scorer: ScorerFn | None = None,
) -> ABResult:
    """跑一次对照实验.

    Args:
        questions: 题目列表。
        expected: 与题目一一对应的标准答案。
        pipeline_a: 分支 A（如纯关键词）回答函数。
        pipeline_b: 分支 B（如 LLM 增强）回答函数。
        judge: 判定回答是否正确。
        scorer: 可选，给出 0~1 满意度分（用于"用户满意度"维度）。

    Returns:
        ``ABResult`` 汇总（accuracy / mean_score / winner / improvement / 明细）。
    """
    if len(questions) != len(expected):
        raise ValueError(f"questions 与 expected 数量不一致: {len(questions)} vs {len(expected)}")

    result = ABResult(total=len(questions))
    for question, exp in zip(questions, expected, strict=False):
        answer_a = pipeline_a(question)
        answer_b = pipeline_b(question)

        trial_a = ABTrial(
            branch="A",
            question=question,
            expected=exp,
            predicted=answer_a,
            correct=bool(judge(answer_a, exp)),
        )
        trial_b = ABTrial(
            branch="B",
            question=question,
            expected=exp,
            predicted=answer_b,
            correct=bool(judge(answer_b, exp)),
        )
        if scorer is not None:
            trial_a.score = float(scorer(answer_a, exp))
            trial_b.score = float(scorer(answer_b, exp))

        result.outcomes.append(trial_a)
        result.outcomes.append(trial_b)
        if trial_a.correct:
            result.correct_a += 1
        if trial_b.correct:
            result.correct_b += 1
        if trial_a.score is not None:
            result.total_score_a += trial_a.score
        if trial_b.score is not None:
            result.total_score_b += trial_b.score
    return result


PipelineFnAsync = Callable[[str], Awaitable[Answer] | Answer]


ProgressFn = Callable[[int, int], None]


async def run_ab_test_async(
    questions: list[str],
    expected: list[Answer],
    pipeline_a: PipelineFnAsync,
    pipeline_b: PipelineFnAsync,
    judge: JudgeFn,
    scorer: ScorerFn | None = None,
    progress: ProgressFn | None = None,
) -> ABResult:
    """异步版对照实验：支持 async 或同步的 pipeline（如真实 async LLM）。

    与 ``run_ab_test`` 返回相同的 ``ABResult`` 结构。pipeline 可为同步或异步，
    内部用 ``inspect.isawaitable`` 自动 await。
    ``progress(done, total)`` 可选回调，每题后调用一次，供实时进度显示。
    """
    if len(questions) != len(expected):
        raise ValueError(f"questions 与 expected 数量不一致: {len(questions)} vs {len(expected)}")

    async def _invoke(fn: PipelineFnAsync, q: str) -> Answer:
        result = fn(q)
        if inspect.isawaitable(result):
            return await result
        return result

    result = ABResult(total=len(questions))
    for idx, (question, exp) in enumerate(zip(questions, expected, strict=False), start=1):
        answer_a = await _invoke(pipeline_a, question)
        answer_b = await _invoke(pipeline_b, question)

        trial_a = ABTrial(
            branch="A", question=question, expected=exp, predicted=answer_a,
            correct=bool(judge(answer_a, exp)),
        )
        trial_b = ABTrial(
            branch="B", question=question, expected=exp, predicted=answer_b,
            correct=bool(judge(answer_b, exp)),
        )
        if scorer is not None:
            trial_a.score = float(scorer(answer_a, exp))
            trial_b.score = float(scorer(answer_b, exp))

        result.outcomes.append(trial_a)
        result.outcomes.append(trial_b)
        if trial_a.correct:
            result.correct_a += 1
        if trial_b.correct:
            result.correct_b += 1
        if trial_a.score is not None:
            result.total_score_a += trial_a.score
        if trial_b.score is not None:
            result.total_score_b += trial_b.score
        if progress is not None:
            progress(idx, len(questions))
    return result


__all__ = ["ABResult", "ABTrial", "run_ab_test", "run_ab_test_async"]
