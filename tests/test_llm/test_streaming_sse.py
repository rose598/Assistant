"""SSE 流式输出模块单元测试.

验证：token 文本抽取、SSE 帧格式、空流/异常收尾、首 token 延迟。
使用确定性的 mock 客户端与自建伪客户端，无需真实端点。
"""

from __future__ import annotations

from typing import Any

from src.llm.mock_llm import MockLLMClient
from src.llm.streaming import (
    _extract_chunk_text,
    first_token_latency,
    iter_token_text,
    sse_payload,
    stream_sse,
)


class _OpenAIStyleChunk:
    """模拟 openai 流式 chunk 结构。"""

    def __init__(self, content: str) -> None:
        self._content = content

    @property
    def choices(self) -> list[Any]:
        class Choice:
            def __init__(self, c: str) -> None:
                self.delta = type("D", (), {"content": c})()

        return [Choice(self._content)]


class _AsyncIterClient:
    """纯字符串 chunk 的异步生成器客户端（模拟 mock 流式）。"""

    def __init__(self, chunks: list[str]) -> None:
        self.chunks = chunks

    async def stream(self, messages: list[dict[str, str]], **kwargs: Any) -> Any:
        async def gen() -> Any:
            for c in self.chunks:
                yield c

        return gen()


class TestExtractChunkText:
    """chunk 文本抽取的兼容性。"""

    def test_string_chunk(self) -> None:
        assert _extract_chunk_text("你好") == "你好"

    def test_openai_style_chunk(self) -> None:
        assert _extract_chunk_text(_OpenAIStyleChunk("GPU")) == "GPU"

    def test_empty_chunk(self) -> None:
        assert _extract_chunk_text("") == ""
        assert _extract_chunk_text(object()) == ""

    def test_no_choices(self) -> None:
        assert _extract_chunk_text(type("X", (), {"choices": []})()) == ""


class TestSsePayload:
    """SSE 帧编码。"""

    def test_json_payload(self) -> None:
        frame = sse_payload({"type": "token", "content": "hi"})
        assert frame.startswith("data: ")
        assert '"content": "hi"' in frame
        assert frame.endswith("\n\n")

    def test_newline_escaped(self) -> None:
        # 内容含换行时应被转义 避免破坏 SSE 单行协议
        frame = sse_payload({"type": "token", "content": "a\nb"})
        assert "\\n" in frame


class TestIterTokenText:
    """逐段文本迭代（兼容两种客户端）。"""

    async def test_mock_client_text(self) -> None:
        client = MockLLMClient()
        texts = []
        async for t in iter_token_text(client, [{"role": "user", "content": "提交作业 sbatch"}]):
            texts.append(t)
        assert texts  # mock 逐字产出非空
        assert "".join(texts)  # 拼接非空

    async def test_openai_style_chunks(self) -> None:
        client = _AsyncIterClient(["GPU", " 不足", "，请调整"])
        merged = ""
        async for t in iter_token_text(client, []):
            merged += t
        assert merged == "GPU 不足，请调整"

    async def test_empty_client_yields_nothing(self) -> None:
        client = _AsyncIterClient([])
        tokens = []
        async for t in iter_token_text(client, []):
            tokens.append(t)
        assert tokens == []


class TestStreamSSE:
    """SSE 事件流完整产出。"""

    async def test_yields_done_at_end(self) -> None:
        client = _AsyncIterClient(["a", "b"])
        frames = []
        async for f in stream_sse(client, []):
            frames.append(f)
        assert frames  # 至少 token 帧
        assert frames[-1] == "data: [DONE]\n\n"
        # 应包含 type=done 事件
        assert any('"type": "done"' in f for f in frames)

    async def test_empty_stream_still_done(self) -> None:
        client = _AsyncIterClient([])
        frames = []
        async for f in stream_sse(client, []):
            frames.append(f)
        assert frames
        assert frames[-1] == "data: [DONE]\n\n"


class TestFirstTokenLatency:
    """首 token 延迟探测。"""

    async def test_mock_returns_first_text_and_latency(self) -> None:
        client = MockLLMClient()
        latency, text = await first_token_latency(
            client, [{"role": "user", "content": "提交"}]
        )
        assert text  # 有首段文本
        assert latency is not None
        assert latency >= 0

    async def test_latency_with_delay(self) -> None:
        client = MockLLMClient(delay_ms=50)
        latency, _ = await first_token_latency(
            client, [{"role": "user", "content": "hi"}]
        )
        assert latency is not None
        assert latency >= 40  # 至少体现注入延迟
