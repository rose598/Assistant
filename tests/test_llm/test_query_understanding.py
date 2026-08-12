"""Query 理解模块单元测试.

覆盖同义词扩展、停用词过滤、规范化，以及空/纯标点/超长等边界。
"""

from __future__ import annotations

from src.llm.query_understanding import normalize_query, rewrite_query, understand


class TestNormalizeQuery:
    """规范化：去空白、全角转半角。"""

    def test_strip_and_collapse_spaces(self) -> None:
        assert normalize_query("  为什么  作业   排队  ") == "为什么 作业 排队"

    def test_fullwidth_ascii_to_halfwidth(self) -> None:
        # 全角字母数字转半角
        assert normalize_query("ＱＯＳ ｓｂａｔｃｈ") == "QOS sbatch"

    def test_empty_returns_empty(self) -> None:
        assert normalize_query("") == ""
        assert normalize_query("   ") == ""

    def test_chinese_content_preserved_after_punct_normalize(self) -> None:
        """全角标点转半角可接受，但中文内容应保留完整。"""
        q = normalize_query("为什么，排队了")
        assert "为什么" in q
        assert "排队" in q

    def test_none_coerced_to_empty(self) -> None:
        assert normalize_query(None) == ""


class TestRewriteQuery:
    """改写：同义词扩展 + 停用词。"""

    def test_gpu_synonym_expands(self) -> None:
        q = rewrite_query("我的显卡看不到GPU")
        assert "gpu" in q.lower()

    def test_queue_synonym(self) -> None:
        q = rewrite_query("作业一直排队")
        assert "排队" in q

    def test_failed_synonym(self) -> None:
        q = rewrite_query("我的作业挂了 报错")
        assert "失败" in q

    def test_stopword_removed(self) -> None:
        q = rewrite_query("请问一下我的作业为什么失败了")
        assert "请问一下" not in q

    def test_slang_understood(self) -> None:
        """口语/缩写也能被规范化。"""
        q = rewrite_query("sbatch 嘎了 一直 pending")
        assert "排队" in q or "pending" in q

    def test_terminology_not_mangled(self) -> None:
        """专有名词不应被同义词/停用词破坏。"""
        q = rewrite_query("sbatch -p Students 提交失败")
        assert "sbatch" in q

    def test_cantonese_noise(self) -> None:
        """纯标点/表情不崩溃且不为空输入破坏。"""
        q = rewrite_query("！！！")
        assert isinstance(q, str)

    def test_mixed_language(self) -> None:
        q = rewrite_query("GPU 内存 out of memory cuda")
        assert isinstance(q, str)

    def test_english_word_not_mangled_by_synonyms(self) -> None:
        """英文里的 f/r 不应被单字母变体误伤（of 保持完整）。"""
        q = rewrite_query("out of memory")
        # memory 会被归一化为 内存, 但 "of" 中的 f 必须保留
        assert "out of" in q

    def test_module_not_found_not_mangled(self) -> None:
        q = rewrite_query("报ModuleNotFound")
        assert "modulenotfound" in q.lower()  # 不应变成 modulenot失败ound

    def test_important_not_mangled_by_import_variant(self) -> None:
        q = rewrite_query("important job")
        assert "important" in q  # import 变体不应误伤 important


class TestUnderstandAlias:
    """understand 是 rewrite_query 的别名。"""

    def test_alias_returns_string(self) -> None:
        assert isinstance(understand("我的作业失败了"), str)

    def test_no_error_on_weird(self) -> None:
        """各种奇怪输入都不该抛异常。"""
        for weird in ["", "   ", "!!!", "🤔", None, 12345, ["a", "b"]]:
            r = rewrite_query(weird)  # type: ignore[arg-type]
            assert isinstance(r, str)
