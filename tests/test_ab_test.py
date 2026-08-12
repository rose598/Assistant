"""A/B 测试框架（ab_test）单元测试.

覆盖:
- 基本计数与准确率统计。
- scorer 满意度维度。
- winner / improvement 判定（A 胜 / B 胜 / 平局 / 全错空）。
- 分支明细 breakdown、数量不匹配校验、空列表边界。
"""

from __future__ import annotations

import pytest

from src.ab_test import run_ab_test


def _pipeline(fixed: str) -> object:
    """构造一个恒定返回 ``fixed`` 的回答函数."""

    def _fn(_question: str) -> str:
        return fixed

    return _fn


def _answer_like(answer: object, expected: object) -> bool:
    """'正确'判定：回答包含预期答案关键词（含 'ok' 表示命中）."""
    text = str(answer)
    target = "ok"
    return target in text


class TestAbBasic:
    """基本计数与准确率."""

    def test_all_correct_both(self) -> None:
        questions = ["q1", "q2"]
        expected = ["e1", "e2"]
        # 两个分支都返回含 'ok' 的答案
        pipeline = _pipeline("这是 ok 答案")
        result = run_ab_test(
            questions,
            expected,
            pipeline,
            pipeline,
            judge=_answer_like,
        )
        assert result.total == 2
        assert result.correct_a == 2 and result.correct_b == 2
        assert result.accuracy_a == 1.0 and result.accuracy_b == 1.0
        assert result.winner == "tie"  # 非零且相等 -> 平局

    def test_b_better_than_a(self) -> None:
        questions = ["q1", "q2", "q3"]
        expected = ["e1", "e2", "e3"]
        a = _pipeline("错的回答")  # 全错
        b = _pipeline("ok 正确回答")  # 全对
        result = run_ab_test(questions, expected, a, b, judge=_answer_like)
        assert result.accuracy_a == 0.0
        assert result.accuracy_b == 1.0
        assert result.winner == "B"
        assert result.improvement == 1.0

    def test_partial(self) -> None:
        # 用不同命中逻辑模拟差异: A 对 3 中 1, B 对 3 中 2
        answers_a = ["ok", "bad", "bad"]
        answers_b = ["ok", "ok", "bad"]

        def mk(answers: list[str]) -> object:
            def _fn(q: str) -> str:
                idx = int(q[-1]) - 1
                return answers[idx]

            return _fn

        result = run_ab_test(
            ["q1", "q2", "q3"],
            ["e1", "e2", "e3"],
            mk(answers_a),
            mk(answers_b),
            judge=_answer_like,
        )
        assert result.correct_a == 1 and result.correct_b == 2
        assert result.winner == "B"


class TestAbScorer:
    """满意度分值维度."""

    def test_mean_score(self) -> None:
        def scorer(answer: object, expected: object) -> float:
            return 1.0 if "ok" in str(answer) else 0.0

        a = _pipeline("ok")
        b = _pipeline("bad")
        result = run_ab_test(
            ["q1", "q2"],
            ["e1", "e2"],
            a,
            b,
            judge=_answer_like,
            scorer=scorer,
        )
        assert result.mean_score_a == 1.0
        assert result.mean_score_b == 0.0

    def test_no_scorer_yields_zero(self) -> None:
        a = _pipeline("ok")
        b = _pipeline("ok")
        result = run_ab_test(["q1"], ["e1"], a, b, judge=_answer_like)
        assert result.mean_score_a == 0.0
        assert result.mean_score_b == 0.0


class TestAbEdgeCases:
    """边界与校验."""

    def test_mismatched_length_raises(self) -> None:
        with pytest.raises(ValueError):
            run_ab_test(["q1"], ["e1", "e2"], _pipeline("x"), _pipeline("y"), _answer_like)

    def test_empty_returns_zero_stats(self) -> None:
        result = run_ab_test([], [], _pipeline("x"), _pipeline("y"), _answer_like)
        assert result.total == 0
        assert result.accuracy_a == 0.0 and result.accuracy_b == 0.0
        assert result.winner is None
        assert result.improvement == 0.0

    def test_all_wrong_winner_none(self) -> None:
        a = _pipeline("bad")
        b = _pipeline("bad")
        result = run_ab_test(["q1"], ["e1"], a, b, judge=_answer_like)
        assert result.winner is None  # 全错且相等

    def test_breakdown_by_branch(self) -> None:
        a = _pipeline("ok")
        b = _pipeline("bad")
        result = run_ab_test(["q1", "q2"], ["e1", "e2"], a, b, judge=_answer_like)
        branch_a = result.breakdown("A")
        branch_b = result.breakdown("B")
        assert len(branch_a) == 2 and all(t.branch == "A" for t in branch_a)
        assert len(branch_b) == 2 and all(t.branch == "B" for t in branch_b)
        assert all(t.correct for t in branch_a)
        assert not any(t.correct for t in branch_b)

    def test_kwargs_pipeline_called_for_each_question(self) -> None:
        seen_a: list[str] = []
        seen_b: list[str] = []

        def spy_a(question: str) -> str:
            seen_a.append(question)
            return "ok"

        def spy_b(question: str) -> str:
            seen_b.append(question)
            return "ok"

        run_ab_test(["qa", "qb"], ["e1", "e2"], spy_a, spy_b, judge=_answer_like)
        # 每个分支都应对每题恰好调用一次
        assert seen_a == ["qa", "qb"]
        assert seen_b == ["qa", "qb"]
