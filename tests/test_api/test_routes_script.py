"""/api/script 端点集成测试（第 5 周，A 侧；TestClient 全链路）.

覆盖：无状态工具端点、改写六步管线 HTTP 全链路、404/422 边界、
回退、导出下载头、删除。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.main import app

SCRIPT = """#!/bin/bash
#SBATCH -J train
#SBATCH -p Students
#SBATCH -t 04:00:00
python train.py
"""


@pytest.fixture(scope="module")
def client() -> TestClient:
    """模块级 TestClient（共享 app 单例）."""
    return TestClient(app)


class TestScriptStatelessEndpoints:
    """无状态工具端点."""

    def test_parse(self, client: TestClient) -> None:
        r = client.post("/api/script/parse", json={"script": SCRIPT})
        assert r.status_code == 200
        body = r.json()
        assert body["fields"]["p"] == "Students"
        assert body["fields"]["J"] == "train"

    def test_templates(self, client: TestClient) -> None:
        r = client.get("/api/script/templates")
        assert r.status_code == 200
        assert "gpu_single" in r.json()["templates"]

    def test_generate_ok(self, client: TestClient) -> None:
        r = client.post(
            "/api/script/generate",
            json={"template_name": "minimal_cpu", "overrides": {"mem": "8G"}},
        )
        assert r.status_code == 200
        assert "#SBATCH --mem=8G" in r.json()["script"]

    def test_generate_unknown_template_422(self, client: TestClient) -> None:
        r = client.post("/api/script/generate", json={"template_name": "nope"})
        assert r.status_code == 422
        assert "Unknown template" in r.json()["detail"]

    def test_suggest(self, client: TestClient) -> None:
        r = client.post("/api/script/suggest", json={"fields": {"gres": "gpu:1"}})
        assert r.status_code == 200
        body = r.json()
        assert body["suggestions"]["qos"] == "qos_stu_default"
        assert body["explanation"]


class TestScriptRewriteFlowEndpoints:
    """改写六步管线 HTTP 全链路."""

    def test_full_flow(self, client: TestClient) -> None:
        sid = "api-full"
        r = client.post("/api/script/rewrite/start", json={"session_id": sid, "script": SCRIPT})
        assert r.status_code == 200
        assert r.json()["dialog_state"] == "identify"

        r = client.post(f"/api/script/rewrite/{sid}/identify", json={"changes": {"partition": "GPU"}})
        assert r.json()["dialog_state"] == "collect"

        r = client.post(
            f"/api/script/rewrite/{sid}/collect", json={"field": "time", "value": "08:00:00"}
        )
        assert r.json()["changes"] == {"partition": "GPU", "time": "08:00:00"}

        r = client.post(f"/api/script/rewrite/{sid}/confirm")
        body = r.json()
        assert "#SBATCH -p GPU" in body["modified_script"]
        assert ["#SBATCH -p Students", "#SBATCH -p GPU"] in body["diff_summary"]["replaced"]
        assert ["#SBATCH -t 04:00:00", "#SBATCH -t 08:00:00"] in body["diff_summary"]["replaced"]

        r = client.post(f"/api/script/rewrite/{sid}/apply")
        assert r.json()["dialog_state"] == "apply"

        r = client.post(f"/api/script/rewrite/{sid}/finish")
        assert r.json()["dialog_state"] == "done"

    def test_status_unknown_session_404(self, client: TestClient) -> None:
        r = client.get("/api/script/rewrite/ghost/status")
        assert r.status_code == 404

    def test_start_empty_session_id_422(self, client: TestClient) -> None:
        r = client.post("/api/script/rewrite/start", json={"session_id": "  ", "script": SCRIPT})
        assert r.status_code == 422

    def test_rollback_via_http(self, client: TestClient) -> None:
        sid = "api-rollback"
        client.post("/api/script/rewrite/start", json={"session_id": sid, "script": SCRIPT})
        client.post(f"/api/script/rewrite/{sid}/identify", json={"changes": {"partition": "GPU"}})
        client.post(f"/api/script/rewrite/{sid}/confirm")
        r = client.post(f"/api/script/rewrite/{sid}/rollback")
        body = r.json()
        assert body["dialog_state"] == "collect"
        assert body["has_modified"] is False
        assert body["consistent"] is True

    def test_export_download_headers(self, client: TestClient) -> None:
        sid = "api-export"
        client.post("/api/script/rewrite/start", json={"session_id": sid, "script": SCRIPT})
        client.post(f"/api/script/rewrite/{sid}/identify", json={"changes": {"partition": "GPU"}})
        client.post(f"/api/script/rewrite/{sid}/confirm")
        r = client.get(f"/api/script/rewrite/{sid}/export")
        assert r.status_code == 200
        assert "train.sbatch" in r.headers["content-disposition"]
        assert "#SBATCH -p GPU" in r.text

    def test_delete_then_404(self, client: TestClient) -> None:
        sid = "api-delete"
        client.post("/api/script/rewrite/start", json={"session_id": sid, "script": SCRIPT})
        r = client.delete(f"/api/script/rewrite/{sid}")
        assert r.status_code == 204
        assert client.get(f"/api/script/rewrite/{sid}/status").status_code == 404
