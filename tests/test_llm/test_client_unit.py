"""LLM client 单元测试.

覆盖 OpenAILLMClient 的降级行为、异常包装、统计，以及 LLMResponse 结构。
不依赖真实端点：未配置端点时应降级/抛 LLMError 而非崩溃。
"""

from __future__ import annotations

import pytest

from src.config import Config, reset_config
from src.llm.client import (
    LLMCallStats,
    LLMError,
    LLMResponse,
    OpenAILLMClient,
)


def _no_endpoint_config() -> Config:
    """返回无端点配置（llm_base_url/api_key 置空）。"""
    reset_config()
    return Config(llm_base_url="", llm_api_key="", llm_model="test-model")


class TestOpenAILLMClientDegrade:
    """未配置端点时的降级行为。"""

    def test_not_available_when_no_endpoint(self) -> None:
        cfg = _no_endpoint_config()
        client = OpenAILLMClient(cfg)
        assert client.available is False

    @pytest.mark.asyncio
    async def test_complete_async_raises_when_no_endpoint(self) -> None:
        cfg = _no_endpoint_config()
        client = OpenAILLMClient(cfg)
        with pytest.raises(LLMError):
            await client.complete([{"role": "user", "content": "hi"}])


class TestLLMResponse:
    """LLMResponse 数据结构。"""

    def test_defaults(self) -> None:
        resp = LLMResponse(text="hello", model="m")
        assert resp.prompt_tokens == 0
        assert resp.completion_tokens == 0
        assert resp.finish_reason == ""


class TestLLMCallStats:
    """调用统计累加。"""

    def test_add_accumulates(self) -> None:
        stats = LLMCallStats()
        stats.add(LLMResponse(text="a", model="m", prompt_tokens=10, completion_tokens=5), 100.0)
        stats.add(LLMResponse(text="b", model="m", prompt_tokens=20, completion_tokens=10), 300.0)
        assert stats.total_calls == 2
        assert stats.total_prompt_tokens == 30
        assert stats.total_completion_tokens == 15
        assert stats.total_latency_ms == 400.0

    def test_average_latency(self) -> None:
        stats = LLMCallStats()
        stats.add(LLMResponse(text="a", model="m"), 100.0)
        stats.add(LLMResponse(text="b", model="m"), 300.0)
        assert stats.to_dict()["average_latency_ms"] == 200.0

    def test_to_dict_empty_stats(self) -> None:
        stats = LLMCallStats()
        d = stats.to_dict()
        assert d["total_calls"] == 0
        assert d["average_latency_ms"] == 0.0
