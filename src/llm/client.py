"""LLM API 客户端封装。

提供统一的 LLM 调用接口，支持 OpenAI 兼容格式（OpenAI SDK）。
包含重试、超时、token 统计与降级策略。
第 3 周周一交付物：`LLMClient` 接口 + OpenAI 兼容实现。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from src.config import get_config


@dataclass
class LLMResponse:
    """LLM 调用返回的统一结构。"""

    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    finish_reason: str = ""


@dataclass
class LLMCallStats:
    """LLM 调用统计（用于 token 统计/成本核算）。"""

    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_calls: int = 0
    total_latency_ms: float = 0.0

    def add(self, response: LLMResponse, latency_ms: float) -> None:
        """累加一次调用的统计。"""
        self.total_calls += 1
        self.total_prompt_tokens += response.prompt_tokens
        self.total_completion_tokens += response.completion_tokens
        self.total_latency_ms += latency_ms

    def to_dict(self) -> dict[str, int | float]:
        """导出为字典（A/B 测试与评估用）。"""
        return {
            "total_calls": self.total_calls,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "average_latency_ms": (
                self.total_latency_ms / self.total_calls if self.total_calls else 0.0
            ),
        }


class LLMClientProtocol(Protocol):
    """LLM 客户端统一协议。

    所有 LLM 实现（真实 / mock）都要满足此协议，保证可替换。
    """

    async def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> LLMResponse:
        """发送对话消息，返回完整回复。"""
        ...

    async def stream(self, messages: list[dict[str, str]], **kwargs: Any) -> Any:
        """发送对话消息，返回流式迭代器。"""
        ...


class LLMError(Exception):
    """LLM 调用异常基类。"""


class LLMRateLimitError(LLMError):
    """触发限流/429 错误。"""


class LLMTimeoutError(LLMError):
    """调用超时。"""


class OpenAILLMClient:
    """基于 OpenAI SDK 的 LLM 客户端（OpenAI 兼容格式）。

    从配置读取 base_url / api_key / model，支持重试与超时。
    ``openai`` 包按需延迟导入：未安装或未配置端点时降级为 ``Unavailable``。
    """

    def __init__(self, config: Any | None = None) -> None:
        self._config = config or get_config()
        self._client: Any | None = None
        self._stats = LLMCallStats()
        self._init_client()

    def _init_client(self) -> None:
        """初始化 OpenAI 客户端；不可用时置空（走降级）。"""
        if not self._config.llm_base_url or not self._config.llm_api_key:
            self._client = None
            return
        try:
            import openai

            self._client = openai.AsyncOpenAI(
                base_url=self._config.llm_base_url,
                api_key=self._config.llm_api_key,
                timeout=self._config.llm_timeout,
                max_retries=self._config.llm_retry,
            )
        except Exception:
            self._client = None

    @property
    def available(self) -> bool:
        """是否可调用真实 LLM（端点已配置且 SDK 可用）。"""
        return self._client is not None

    @property
    def stats(self) -> LLMCallStats:
        """调用统计。"""
        return self._stats

    async def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> LLMResponse:
        """发送消息并返回完整回复。未配置端点时抛出 LLMError。"""
        if not self.available or self._client is None:
            raise LLMError(
                "LLM 端点未配置（llm_base_url / llm_api_key 为空），无法调用真实模型。"
            )
        start = asyncio.get_event_loop().time()
        try:
            resp = await self._client.chat.completions.create(
                model=kwargs.pop("model", self._config.llm_model),
                messages=messages,
                temperature=kwargs.pop("temperature", self._config.llm_temperature),
                max_tokens=kwargs.pop("max_tokens", self._config.llm_max_tokens),
                **kwargs,
            )
        except Exception as exc:
            raise LLMError(f"LLM 调用失败: {exc}") from exc

        choice = resp.choices[0]
        usage = getattr(resp, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)

        result = LLMResponse(
            text=(choice.message.content or "").strip(),
            model=getattr(resp, "model", self._config.llm_model),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            finish_reason=(getattr(choice, "finish_reason", "") or ""),
        )
        latency = (asyncio.get_event_loop().time() - start) * 1000
        self._stats.add(result, latency)
        return result

    async def stream(self, messages: list[dict[str, str]], **kwargs: Any) -> Any:
        """流式调用：逐 token 生成。返回异步迭代器。"""
        if not self.available or self._client is None:
            raise LLMError("LLM 端点未配置，无法进行流式调用。")
        return await self._client.chat.completions.create(
            model=kwargs.pop("model", self._config.llm_model),
            messages=messages,
            temperature=kwargs.pop("temperature", self._config.llm_temperature),
            max_tokens=kwargs.pop("max_tokens", self._config.llm_max_tokens),
            stream=True,
            **kwargs,
        )


def utc_now_iso() -> str:
    """当前 UTC 时间的 ISO 字符串（用于日志/缓存时间戳）。"""
    return datetime.now(timezone.utc).isoformat()
