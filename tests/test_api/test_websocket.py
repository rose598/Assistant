"""WebSocket 实时对话端点测试 (第 2 周周四计划任务)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    """模块级 TestClient."""
    return TestClient(app)


class TestWebSocketAsk:
    """WebSocket 问答测试类."""

    def test_single_round(self, client: TestClient) -> None:
        with client.websocket_connect("/ws/ask") as ws:
            ws.send_text("CUDA out of memory")
            data = ws.receive_json()
            assert data["answer"]
            assert data["primary_intent"]

    def test_multi_round(self, client: TestClient) -> None:
        # 同一连接多轮, 验证连接保持
        with client.websocket_connect("/ws/ask") as ws:
            ws.send_text("如何提交作业")
            r1 = ws.receive_json()
            assert r1["answer"]
            ws.send_text("作业一直排队")
            r2 = ws.receive_json()
            assert r2["answer"]

    def test_empty_question(self, client: TestClient) -> None:
        with client.websocket_connect("/ws/ask") as ws:
            ws.send_text("   ")
            data = ws.receive_json()
            assert data["error"] == "问题不能为空"

    def test_long_question(self, client: TestClient) -> None:
        with client.websocket_connect("/ws/ask") as ws:
            ws.send_text("a" * 6000)
            data = ws.receive_json()
            assert data["error"] == "问题过长"
