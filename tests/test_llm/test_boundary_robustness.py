"""Day 1 成果的边界与鲁棒性对抗测试.

主动用"刁钻"输入探测 client / mock / prompts 的边界处理，
验证空输入、异常类型、缺失键等情况下能否优雅处理而非崩溃。
"""

from __future__ import annotations

import pytest

from src.config import Config
from src.llm.client import LLMResponse, OpenAILLMClient
from src.llm.mock_llm import MockLLMClient
from src.llm.prompts import get_template


class TestMockLLMClientBoundary:
    """Mock 客户端的边界输入。"""

    @pytest.mark.asyncio
    async def test_empty_messages_list(self) -> None:
        """空消息列表不应崩溃：无 user 角色时走兜底回复。"""
        client = MockLLMClient()
        resp = await client.complete([])
        assert resp.text  # 非空兜底

    @pytest.mark.asyncio
    async def test_no_user_role_message(self) -> None:
        """只有 system 消息、无 user：应走兜底而非崩溃。"""
        client = MockLLMClient()
        resp = await client.complete([{"role": "system", "content": "be helpful"}])
        assert resp.text

    @pytest.mark.asyncio
    async def test_content_none(self) -> None:
        """content 为 None：不能崩溃（真实 API 可能出现）。"""
        client = MockLLMClient()
        resp = await client.complete([{"role": "user", "content": None}])
        assert resp.text

    @pytest.mark.asyncio
    async def test_content_missing_key(self) -> None:
        """缺 content 键：应兜底。"""
        client = MockLLMClient()
        resp = await client.complete([{"role": "user"}])
        assert resp.text

    @pytest.mark.asyncio
    async def test_empty_user_content(self) -> None:
        """空字符串 content：应走兜底回复。"""
        client = MockLLMClient()
        resp = await client.complete([{"role": "user", "content": ""}])
        assert resp.text

    @pytest.mark.asyncio
    async def test_pure_symbols_do_not_crash(self) -> None:
        """纯标点/表情：lower() 与匹配应安全。"""
        client = MockLLMClient()
        for weird in ["！！！", "🤔🤔", "---  ---", "...???", "　　"]:
            resp = await client.complete([{"role": "user", "content": weird}])
            assert resp.text

    @pytest.mark.asyncio
    async def test_very_long_content(self) -> None:
        """超长输入（5000 字）：不崩溃、不无限循环。"""
        client = MockLLMClient()
        long_text = "排队" * 5000
        resp = await client.complete([{"role": "user", "content": long_text}])
        assert resp.text

    @pytest.mark.asyncio
    async def test_keyword_mixed_with_noise(self) -> None:
        """关键词夹杂大量无关字符：仍能命中关键词。"""
        client = MockLLMClient()
        resp = await client.complete(
            [{"role": "user", "content": "啊啊啊 我的 cuda out of memory 了 怎么办 好急"}]
        )
        assert "内存" in resp.text or "OOM" in resp.text


class TestLLMResponseBoundary:
    """LLMResponse 的异常取值。"""

    def test_negative_tokens_possible_but_not_forced(self) -> None:
        """分数/负数 tokens 不应被限制（显示层负责）。"""
        resp = LLMResponse(text="x", model="m", prompt_tokens=-1)
        assert resp.prompt_tokens == -1


class TestPromptRenderBoundary:
    """Prompt 渲染的缺失占位符处理。"""

    def test_missing_placeholder_raises_keyerror(self) -> None:
        """(预期) 渲染缺占位符会抛 KeyError——需文档说明 or 改进。"""
        tpl = get_template("script_generate")
        # 缺 description/partitions/qos_list 任一
        with pytest.raises(KeyError):
            tpl.render(description="x")

    def test_extra_kwargs_ignored(self) -> None:
        """多余 kwargs 不影响渲染。"""
        tpl = get_template("basic")
        messages = tpl.render(question="hi", extra="ignored", another=1)
        assert len(messages) == 2

    def test_brace_escaping(self) -> None:
        """用户输入含未转义花括号：format 会误解析——需注意。"""
        # question 里含 {} 会让 str.format 误解读
        tpl = get_template("basic")
        messages = tpl.render(question="队列 {排队} 问题")
        assert "{" in messages[1]["content"]  # 不抛异常是可接受的


class TestConfigFactoryRobustness:
    """工厂与客户端在边界配置下不崩溃。"""

    def test_factory_empty_config(self) -> None:
        """完全空配置（无 base_url/key）降级为 mock。"""
        import src.llm.mock_llm as m

        cfg = Config(llm_base_url="", llm_api_key="")
        client = m.create_llm_client(cfg)
        assert isinstance(client, MockLLMClient)

    def test_openai_client_stable_with_no_endpoint(self) -> None:
        """未配端点时 OpenAILLMClient 构造不抛异常。"""
        client = OpenAILLMClient(Config(llm_base_url="", llm_api_key=""))
        assert client.available is False

    def test_openai_client_full_config_imports_sdk(self) -> None:
        """配了端点但 openai SDK 已装：构造不抛异常（不真正发请求）。"""
        # 即使 key 看似非法 构造阶段也不应崩溃
        client = OpenAILLMClient(
            Config(llm_base_url="http://localhost:9999/v1", llm_api_key="sk-fake")
        )
        assert client.available is True
