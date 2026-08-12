"""Mock LLM 客户端单元测试.

验证无需端点即可运行的确定性回复、关键词分支、统计累加与工厂降级。
"""

from __future__ import annotations

import pytest

from src.config import Config
from src.llm.mock_llm import MockLLMClient, create_llm_client


class TestMockLLMClient:
    """Mock 客户端核心行为。"""

    @pytest.mark.asyncio
    async def test_always_available(self) -> None:
        client = MockLLMClient()
        assert client.available is True

    @pytest.mark.asyncio
    async def test_oom_keyword_reply(self) -> None:
        client = MockLLMClient()
        resp = await client.complete([{"role": "user", "content": "我的作业 out of memory 了"}])
        assert "内存" in resp.text or "OOM" in resp.text

    @pytest.mark.asyncio
    async def test_queue_keyword_reply(self) -> None:
        client = MockLLMClient()
        resp = await client.complete([{"role": "user", "content": "作业一直排队"}])
        assert "排队" in resp.text

    @pytest.mark.asyncio
    async def test_generic_reply_when_no_match(self) -> None:
        client = MockLLMClient()
        resp = await client.complete([{"role": "user", "content": "任意无关内容xyz"}])
        assert resp.text  # 非空即可
        assert resp.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_stats_accumulate(self) -> None:
        client = MockLLMClient()
        await client.complete([{"role": "user", "content": "排队"}])
        await client.complete([{"role": "user", "content": "提交"}])
        assert client.stats.total_calls == 2

    @pytest.mark.asyncio
    async def test_delay_respected(self) -> None:
        import time

        client = MockLLMClient(delay_ms=50)
        start = time.monotonic()
        await client.complete([{"role": "user", "content": "hi"}])
        elapsed = time.monotonic() - start
        assert elapsed >= 0.04

    @pytest.mark.asyncio
    async def test_stream_yields_chunks(self) -> None:
        client = MockLLMClient()
        stream = await client.stream([{"role": "user", "content": "提交作业 sbatch"}])
        parts = []
        async for ch in stream:
            parts.append(ch)
        assert len(parts) > 1  # 逐字产出
        assert "".join(parts)  # 非空


class TestCreateLLMClient:
    """工厂函数：无端点时应降级为 Mock。"""

    def test_falls_back_to_mock_when_no_endpoint(self) -> None:
        cfg = Config(llm_base_url="", llm_api_key="")
        client = create_llm_client(cfg)
        assert isinstance(client, MockLLMClient)
