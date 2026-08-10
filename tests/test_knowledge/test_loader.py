"""知识库加载器测试。

覆盖加载正确性、字段完整性与未加载时异常。
"""

from __future__ import annotations

import pytest

from src.knowledge.loader import KnowledgeLoader, load_knowledge_base


class TestKnowledgeLoader:
    """知识库加载器测试类."""

    def test_load_all_types_have_entries(self) -> None:
        """各类型数据均有条目."""
        kb, _ = load_knowledge_base()
        assert kb.faq_count >= 30
        assert len(kb.commands) > 0
        assert len(kb.qos) > 0
        assert len(kb.error_codes) > 0

    def test_faq_fields_complete(self) -> None:
        """FAQ 必填字段完整."""
        kb, _ = load_knowledge_base()
        for f in kb.faq:
            assert f.id, "FAQ 必须有 id"
            assert f.title, "FAQ 必须有 title"
            assert f.keywords, "FAQ 必须有 keywords"
            assert f.answer, "FAQ 必须有 answer"
            assert f.search_text.strip(), "FAQ 的 search_text 不能为空"

    def test_kb_not_loaded_raises(self) -> None:
        """未调用 load 前访问 kb 应抛 RuntimeError."""
        loader = KnowledgeLoader()
        with pytest.raises(RuntimeError):
            _ = loader.kb

    def test_load_knowledge_base_convenience(self) -> None:
        """便捷函数返回可用的 kb 与 matcher."""
        kb, matcher = load_knowledge_base()
        assert kb.faq_count >= 30
        assert len(matcher.match("CUDA out of memory")) > 0
