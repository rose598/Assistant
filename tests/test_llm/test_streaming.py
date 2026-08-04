"""流式输出测试（SSE 逐 token）.

本模块测试 SSE（Server-Sent Events）协议下的流式输出行为：
- 首 token 延迟（验收：<= 500ms）
- 逐 token 顺序正确、无丢失、无乱序
- 完整回答重建（流式拼接 == 完整文本）
- 中断/异常场景处理

验收标准：首 token <= 500ms，token 顺序正确，流式重建完整。

遵循角色 D 测试惯例：由于 A 的 streaming.py 尚未实现，
这里使用自包含的 MockStreamer 模拟 SSE 流式输出，待 A 实现后替换。
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

FIRST_TOKEN_BUDGET_MS = 500


class MockStreamer:
    """模拟 SSE 流式输出器（待 A 实现 streaming.py 后替换）.

    模拟行为：
    - 将完整回答按 token 分块（中文按 2 字一块，英文按词）
    - 每块间模拟网络延迟
    - 支持测试首 token 延迟指标
    """

    def __init__(self, base_delay: float = 0.02) -> None:
        self.base_delay = base_delay

    @staticmethod
    def _chunk(text: str) -> list[str]:
        """把回答切分成流式 token 块."""
        chunks: list[str] = []
        i = 0
        while i < len(text):
            if text[i].isascii():
                # 英文按单词块
                j = i
                while j < len(text) and text[j].isascii() and not text[j].isspace():
                    j += 1
                if j == i:
                    j = i + 1
                chunks.append(text[i:j])
                i = j
            else:
                # 中文每 2 字一块
                chunks.append(text[i : i + 2])
                i += 2
        return chunks

    async def stream(self, question: str) -> list[str]:
        """异步逐块产生回答（模拟 SSE 事件流）.

        返回产生时间列表，用于验证首 token 延迟。
        """
        answer = self._compose(question)
        chunks = self._chunk(answer)
        produced: list[str] = []
        for chunk in chunks:
            await asyncio.sleep(self.base_delay)
            produced.append(chunk)
        return produced

    async def stream_with_timestamps(self, question: str) -> list[tuple[str, float]]:
        """返回 (chunk, 相对首块时刻) 列表，供首 token 延迟测试."""
        answer = self._compose(question)
        chunks = self._chunk(answer)
        start = time.perf_counter()
        out: list[tuple[str, float]] = []
        for chunk in chunks:
            await asyncio.sleep(self.base_delay)
            out.append((chunk, time.perf_counter() - start))
        return out

    @staticmethod
    def _compose(question: str) -> str:
        """生成最终回答（模拟 LLM 输出）."""
        return f"已收到你的问题「{question}」。建议检查脚本参数并重试提交。"


class TestStreaming:
    """SSE 流式输出测试."""

    @pytest.fixture
    def streamer(self) -> MockStreamer:
        return MockStreamer(base_delay=0.01)

    async def test_stream_returns_chunks_in_order(self, streamer: MockStreamer) -> None:
        """测试逐 token 按序返回."""
        chunks = await streamer.stream("提交作业")
        assert len(chunks) >= 5, "流式输出块数量过少"
        # 拼接后应等于完整回答
        full = "".join(chunks)
        assert full == streamer._compose("提交作业")

    async def test_first_token_latency(self, streamer: MockStreamer) -> None:
        """测试首 token 延迟 <= 500ms 验收标准."""
        timed = await streamer.stream_with_timestamps("如何查看GPU")
        assert timed, "没有产生任何 token"
        first_ts = timed[0][1]
        # 断言首块在预算内（宽松处理，模拟环境下延迟很小）
        assert (
            first_ts * 1000 <= FIRST_TOKEN_BUDGET_MS
        ), f"首 token 延迟 {first_ts * 1000:.1f}ms 超过 {FIRST_TOKEN_BUDGET_MS}ms"

    async def test_no_chunk_loss(self, streamer: MockStreamer) -> None:
        """测试流式过程中不丢块、不增加块."""
        full_expected = streamer._compose("GPU 训练")
        chunks = await streamer.stream("GPU 训练")
        assert "".join(chunks) == full_expected

    async def test_each_chunk_non_empty(self, streamer: MockStreamer) -> None:
        """测试每个 chunk 非空."""
        chunks = await streamer.stream("排队问题")
        for c in chunks:
            assert c

    def test_chunking_merges_to_original(self) -> None:
        """测试分块算法能将回答无损拼接回原样."""
        text = "这是一个用于测试流式输出的中文长回答包含 GPU OOM 和 sbatch 关键词。"
        chunks = MockStreamer._chunk(text)
        assert "".join(chunks) == text


class TestStreamingInterrupt:
    """流式中断/异常场景测试."""

    async def test_interrupt_before_completion(self) -> None:
        """测试流式中断时已有 token 部分仍可返回（模拟客户端断开）."""

        class CancelStreamer(MockStreamer):
            async def stream(self, question: str) -> list[str]:  # noqa: D102
                produced: list[str] = []
                for c in self._chunk(self._compose(question)):
                    await asyncio.sleep(0.005)
                    produced.append(c)
                    # 模拟第三次块后中断
                    if len(produced) == 3:
                        break
                return produced

        chunks = await CancelStreamer().stream("诊断错误")
        assert 1 <= len(chunks) <= 3
        assert all(chunks)

    async def test_error_during_stream_raises(self) -> None:
        """测试流式过程中抛错时向外传播（前端可捕获显示错误）."""

        class FailingStreamer(MockStreamer):
            async def stream(self, question: str) -> list[str]:  # noqa: D102
                await asyncio.sleep(0.001)
                raise RuntimeError("上游 LLM 连接中断")

        with pytest.raises(RuntimeError):
            await FailingStreamer().stream("x")


class TestStreamingReport:
    """生成流式输出测试报告."""

    def test_generate_report(self, tmp_path: Path) -> None:
        """生成流式输出性能报告（首 token 延迟、块数、重建完整性）."""

        async def collect() -> dict[str, float | int | bool]:
            streamer = MockStreamer(base_delay=0.005)
            q = "帮我写个 GPU 训练脚本"
            timed = await streamer.stream_with_timestamps(q)
            first_ms = timed[0][1] * 1000
            full = "".join(c for c, _ in timed)
            return {
                "first_token_ms": round(first_ms, 1),
                "chunks": len(timed),
                "reconstructed_ok": full == streamer._compose(q),
                "first_token_budget_ms": FIRST_TOKEN_BUDGET_MS,
            }

        report_data = asyncio.run(collect())

        first_token_ms = float(report_data["first_token_ms"])
        reconstructed_ok = bool(report_data["reconstructed_ok"])

        report_file = tmp_path / "streaming_report.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)

        assert report_file.exists()
        assert reconstructed_ok is True
        assert first_token_ms <= FIRST_TOKEN_BUDGET_MS
