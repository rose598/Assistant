"""IntegratedQA 双通道演示脚本（冒烟体验，非 pytest）。

用法：python scripts/integrated_qa_demo.py

用内存向量库 + mock LLM 跑 3 个代表性问题，直观展示双通道如何分流：
- 关键词高置信命中 -> channel=keyword（省 LLM）
- 未命中但走 RAG    -> channel=rag（检索+LLM）
- 双通道都不可用    -> channel=fallback（needs_llm=True）

不依赖网络/真实 qwen；用于在 B 到位前验证这条自闭环链路。
"""

from __future__ import annotations

import sys
from contextlib import suppress
from typing import ClassVar

# Windows 控制台默认 GBK 会乱码中文, 切 UTF-8 以保证可读
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    with suppress(AttributeError, OSError):
        sys.stdout.reconfigure(encoding="utf-8")

from src.llm.integrated_qa import IntegratedQA, KeywordHit
from src.llm.vector_store import MemoryVectorStore


class _DemoMatcher:
    """演示用关键词 matcher：命中一组词则高分直回, 否则 None."""

    _KEYWORDS: ClassVar[dict[str, str]] = {
        "CUDA out of memory": "显存/内存不足，建议调小 --mem 或 batch size，并确认申请了 GPU（--gres=gpu:1）",
        "一直排队": "作业长时间排队，可检查分区资源、QOS 限额，或降低资源申请量",
    }

    def match(self, query: str) -> KeywordHit | None:
        lowered = query.lower()
        for kw, answer in self._KEYWORDS.items():
            if kw.lower() in lowered:
                return KeywordHit(
                    answer=answer, confidence=0.95, intent="keyword", sources=["demo"]
                )
        return None


class _MockLLM:
    """演示用 mock LLM：返回带检索知识引用的回答(异步)."""

    async def complete(self, messages: list[dict[str, str]]) -> object:
        system = messages[0]["content"]
        # 抽出检索知识段示意
        knowledge = ""
        for line in system.splitlines():
            if line.startswith("["):
                knowledge += line + " "
        return type("R", (), {"text": f"(mock LLM) 依据检索: {knowledge or '无命中'} 给出建议"})()


async def main() -> None:
    store = MemoryVectorStore()
    store.add(
        [
            "CUDA out of memory 时减小 batch size 或模型规模",
            "作业一直排队 PD pending 可降低资源申请",
            "conda 未激活时在脚本里加 conda init",
        ],
        [{"faq_id": "faq-003"}, {"faq_id": "faq-006"}, {"faq_id": "faq-007"}],
    )

    qa = IntegratedQA(
        keyword_matcher=_DemoMatcher(),
        vector_store=store,
        llm=_MockLLM(),
    )

    questions = [
        "我作业报 CUDA out of memory 怎么办",  # 关键词高置信 -> keyword
        "conda 找不到环境",  # 关键词未命中 -> rag
        "今天天气怎么样",  # 全无 -> fallback
    ]
    for question in questions:
        result = await qa.ask("demo-session", question)
        print(f"\nQ: {question}")
        print(f"   channel={result.channel}  intent={result.intent}  needs_llm={result.needs_llm}")
        print(f"   answer: {result.answer[:60]}")
        if result.sources:
            print(f"   sources: {result.sources}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
