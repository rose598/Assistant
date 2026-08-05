"""部署测试 — staging 环境全流程验收.

模拟 staging 环境完整跑通用户使用全流程：
- 健康检查
- 基础问答
- 作业查询
- 作业诊断
- 脚本改写
- 推荐系统
- 端到端用户旅程
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

import pytest

# ============================================================
# Mock 全链路服务
# ============================================================


@dataclass
class MockStagingServer:
    """模拟 staging 环境的全链路服务."""

    sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    jobs_db: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    knowledge_base: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        """初始化数据."""
        # 知识库
        self.knowledge_base = [
            {
                "id": "faq-001",
                "category": "job_submission",
                "keywords": ["提交", "GPU", "sbatch"],
                "question": "如何提交 GPU 作业？",
                "answer": "使用 sbatch 命令提交作业脚本...",
            },
            {
                "id": "faq-002",
                "category": "error_diagnosis",
                "keywords": ["CUDA", "OOM", "显存"],
                "question": "CUDA out of memory 怎么办？",
                "answer": "减小 batch_size 或使用混合精度...",
            },
            {
                "id": "faq-003",
                "category": "error_diagnosis",
                "keywords": ["QOS", "时间限制", "WallDuration"],
                "question": "QOSMaxWallDurationPerJobLimit",
                "answer": "作业运行时间超过 QOS 限制...",
            },
        ]

        # 模拟作业数据
        self.jobs_db = {
            "scc123": [
                {
                    "job_id": "10001",
                    "job_name": "train_resnet",
                    "state": "COMPLETED",
                    "partition": "Students",
                    "exit_code": "0:0",
                },
                {
                    "job_id": "10002",
                    "job_name": "train_bert",
                    "state": "FAILED",
                    "partition": "Students",
                    "exit_code": "1:1",
                    "error_log": "CUDA out of memory. Tried to allocate 2.00 GiB",
                },
            ],
        }

    async def health_check(self) -> dict[str, Any]:
        """健康检查."""
        return {
            "status": "healthy",
            "version": "0.1.0",
            "services": {
                "database": "connected",
                "llm": "available",
                "ssh": "connected",
            },
        }

    async def ask(self, question: str, session_id: str | None = None) -> dict[str, Any]:
        """问答接口."""
        # 意图识别
        intent = self._identify_intent(question)

        # 知识库检索
        sources = self._search_knowledge(intent)

        # 生成回答
        answer = sources[0]["answer"] if sources else "抱歉，我暂时无法回答这个问题。"

        # 会话管理
        if session_id:
            if session_id not in self.sessions:
                self.sessions[session_id] = {"history": [], "created": time.time()}
            self.sessions[session_id]["history"].append({"role": "user", "content": question})
            self.sessions[session_id]["history"].append({"role": "assistant", "content": answer})

        return {
            "answer": answer,
            "confidence": 0.85 if sources else 0.3,
            "sources": [{"id": s["id"], "title": s["question"]} for s in sources],
            "intent": intent,
            "session_id": session_id,
        }

    async def get_jobs(self, user: str, limit: int = 10) -> dict[str, Any]:
        """作业查询."""
        jobs = self.jobs_db.get(user, [])
        return {
            "user": user,
            "jobs": jobs[:limit],
            "total": len(jobs),
        }

    async def diagnose_job(self, job_id: str) -> dict[str, Any]:
        """作业诊断."""
        for user_jobs in self.jobs_db.values():
            for job in user_jobs:
                if job["job_id"] == job_id:
                    if job["state"] == "FAILED":
                        error_log = job.get("error_log", "")
                        if "CUDA" in error_log and "memory" in error_log:
                            return {
                                "job_id": job_id,
                                "status": "FAILED",
                                "diagnosis": {
                                    "category": "resource_exhausted",
                                    "subcategory": "gpu_oom",
                                    "confidence": 0.92,
                                    "description": "GPU 显存溢出",
                                },
                                "suggestions": [
                                    {"action": "减小 batch_size", "priority": "high"},
                                    {"action": "使用混合精度", "priority": "medium"},
                                ],
                            }
                    return {
                        "job_id": job_id,
                        "status": job["state"],
                        "diagnosis": None,
                        "suggestions": [],
                    }
        return {"job_id": job_id, "status": "NOT_FOUND", "diagnosis": None, "suggestions": []}

    def _identify_intent(self, question: str) -> str:
        """意图识别."""
        if any(kw in question for kw in ["提交", "sbatch", "作业"]):
            return "job_submission"
        if any(kw in question for kw in ["错误", "报错", "失败", "怎么办"]):
            return "error_diagnosis"
        if any(kw in question for kw in ["排队", "状态", "squeue"]):
            return "job_status"
        return "general"

    def _search_knowledge(self, intent: str) -> list[dict[str, Any]]:
        """知识库检索."""
        return [item for item in self.knowledge_base if item["category"] == intent]


# ============================================================
# 全流程验收测试
# ============================================================


@pytest.fixture
def server() -> MockStagingServer:
    """创建 staging 服务器."""
    return MockStagingServer()


class TestHealthCheck:
    """健康检查."""

    @pytest.mark.asyncio
    async def test_health_endpoint(self, server: MockStagingServer) -> None:
        """健康检查端点正常."""
        result = await server.health_check()
        assert result["status"] == "healthy"
        assert result["version"] == "0.1.0"

    @pytest.mark.asyncio
    async def test_all_services_healthy(self, server: MockStagingServer) -> None:
        """所有服务健康."""
        result = await server.health_check()
        services = result["services"]
        assert services["database"] == "connected"
        assert services["llm"] == "available"
        assert services["ssh"] == "connected"


class TestBasicQA:
    """基础问答流程."""

    @pytest.mark.asyncio
    async def test_gpu_submission_question(self, server: MockStagingServer) -> None:
        """GPU 作业提交问答."""
        result = await server.ask("如何提交一个 GPU 作业？")
        assert result["answer"]
        assert result["confidence"] > 0.5
        assert result["intent"] == "job_submission"

    @pytest.mark.asyncio
    async def test_error_diagnosis_question(self, server: MockStagingServer) -> None:
        """错误诊断问答."""
        result = await server.ask("CUDA out of memory 怎么办？")
        assert result["answer"]
        assert result["intent"] == "error_diagnosis"
        assert result["confidence"] > 0.5

    @pytest.mark.asyncio
    async def test_unknown_question(self, server: MockStagingServer) -> None:
        """未知问题降级."""
        result = await server.ask("今天天气怎么样？")
        assert result["answer"]
        assert result["confidence"] < 0.5


class TestJobQuery:
    """作业查询流程."""

    @pytest.mark.asyncio
    async def test_query_existing_user(self, server: MockStagingServer) -> None:
        """查询已有用户作业."""
        result = await server.get_jobs("scc123")
        assert result["total"] == 2
        assert len(result["jobs"]) == 2

    @pytest.mark.asyncio
    async def test_query_nonexistent_user(self, server: MockStagingServer) -> None:
        """查询不存在用户."""
        result = await server.get_jobs("nonexistent")
        assert result["total"] == 0
        assert result["jobs"] == []

    @pytest.mark.asyncio
    async def test_query_with_limit(self, server: MockStagingServer) -> None:
        """限制返回数量."""
        result = await server.get_jobs("scc123", limit=1)
        assert len(result["jobs"]) == 1


class TestJobDiagnosis:
    """作业诊断流程."""

    @pytest.mark.asyncio
    async def test_diagnose_failed_job(self, server: MockStagingServer) -> None:
        """诊断失败作业."""
        result = await server.diagnose_job("10002")
        assert result["status"] == "FAILED"
        assert result["diagnosis"] is not None
        assert result["diagnosis"]["subcategory"] == "gpu_oom"
        assert len(result["suggestions"]) > 0

    @pytest.mark.asyncio
    async def test_diagnose_completed_job(self, server: MockStagingServer) -> None:
        """诊断成功作业."""
        result = await server.diagnose_job("10001")
        assert result["status"] == "COMPLETED"
        assert result["diagnosis"] is None

    @pytest.mark.asyncio
    async def test_diagnose_nonexistent_job(self, server: MockStagingServer) -> None:
        """诊断不存在作业."""
        result = await server.diagnose_job("99999")
        assert result["status"] == "NOT_FOUND"


class TestMultiTurnDialog:
    """多轮对话流程."""

    @pytest.mark.asyncio
    async def test_session_persistence(self, server: MockStagingServer) -> None:
        """会话持久化."""
        session_id = "test-session-001"

        # 第一轮
        await server.ask("如何提交作业？", session_id=session_id)
        assert session_id in server.sessions

        # 第二轮
        await server.ask("CUDA OOM 怎么办？", session_id=session_id)
        history = server.sessions[session_id]["history"]
        assert len(history) == 4  # 2 轮 × 2 (user + assistant)

    @pytest.mark.asyncio
    async def test_multiple_sessions_isolated(self, server: MockStagingServer) -> None:
        """多会话隔离."""
        await server.ask("问题1", session_id="session-A")
        await server.ask("问题2", session_id="session-B")

        assert "session-A" in server.sessions
        assert "session-B" in server.sessions
        assert len(server.sessions["session-A"]["history"]) == 2
        assert len(server.sessions["session-B"]["history"]) == 2


class TestEndToEndWorkflow:
    """端到端用户旅程."""

    @pytest.mark.asyncio
    async def test_full_user_journey(self, server: MockStagingServer) -> None:
        """完整用户旅程：健康检查 → 问答 → 查询 → 诊断."""
        # Step 1: 健康检查
        health = await server.health_check()
        assert health["status"] == "healthy"

        # Step 2: 用户提问
        qa_result = await server.ask("如何提交 GPU 作业？", session_id="journey-001")
        assert qa_result["answer"]
        assert qa_result["confidence"] > 0.5

        # Step 3: 查询作业
        jobs_result = await server.get_jobs("scc123")
        assert jobs_result["total"] > 0

        # Step 4: 诊断失败作业
        diagnose_result = await server.diagnose_job("10002")
        assert diagnose_result["status"] == "FAILED"
        assert diagnose_result["diagnosis"] is not None

        # Step 5: 继续提问
        follow_up = await server.ask("CUDA OOM 怎么解决？", session_id="journey-001")
        assert follow_up["answer"]

    @pytest.mark.asyncio
    async def test_error_flow(self, server: MockStagingServer) -> None:
        """错误流程：查询不存在的用户 → 查询不存在的作业."""
        # 查询不存在的用户
        jobs = await server.get_jobs("unknown_user")
        assert jobs["total"] == 0

        # 查询不存在的作业
        diagnose = await server.diagnose_job("99999")
        assert diagnose["status"] == "NOT_FOUND"

        # 提问降级
        qa = await server.ask("与平台无关的问题")
        assert qa["answer"]
        assert qa["confidence"] < 0.5


class TestDeploymentValidation:
    """部署验证."""

    @pytest.mark.asyncio
    async def test_response_time_acceptable(self, server: MockStagingServer) -> None:
        """响应时间可接受."""
        start = time.time()
        await server.ask("测试问题")
        elapsed = time.time() - start
        assert elapsed < 1.0, f"响应时间 {elapsed}s > 1s"

    @pytest.mark.asyncio
    async def test_concurrent_requests(self, server: MockStagingServer) -> None:
        """并发请求正常."""
        tasks = [server.ask(f"问题 {i}") for i in range(10)]
        results = await asyncio.gather(*tasks)
        assert all(r["answer"] for r in results)

    @pytest.mark.asyncio
    async def test_json_response_format(self, server: MockStagingServer) -> None:
        """JSON 响应格式正确."""
        result = await server.ask("测试")
        # 确保可以 JSON 序列化
        json_str = json.dumps(result, ensure_ascii=False)
        parsed = json.loads(json_str)
        assert "answer" in parsed
        assert "confidence" in parsed
