"""Day 2 三合一实测脚本（改写 + 真实问答 + 首 token 延迟）。

用法（在项目根目录，用户侧已设 AGENT_LLM_* 环境变量）::

    "..\\.venv\\Scripts\\python.exe" scripts/llm_day2_check.py

脚本做三件事：
1. query_understanding 改写演示：对若干真实问法看改写结果
2. 用真实 LLM（qwen-chat）对改写后的 query 问答
3. 用 streaming.first_token_latency 量真实首 token 延迟（验证 plan <=500ms 目标）
"""

from __future__ import annotations

import asyncio

from src.config import Config, reset_config
from src.llm import create_llm_client, first_token_latency, rewrite_query

# 贴近 107 平台真实问法 含口语/缩写/错别字
DEMO_QUERIES = [
    "我的显卡看不到GPU",
    "作业一直排队 等半天了",
    "sbatch 提交失败 报错 怎么办",
    "conda 环境没激活 报ModuleNotFound",
    "我申请了gpu但显存不够 out of memory",
]


def _demo_rewrite() -> None:
    """第 1 部分：改写演示。"""
    print("=" * 70)
    print("[1] query_understanding 改写演示")
    print("-" * 70)
    for q in DEMO_QUERIES:
        print(f"  原句 : {q}")
        print(f"  改写 : {rewrite_query(q)}")
        print()


async def _ask_real(client: object, question: str) -> None:
    """第 2 部分：真实 LLM 问答单句。"""
    from src.llm.prompts import get_template

    messages = get_template("basic").render(question=question)
    try:
        resp = await client.complete(messages)  # type: ignore[attr-defined]
        print(f"  问答 : {question}")
        print(f"  回复 : {resp.text[:200]}")
        print()
    except Exception as exc:
        print(f"  问答失败: {type(exc).__name__}: {exc}\n")


async def _latency(client: object) -> None:
    """第 3 部分：真实首 token 延迟。"""
    print("=" * 70)
    print("[3] 真实首 token 延迟探测（plan 目标 <=500ms）")
    print("-" * 70)
    from src.llm.prompts import get_template

    messages = get_template("basic").render(question="介绍一下107算力平台能做什么")
    latency, first = await first_token_latency(client, messages)
    if latency is None:
        print("  无输出 / 流式不可用")
    else:
        status = "✅ <=500ms 达标" if latency <= 500 else "⚠️ 超过 500ms"
        print(f"  首 token 延迟: {latency:.0f} ms  ({status})")
        print(f"  首段文本: {first!r}")


async def main() -> int:
    reset_config()
    cfg = Config()
    if not cfg.llm_base_url or not cfg.llm_api_key:
        print("未设置 AGENT_LLM_BASE_URL / AGENT_LLM_API_KEY，无法进行真实实测。")
        return 2

    client = create_llm_client(cfg)
    print(f"使用的客户端: {type(client).__name__}\n")
    if type(client).__name__ != "OpenAILLMClient":
        print("⚠️ 当前是 Mock 客户端：真实端点未能切换，请检查 base_url/key。\n")

    _demo_rewrite()

    print("=" * 70)
    print("[2] 真实 LLM 问答（改写后的 query 走 qwen-chat）")
    print("-" * 70)
    for q in DEMO_QUERIES:
        await _ask_real(client, q)

    await _latency(client)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
