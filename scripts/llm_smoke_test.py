"""真实模型冒烟测试脚本（第 3 周，真实 qwen-chat）。

验证在真实端点下：
- client 是否真正切到 OpenAILLMClient（而非 mock）
- Prompt 模板（basic / rag / log_analysis）渲染后真实模型回答是否正常
- 输出格式（列表/代码块/中文）是否合理、是否夹带异常前缀

用法（项目根目录，用户侧已设 AGENT_LLM_* 环境变量）::

    "..\\.venv\\Scripts\\python.exe" scripts/llm_smoke_test.py

依赖真实 key：未设 key 时仅打印 mock 提示。
"""

from __future__ import annotations

import asyncio

from src.config import Config, reset_config
from src.llm.mock_llm import create_llm_client
from src.llm.prompts import get_template

# 贴近 107 平台真实问法的几个问题
SMOKE_QUESTIONS = [
    "提交作业时提示 QOSMaxWallDurationPerJobLimit 怎么办",
    "我的作业一直排队（PD）可能是什么原因",
    "作业跑着跑着就 out of memory 了",
]


async def _ask(client: object, messages: list[dict[str, str]], label: str) -> None:
    """调用一次并打印可读结果。"""
    print("=" * 70)
    print(f"[{label}]")
    try:
        resp = await client.complete(messages)  # type: ignore[attr-defined]
        print(f"回复: {resp.text}")
        print(f"模型: {resp.model} | prompt_tokens={resp.prompt_tokens} "
              f"| completion_tokens={resp.completion_tokens} | reason={resp.finish_reason}")
    except Exception as exc:
        print(f"❌ 调用失败: {type(exc).__name__}: {exc}")


async def _run() -> None:
    reset_config()
    cfg = Config()
    if not cfg.llm_base_url or not cfg.llm_api_key:
        print("未设置 AGENT_LLM_BASE_URL / AGENT_LLM_API_KEY，跳过真实冒烟测试。")
        return

    client = create_llm_client(cfg)
    print(f"使用的客户端: {type(client).__name__}")
    if type(client).__name__ != "OpenAILLMClient":
        print("⚠️ 当前是 Mock 客户端——真实端点未能切换，请检查 base_url/key。")

    # 1. basic 模板
    tpl = get_template("basic")
    for i, q in enumerate(SMOKE_QUESTIONS, 1):
        await _ask(client, tpl.render(question=q), f"basic 场景{i}: {q[:20]}")

    # 2. log_analysis 模板 -- 先验模板兼容性
    ltpl = get_template("log_analysis")
    await _ask(
        client,
        ltpl.render(
            job_id="12345",
            job_state="FAILED",
            reason="OutOfMemory",
            error_log="CUDA out of memory. Attempted to allocate 2.0 GiB",
        ),
        "log_analysis 模板",
    )


def main() -> int:
    asyncio.run(_run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
