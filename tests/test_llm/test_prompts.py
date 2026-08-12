"""Prompt 模板体系单元测试.

验证 4 类模板（basic/rag/script_generate/log_analysis）渲染为
正确的 OpenAI messages 格式，以及未知模板名的回退行为。
"""

from __future__ import annotations

from src.llm.prompts import (
    BASIC_TEMPLATE,
    RAG_TEMPLATE,
    get_template,
    list_templates,
    system_prompt,
)


class TestPromptTemplates:
    """模板渲染与查询。"""

    def test_list_templates_has_4(self) -> None:
        names = list_templates()
        assert {"basic", "rag", "script_generate", "log_analysis"} <= set(names)

    def test_basic_render(self) -> None:
        messages = BASIC_TEMPLATE.render(question="为什么排队")
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "为什么排队" in messages[1]["content"]

    def test_rag_render_injects_knowledge(self) -> None:
        messages = RAG_TEMPLATE.render(
            question="QOS 超时", knowledge="知识条目A\n知识条目B"
        )
        assert "知识条目A" in messages[0]["content"]
        assert "QOS 超时" in messages[1]["content"]

    def test_script_render_fields(self) -> None:
        tpl = get_template("script_generate")
        messages = tpl.render(
            description="训练 ResNet50",
            partitions="Students",
            qos_list="qos_stu_default",
        )
        assert "训练 ResNet50" in messages[1]["content"]
        assert "Students" in messages[1]["content"]

    def test_log_analysis_render(self) -> None:
        tpl = get_template("log_analysis")
        messages = tpl.render(
            job_id="12345",
            job_state="FAILED",
            reason="Killed by signal 9",
            error_log="CUDA out of memory",
        )
        content = messages[1]["content"]
        assert "12345" in content
        assert "FAILED" in content
        assert "CUDA out of memory" in content

    def test_unknown_template_falls_back_to_basic(self) -> None:
        tpl = get_template("nonexistent")
        assert tpl.name == "basic"

    def test_system_prompt_mentions_platform(self) -> None:
        assert "107" in system_prompt
