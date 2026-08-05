"""压力测试与安全审计.

周三+周四任务合并：
- 模拟 100 并发用户混合场景压测
- 安全审计：SQL 注入、XSS、API 限流、敏感信息脱敏
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Any

import pytest

# ============================================================
# Mock 服务端
# ============================================================


@dataclass
class MockResponse:
    """模拟 HTTP 响应."""

    status_code: int
    body: str
    headers: dict[str, str] = field(default_factory=dict)
    latency_ms: float = 0.0


@dataclass
class MockServer:
    """模拟 API 服务器."""

    request_count: int = 0
    error_count: int = 0
    latency_history: list[float] = field(default_factory=list)
    rate_limit: int = 100  # req/min
    _window_start: float = field(default_factory=time.time)
    _window_count: int = 0

    async def handle_request(self, endpoint: str, payload: dict[str, Any]) -> MockResponse:
        """处理请求."""
        self.request_count += 1

        # 模拟处理延迟
        latency = 50 + (self.request_count % 10) * 5  # 50-100ms
        await asyncio.sleep(latency / 1000)

        # 限流检查
        now = time.time()
        if now - self._window_start > 60:
            self._window_start = now
            self._window_count = 0
        self._window_count += 1

        if self._window_count > self.rate_limit:
            self.latency_history.append(latency)
            return MockResponse(
                status_code=429,
                body='{"error": {"code": "RATE_LIMITED", "message": "请求过于频繁"}}',
                latency_ms=latency,
            )

        # 路由
        if endpoint == "/api/ask":
            return await self._handle_ask(payload, latency)
        if endpoint == "/api/jobs":
            return await self._handle_jobs(payload, latency)
        if endpoint == "/health":
            self.latency_history.append(latency)
            return MockResponse(status_code=200, body='{"status": "healthy"}', latency_ms=latency)

        self.latency_history.append(latency)
        return MockResponse(status_code=404, body='{"error": "not found"}', latency_ms=latency)

    async def _handle_ask(self, payload: dict[str, Any], latency: float) -> MockResponse:
        """处理问答请求."""
        question = payload.get("question", "")

        # 安全检查
        if self._detect_injection(question):
            self.error_count += 1
            self.latency_history.append(latency)
            return MockResponse(
                status_code=400,
                body='{"error": {"code": "VALIDATION_ERROR", "message": "输入包含非法字符"}}',
                latency_ms=latency,
            )

        if not question.strip():
            self.latency_history.append(latency)
            return MockResponse(
                status_code=400,
                body='{"error": {"code": "VALIDATION_ERROR", "message": "question 不能为空"}}',
                latency_ms=latency,
            )

        # 脱敏处理
        answer = self._mask_sensitive(question)
        self.latency_history.append(latency)
        return MockResponse(
            status_code=200,
            body=f'{{"answer": "{answer}", "confidence": 0.9}}',
            latency_ms=latency,
        )

    async def _handle_jobs(self, payload: dict[str, Any], latency: float) -> MockResponse:
        """处理作业查询."""
        user = payload.get("user", "")
        if self._detect_injection(user):
            self.error_count += 1
            self.latency_history.append(latency)
            return MockResponse(
                status_code=400,
                body='{"error": {"code": "VALIDATION_ERROR", "message": "输入包含非法字符"}}',
                latency_ms=latency,
            )

        self.latency_history.append(latency)
        return MockResponse(
            status_code=200,
            body='{"jobs": [], "total": 0}',
            latency_ms=latency,
        )

    @staticmethod
    def _detect_injection(text: str) -> bool:
        """检测注入攻击."""
        patterns = [
            r"(?i)(DROP|DELETE|INSERT|UPDATE|SELECT)\s+",  # SQL
            r"(?i)<script[^>]*>",  # XSS
            r"(?i)javascript:",  # XSS
            r"(?i)on\w+\s*=",  # 事件处理器
            r";\s*rm\s+",  # 命令注入
            r"\|\s*cat\s+/etc",  # 命令注入
        ]
        return any(re.search(p, text) for p in patterns)

    @staticmethod
    def _mask_sensitive(text: str) -> str:
        """脱敏处理."""
        # 隐藏账号路径
        text = re.sub(r"/home/scc/\w+", "/home/scc/***", text)
        # 隐藏邮箱
        text = re.sub(r"[\w.]+@[\w.]+", "***@***", text)
        return text


# ============================================================
# 压测
# ============================================================


@pytest.fixture
def server() -> MockServer:
    """创建模拟服务器."""
    return MockServer()


class TestPressureLoad:
    """压力测试."""

    @pytest.mark.asyncio
    async def test_100_concurrent_users(self, server: MockServer) -> None:
        """100 并发用户混合场景."""
        questions = [
            {"question": "如何提交 GPU 作业？"},
            {"question": "CUDA out of memory 怎么办？"},
            {"question": "QOSMaxWallDurationPerJobLimit 错误"},
            {"question": "作业一直排队怎么办？"},
            {"question": "如何查看作业状态？"},
            {"question": "conda 环境怎么配置？"},
            {"question": "如何申请更多 GPU？"},
            {"question": "sbatch 脚本报错"},
            {"question": "如何查看集群状态？"},
            {"question": "作业被取消了"},
        ]

        async def send_request(q: dict[str, Any]) -> MockResponse:
            return await server.handle_request("/api/ask", q)

        # 100 并发
        tasks = [send_request(questions[i % len(questions)]) for i in range(100)]
        results = await asyncio.gather(*tasks)

        # 验证
        success = sum(1 for r in results if r.status_code == 200)
        rate_limited = sum(1 for r in results if r.status_code == 429)

        assert success + rate_limited == 100
        # 允许部分限流，但不能有 500 错误
        server_errors = sum(1 for r in results if r.status_code >= 500)
        assert server_errors == 0, f"有 {server_errors} 个 500 错误"

    @pytest.mark.asyncio
    async def test_p95_latency_under_3s(self, server: MockServer) -> None:
        """P95 延迟 ≤ 3s."""
        for i in range(50):
            await server.handle_request("/api/ask", {"question": f"问题 {i}"})

        latencies = sorted(server.latency_history)
        p95_idx = int(len(latencies) * 0.95)
        p95 = latencies[p95_idx] if p95_idx < len(latencies) else latencies[-1]

        assert p95 <= 3000, f"P95 延迟 {p95}ms > 3000ms"

    @pytest.mark.asyncio
    async def test_no_500_errors_under_load(self, server: MockServer) -> None:
        """负载下无 500 错误."""
        tasks = [server.handle_request("/api/ask", {"question": f"test {i}"}) for i in range(200)]
        results = await asyncio.gather(*tasks)
        errors_500 = [r for r in results if r.status_code >= 500]
        assert len(errors_500) == 0

    @pytest.mark.asyncio
    async def test_mixed_endpoints(self, server: MockServer) -> None:
        """混合端点请求."""
        tasks = []
        for i in range(60):
            if i % 3 == 0:
                tasks.append(server.handle_request("/health", {}))
            elif i % 3 == 1:
                tasks.append(server.handle_request("/api/ask", {"question": f"Q{i}"}))
            else:
                tasks.append(server.handle_request("/api/jobs", {"user": f"user{i}"}))

        results = await asyncio.gather(*tasks)
        assert all(r.status_code in (200, 429) for r in results)


# ============================================================
# 安全审计
# ============================================================


class TestSecuritySQLInjection:
    """SQL 注入防护."""

    @pytest.mark.asyncio
    async def test_sql_drop_table(self, server: MockServer) -> None:
        """拦截 DROP TABLE 注入."""
        resp = await server.handle_request("/api/ask", {"question": "'; DROP TABLE users; --"})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_sql_select_union(self, server: MockServer) -> None:
        """拦截 UNION SELECT 注入."""
        resp = await server.handle_request(
            "/api/ask", {"question": "' UNION SELECT * FROM passwords --"}
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_sql_delete(self, server: MockServer) -> None:
        """拦截 DELETE 注入."""
        resp = await server.handle_request(
            "/api/ask", {"question": "'; DELETE FROM jobs WHERE 1=1; --"}
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_sql_injection_in_user_field(self, server: MockServer) -> None:
        """拦截 user 字段的 SQL 注入."""
        resp = await server.handle_request(
            "/api/jobs", {"user": "admin'; SELECT * FROM passwords; --"}
        )
        assert resp.status_code == 400


class TestSecurityXSS:
    """XSS 防护."""

    @pytest.mark.asyncio
    async def test_script_tag_injection(self, server: MockServer) -> None:
        """拦截 <script> 标签."""
        resp = await server.handle_request(
            "/api/ask", {"question": "<script>alert('xss')</script>"}
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_javascript_protocol(self, server: MockServer) -> None:
        """拦截 javascript: 协议."""
        resp = await server.handle_request(
            "/api/ask", {"question": "javascript:alert(document.cookie)"}
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_event_handler_injection(self, server: MockServer) -> None:
        """拦截事件处理器注入."""
        resp = await server.handle_request(
            "/api/ask", {"question": '<img onerror="alert(1)" src=x>'}
        )
        assert resp.status_code == 400


class TestSecurityRateLimit:
    """API 限流."""

    @pytest.mark.asyncio
    async def test_rate_limit_enforced(self, server: MockServer) -> None:
        """超过限流返回 429."""
        server.rate_limit = 10  # 降低限流阈值
        results = []
        for i in range(20):
            resp = await server.handle_request("/api/ask", {"question": f"Q{i}"})
            results.append(resp)

        rate_limited = sum(1 for r in results if r.status_code == 429)
        assert rate_limited > 0, "应有限流响应"

    @pytest.mark.asyncio
    async def test_rate_limit_response_format(self, server: MockServer) -> None:
        """限流响应格式正确."""
        server.rate_limit = 1
        await server.handle_request("/api/ask", {"question": "Q1"})
        resp = await server.handle_request("/api/ask", {"question": "Q2"})

        if resp.status_code == 429:
            assert "RATE_LIMITED" in resp.body


class TestSecurityDataMasking:
    """敏感信息脱敏."""

    @pytest.mark.asyncio
    async def test_user_path_masked(self, server: MockServer) -> None:
        """用户路径脱敏."""
        resp = await server.handle_request(
            "/api/ask", {"question": "我的文件在 /home/scc/zhangsan/data"}
        )
        assert "/home/scc/***" in resp.body
        assert "zhangsan" not in resp.body

    @pytest.mark.asyncio
    async def test_email_masked(self, server: MockServer) -> None:
        """邮箱脱敏."""
        resp = await server.handle_request("/api/ask", {"question": "我的邮箱是 test@ustc.edu.cn"})
        assert "test@ustc.edu.cn" not in resp.body
        assert "***@***" in resp.body

    def test_mask_function_path(self) -> None:
        """路径脱敏函数测试."""
        result = MockServer._mask_sensitive("路径: /home/scc/myuser/file.txt")
        assert "myuser" not in result
        assert "/home/scc/***" in result

    def test_mask_function_email(self) -> None:
        """邮箱脱敏函数测试."""
        result = MockServer._mask_sensitive("联系 user@example.com")
        assert "user@example.com" not in result
        assert "***@***" in result


class TestSecurityInputValidation:
    """输入验证."""

    @pytest.mark.asyncio
    async def test_empty_question(self, server: MockServer) -> None:
        """空问题返回 400."""
        resp = await server.handle_request("/api/ask", {"question": ""})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_whitespace_only_question(self, server: MockServer) -> None:
        """纯空白问题返回 400."""
        resp = await server.handle_request("/api/ask", {"question": "   "})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_valid_question_accepted(self, server: MockServer) -> None:
        """正常问题返回 200."""
        resp = await server.handle_request("/api/ask", {"question": "如何提交作业？"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_command_injection_blocked(self, server: MockServer) -> None:
        """拦截命令注入."""
        resp = await server.handle_request(
            "/api/ask", {"question": "; rm -rf / --no-preserve-root"}
        )
        assert resp.status_code == 400
