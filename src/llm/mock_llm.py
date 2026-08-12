"""Mock LLM 客户端。

端点尚未配置时使用的降级实现。它不调用外部服务，而是根据知识库/意图规则
返回一个确定的、符合 107 平台语义的回复，保证第 3 周各组件可在无端点环境下
开发与联调。端点到位后，通过 config 切换即可替换为 ``OpenAILLMClient``。

同时支持注入人工延迟，用于测试流式输出与超时重试逻辑。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from src.llm.client import LLMCallStats, LLMError, LLMResponse


@dataclass
class MockLLMClient:
    """确定性 Mock LLM：根据关键词返回 107 平台相关回复。

    特性：
    - 无需网络 / API key
    - 支持 ``delay_ms`` 模拟真实延迟（压测流式/超时）
    - 统计可复用 ``LLMCallStats``
    """

    delay_ms: float = 0.0
    model: str = "mock-qwen2.5-7b"
    _stats: LLMCallStats = field(init=False, default_factory=LLMCallStats)

    @property
    def available(self) -> bool:
        """Mock 恒可用。"""
        return True

    @property
    def stats(self) -> LLMCallStats:
        return self._stats

    @staticmethod
    def _keyword_reply(text: object | None) -> str:
        """根据用户输入关键词返回模板化回复。

        ``text`` 可能为 None 或非字符串（真实 API/调用方可能传入），
        先安全转成字符串，避免 ``AttributeError``。
        """
        lowered = str(text or "").lower()
        if "oom" in lowered or "out of memory" in lowered or "显存" in lowered:
            return (
                "你的作业报显存/内存不足（OOM）。建议：\n"
                "1. 调小 `--mem` 或减小 batch size\n"
                "2. 确认是否真正申请了 GPU（`--gres=gpu:1`）\n"
                "3. 避免在登录节点跑训练，改用 `sbatch` 提交"
            )
        if "queue" in lowered or "排队" in lowered or "pd" in lowered:
            return (
                "你的作业在排队（PD）。可能原因：\n"
                "1. 分区/GPU 资源紧张\n"
                "2. QOS 限额未释放\n"
                "3. 申请资源超过分区上限\n"
                "可用 `squeue -u $USER` 查看排队详情，`sprio -w` 查看权重。"
            )
        if "qos" in lowered or "permission" in lowered or "权限" in lowered:
            return (
                "疑似 QOS / 权限问题。请确认：\n"
                "1. 提交时是否带正确分区与 `--qos`\n"
                "2. 账号是否已被授权该 QOS（`sacctmgr show assoc user=$USER`）\n"
                "3. 是否超过资源上限（配额）"
            )
        if "sbatch" in lowered or "submit" in lowered or "提交" in lowered:
            return (
                "提交作业请使用：\n"
                "```bash\n"
                "sbatch -A <account> -p Students --qos=qos_stu_default -J jobname -t 00:10:00 -c 1 --wrap '你的命令'\n"
                "```\n"
                "注意：需显式指定 account、大写分区名与正确 QOS。"
            )
        return (
            "我已收到你的问题。当前为 Mock LLM 回复（端点未配置）。"
            "你的问题与 107 算力平台相关，可尝试提供更多报错信息（如作业状态、错误码），"
            "我将帮你定位原因并给出修复步骤。"
        )

    async def complete(
        self, messages: list[dict[str, str]], **kwargs: Any
    ) -> LLMResponse:
        """返回确定性回复；可注入延迟。"""
        if self.delay_ms > 0:
            await asyncio.sleep(self.delay_ms / 1000.0)
        user_text = ""
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "user":
                content = msg.get("content", "")
                user_text = content if isinstance(content, str) else str(content or "")
                break
        text = self._keyword_reply(user_text)
        response = LLMResponse(
            text=text,
            model=self.model,
            prompt_tokens=len(user_text),
            completion_tokens=len(text),
            finish_reason="stop",
        )
        self._stats.add(response, self.delay_ms)
        return response

    async def stream(self, messages: list[dict[str, str]], **kwargs: Any) -> Any:
        """流式：把 mock 回复按字逐 token 产出，模拟流式效果。"""
        response = await self.complete(messages, **kwargs)

        async def _gen() -> Any:
            for ch in response.text:
                yield ch

        return _gen()


def create_llm_client(config: Any | None = None) -> Any:
    """工厂：根据配置创建真实或 mock 客户端。

    端点配置完整（base_url + api_key）且 SDK 可用 → 真实 OpenAILLMClient；
    否则 → MockLLMClient 降级。这是第 3 周"可切换"机制的入口。
    """
    from src.llm.client import OpenAILLMClient

    real = None
    if config is not None:
        real = OpenAILLMClient(config)
    else:
        try:
            real = OpenAILLMClient()
        except LLMError:
            real = None
    if real is not None and real.available:
        return real
    return MockLLMClient()
