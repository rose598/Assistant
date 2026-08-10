"""FastAPI API 端点测试.

覆盖计划第 2 周 API 验收:
- /health 健康检查
- /api/ask 问答(命中/空串/无关)
- /api/jobs/{user} 作业列表
- /api/jobs/{job_id}/diagnose 诊断(失败/成功/不存在/非法 ID)
- 前端静态资源可访问
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    """模块级 TestClient."""
    return TestClient(app)


class TestHealth:
    """健康检查测试类."""

    def test_health(self, client: TestClient) -> None:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


class TestAsk:
    """问答端点测试类."""

    def test_ask_hits_knowledge(self, client: TestClient) -> None:
        r = client.post("/api/ask", json={"question": "CUDA out of memory"})
        assert r.status_code == 200
        j = r.json()
        assert j["answer"]
        assert j["intent"]["primary"]
        assert j["matched"] is not None

    def test_ask_empty(self, client: TestClient) -> None:
        # 空串被 pydantic 拦截
        r = client.post("/api/ask", json={"question": ""})
        assert r.status_code == 422

    def test_ask_whitespace_only(self, client: TestClient) -> None:
        # 纯空格即使过 pydantic, 端点也友好处理
        r = client.post("/api/ask", json={"question": "   "})
        assert r.status_code in (200, 422)

    def test_ask_unknown_query(self, client: TestClient) -> None:
        r = client.post("/api/ask", json={"question": "今天中午吃什么"})
        assert r.status_code == 200
        assert len(r.json()["answer"]) > 0


class TestJobsList:
    """作业列表端点测试类."""

    def test_list_jobs(self, client: TestClient) -> None:
        r = client.get("/api/jobs/pb25071364")
        assert r.status_code == 200
        jobs = r.json()
        assert isinstance(jobs, list)
        assert len(jobs) > 0
        assert jobs[0]["job_id"]


class TestDiagnose:
    """作业诊断端点测试类."""

    def test_diagnose_failed_job(self, client: TestClient) -> None:
        # 1001 = QOS 运行时间受限
        r = client.get("/api/jobs/1001/diagnose")
        assert r.status_code == 200
        j = r.json()
        assert j["diagnosis"]["is_failed"] is True
        assert j["diagnosis"]["faq_id"] == "faq-001"
        assert j["diagnosis"]["advice"]
        assert j["data_source"] in ("mock", "ssh")

    def test_diagnose_oom_job(self, client: TestClient) -> None:
        # 1003 = GPU OOM
        r = client.get("/api/jobs/1003/diagnose")
        assert r.status_code == 200
        assert r.json()["diagnosis"]["category"] == "oom"

    def test_diagnose_not_found(self, client: TestClient) -> None:
        r = client.get("/api/jobs/999999/diagnose")
        assert r.status_code == 404

    def test_diagnose_invalid_id(self, client: TestClient) -> None:
        r = client.get("/api/jobs/abc/diagnose")
        assert r.status_code in (404, 422)


class TestFrontend:
    """前端静态资源测试类."""

    def test_index(self, client: TestClient) -> None:
        r = client.get("/")
        assert r.status_code == 200
        assert "107-Agent" in r.text

    def test_static_assets(self, client: TestClient) -> None:
        assert client.get("/scripts.js").status_code == 200
        assert client.get("/style.css").status_code == 200

    def test_api_not_shadowed(self, client: TestClient) -> None:
        # 静态挂载不应遮蔽 API
        assert client.post("/api/ask", json={"question": "如何提交作业"}).status_code == 200
