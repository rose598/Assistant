"""/api/ask 边缘 case 测试 (第 2 周周五计划任务).

覆盖 plan 要求的鲁棒性边界: 空输入 / 纯标点 / 超长 / SQL 注入 / 表情符号.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    """模块级 TestClient."""
    return TestClient(app)


class TestAskEdgeCases:
    """问答端点边缘输入测试类."""

    def test_sql_injection(self, client: TestClient) -> None:
        # SQL 注入尝试应被当作普通 query 处理, 不报错不泄露
        payload = "'; DROP TABLE faq; --"
        r = client.post("/api/ask", json={"question": payload})
        assert r.status_code == 200
        assert r.json()["answer"]

    def test_union_injection(self, client: TestClient) -> None:
        r = client.post(
            "/api/ask",
            json={"question": "SELECT * FROM users UNION SELECT 1,2,3 --"},
        )
        assert r.status_code == 200

    def test_long_within_limit(self, client: TestClient) -> None:
        # 5000 字以内合法
        r = client.post("/api/ask", json={"question": "提交作业" * 1000})
        assert r.status_code == 200

    def test_too_long_exceeds(self, client: TestClient) -> None:
        # 超过 5000 字被 pydantic 拦截
        r = client.post("/api/ask", json={"question": "a" * 5001})
        assert r.status_code == 422

    def test_emoji_only(self, client: TestClient) -> None:
        r = client.post("/api/ask", json={"question": "😀🎉🚀"})
        assert r.status_code == 200
        assert r.json()["answer"]

    def test_punctuation_only(self, client: TestClient) -> None:
        r = client.post("/api/ask", json={"question": "。。。！！！？？"})
        assert r.status_code == 200

    def test_foreign_language(self, client: TestClient) -> None:
        # 无关语言也应友好返回
        r = client.post("/api/ask", json={"question": "hello world how are you"})
        assert r.status_code == 200
        assert r.json()["answer"]

    def test_newline_and_tabs(self, client: TestClient) -> None:
        r = client.post("/api/ask", json={"question": "CUDA\nout\t of  memory"})
        assert r.status_code == 200
