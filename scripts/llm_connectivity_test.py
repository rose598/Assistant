"""LLM 端点连通性验证脚本（第 3 周用）。

功能：从环境变量读取 LLM 配置，真实调用一次模型，验证：
- 端点(base_url)路径是否正确
- 认证(api_key)是否有效
- 模型(model)是否存在
- 回复 / token / 延迟是否正常

用法（在项目根目录，已激活 venv）::

    set AGENT_LLM_BASE_URL=https://api.llm.ustc.edu.cn/v1
    set AGENT_LLM_API_KEY=<你的真实 key>
    set AGENT_LLM_MODEL=qwen-chat
    python scripts/llm_connectivity_test.py

若未设置 key / 端点，会明确提示，不会崩溃。
"""

from __future__ import annotations

import asyncio

from src.config import Config, reset_config
from src.llm.mock_llm import create_llm_client


def main() -> int:
    """执行连通性验证；返回 0 表示成功。"""
    reset_config()
    cfg = Config()

    base_url = cfg.llm_base_url
    model = cfg.llm_model
    has_key = bool(cfg.llm_api_key)

    print("=" * 60)
    print("LLM 连通性验证")
    print("-" * 60)
    print(f"base_url : {base_url or '(空!)'}")
    print(f"model    : {model or '(空!)'}")
    print(f"api_key  : {'已设置' if has_key else '未设置(空!)'}")
    print("-" * 60)

    if not base_url or not has_key:
        print("配置不完整：请先设置 AGENT_LLM_BASE_URL 与 AGENT_LLM_API_KEY（环境变量）。")
        print("当前将以 MockLLM 模式说明如何切换，不改动代码。")
        return 2

    client = create_llm_client(cfg)
    print(f"使用的客户端: {type(client).__name__}")

    async def _run() -> None:
        try:
            resp = await client.complete(
                [{"role": "user", "content": "你好，请回复'连通成功'这几个字"}]
            )
            print("-" * 60)
            print("✅ 调用成功！模型回复：")
            print(resp.text)
            print("-" * 60)
            print(f"model          : {resp.model}")
            print(f"prompt_tokens  : {resp.prompt_tokens}")
            print(f"completion_tok : {resp.completion_tokens}")
            print(f"finish_reason  : {resp.finish_reason}")
            print(f"累计调用次数   : {client.stats.total_calls}")
        except Exception as exc:
            print("❌ 调用失败：")
            print(f"   {type(exc).__name__}: {exc}")
            print("\n可能原因：")
            print("  1. base_url 路径不对（/v1 或其它前缀）")
            print("  2. api_key 无效/过期")
            print("  3. model 名不对（qwen-chat 是否正确）")
            print("  4. 需要校园网/已在校园网内")
            raise SystemExit(1) from exc

    asyncio.run(_run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
