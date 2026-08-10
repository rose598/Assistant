"""用户反馈收集端点测试 (第 2 周周四计划任务)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    """模块级 TestClient."""
    return TestClient(app)


class TestFeedbackSubmit:
    """反馈提交端点测试类."""

    def test_submit_useful(self, client: TestClient) -> None:
        r = client.post("/api/feedback", json={"useful": 1, "question": "如何提交作业"})
        assert r.status_code == 200
        assert r.json()["recorded"] is True

    def test_submit_useless(self, client: TestClient) -> None:
        r = client.post("/api/feedback", json={"useful": 0, "answer": "无用回复"})
        assert r.status_code == 200

    def test_submit_invalid_useful(self, client: TestClient) -> None:
        # useful 必须为 0 或 1
        r = client.post("/api/feedback", json={"useful": 5})
        assert r.status_code == 422

    def test_submit_missing_field(self, client: TestClient) -> None:
        r = client.post("/api/feedback", json={})
        assert r.status_code == 422

    def test_submit_no_extra_content(self, client: TestClient) -> None:
        # 只有 useful, 无上下文也允许
        r = client.post("/api/feedback", json={"useful": 1})
        assert r.status_code == 200


class TestFeedbackStats:
    """反馈统计端点测试类."""

    def test_stats_empty_or_ok(self, client: TestClient) -> None:
        r = client.get("/api/feedback/stats")
        assert r.status_code == 200
        j = r.json()
        assert "total" in j and "useful" in j and "useless" in j and "useful_rate" in j
