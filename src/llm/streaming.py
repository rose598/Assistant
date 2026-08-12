"""SSE 流式输出模块。

第 3 周周二交付物：把 LLM 客户端的流式产出包装为 SSE 事件流，
供 Web API / 前端逐 token 展示。

设计：
- 统一的 chunk 文本抽取：兼容两种客户端流式格式
  - OpenAILLMClient -> openai 流式响应对象（chunk.choices[0].delta.content）
  - MockLLMClient  -> 逐字产出的异步生成器（纯字符串 chunk）
- SSE 帧格式：``data: <json>`` 逐段推送，结尾 ``data: [DONE]``
- 鲁棒性：
  - 客户端中途抛错 -> 推 ``data: [ERROR]`` 事件并优雅收尾，不悬挂
  - 空流 / 连接无内容 -> 正常以 [DONE] 收尾
  - 首 chunk 即时产出，保障"逐 token 显示"体验
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from src.llm.client import LLMError


def _extract_chunk_text(chunk: Any) -> str:
    """从任意 chunk 中抽取文本片段。

    兼容 openai 流式对象（含 ``choices[0].delta.content``）与
    纯字符串 chunk（mock 用）。
    """
    if isinstance(chunk, str):
        return chunk
    try:
        choices = chunk.choices
    except AttributeError:
        return ""
    if not choices:
        return ""
    delta = getattr(choices[0], "delta", None)
    if delta is None:
        return ""
    content = getattr(delta, "content", None)
    return content or ""


def sse_payload(data: Any) -> str:
    """把任意数据编码为一条 SSE 事件（去掉换行以符合 SSE 规范）。"""
    payload = json.dumps(data, ensure_ascii=False)
    payload = payload.replace("\n", "\\n")
    return f"data: {payload}\n\n"


async def iter_token_text(
    client: Any,
    messages: list[dict[str, str]],
    **kwargs: Any,
) -> AsyncIterator[str]:
    """迭代 LLM 客户端的流式文本片段（逐 chunk）。

    底层同时兼容真实 openai 流式对象与 mock 字符串生成器。
    若客户端不可用/抛错，转为抛出 LLMError，由上层决定如何收尾。
    """
    stream_obj = await client.stream(messages, **kwargs)
    if stream_obj is None:
        return

    if hasattr(stream_obj, "__aiter__"):
        async for chunk in stream_obj:
            text = _extract_chunk_text(chunk)
            if text:
                yield text
        return

    # 兼容 openai 响应对象内部的异步迭代
    for chunk in stream_obj:
        text = _extract_chunk_text(chunk)
        if text:
            yield text


async def stream_sse(
    client: Any,
    messages: list[dict[str, str]],
    **kwargs: Any,
) -> AsyncIterator[str]:
    """产出完整 SSE 帧序列，含逐段 ``data:`` 与结尾 ``data: [DONE]``。

    - 正常：逐段推进文本事件，最后以 ``data: [DONE]`` 收尾
    - 中途异常：推 ``data: [ERROR]`` 事件，不悬挂、不抛给调用方
    """
    try:
        async for text in iter_token_text(client, messages, **kwargs):
            yield sse_payload({"type": "token", "content": text})
    except (LLMError, Exception) as exc:
        yield sse_payload({"type": "error", "message": str(exc)})
        return
    yield sse_payload({"type": "done"})
    yield "data: [DONE]\n\n"


async def first_token_latency(
    client: Any,
    messages: list[dict[str, str]],
    **kwargs: Any,
) -> tuple[float | None, str]:
    """探测首 token 延迟（毫秒）。

    返回 (首token延迟ms 或 None 表示无输出, 首段文本)。用于评估"首 token ≤500ms"。
    """
    start = asyncio.get_event_loop().time()
    first_text = ""
    it = iter_token_text(client, messages, **kwargs)
    try:
        async for text in it:
            if not first_text:
                first_text = text
                break
    finally:
        # 提前退出时关闭底层异步生成器 避免资源泄漏告警
        aclose = getattr(it, "aclose", None)
        if aclose is not None:
            await aclose()
    latency = (asyncio.get_event_loop().time() - start) * 1000
    return (latency if first_text else None, first_text)


__all__ = ["first_token_latency", "iter_token_text", "sse_payload", "stream_sse"]
