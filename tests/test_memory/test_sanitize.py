import pytest

"""memory/sanitize.py のテスト"""

from memory.sanitize import safe_author_name, sanitize_llm_text, sanitize_llm_text_list


class TestSanitizeLlmText:
    """sanitize_llm_text のテスト"""

    def test_collapses_whitespace_and_strips(self):
        """改行・タブを空白1つにまとめ、前後の空白を除去すること"""
        assert sanitize_llm_text("  a\n\tb  ", 10) == "a b"

    def test_removes_control_and_format_chars(self):
        """制御文字・ゼロ幅文字などの書式文字を除去すること"""
        assert sanitize_llm_text("a\x00b​c‮", 10) == "abc"

    def test_truncates(self):
        """最大文字数で切り詰めること"""
        assert sanitize_llm_text("abcdef", 3) == "abc"

    def test_non_string_and_empty_return_none(self):
        """文字列以外・空文字は None を返すこと"""
        assert sanitize_llm_text(None, 10) is None
        assert sanitize_llm_text(123, 10) is None
        assert sanitize_llm_text(" \n ", 10) is None


class TestSanitizeLlmTextList:
    """sanitize_llm_text_list のテスト"""

    def test_non_list_returns_empty(self):
        """リスト以外は空リストを返すこと"""
        assert sanitize_llm_text_list("abc", 10, 5) == []

    def test_filters_invalid_and_duplicates(self):
        """不正要素と正規化後の重複を除外すること"""
        assert sanitize_llm_text_list(["a", 1, "a ", None, "b"], 10, 5) == ["a", "b"]

    def test_limits_items(self):
        """最大件数で打ち切ること"""
        assert sanitize_llm_text_list(["a", "b", "c"], 10, 2) == ["a", "b"]


class TestSafeAuthorName:
    """safe_author_name のテスト"""

    def test_collapses_newlines_and_truncates(self):
        """改行をつぶし、32文字に切り詰めること"""
        assert safe_author_name("a\nb") == "a b"
        assert len(safe_author_name("x" * 100)) == 32

    def test_strips_markers(self):
        """[BOT] 表記やコロン区切りを偽装できないこと"""
        assert safe_author_name("Foo[BOT]: hi") == "FooBOT hi"
        assert safe_author_name("［BOT］：") == "BOT"

    @pytest.mark.parametrize(
        "name",
        ["A﹕B", "A︓B", "A∶B", "A꞉B", "A【BOT】B", "A〔BOT〕B", "A⟦BOT⟧B", "A<BOT>B"],
    )
    def test_strips_lookalike_markers(self, name):
        """NFKC正規化で寄る類似文字・寄らない類似括弧/コロンも除去すること"""
        result = safe_author_name(name)
        assert result in ("AB", "ABOTB")

    def test_normalizes_nfkc(self):
        """全角英数字などを NFKC で正規化すること"""
        assert safe_author_name("Ｆｏｏ") == "Foo"

    def test_empty_falls_back(self):
        """空になった場合は代替名を返すこと"""
        assert safe_author_name("[]") == "ユーザー"
        assert safe_author_name("\u200b") == "ユーザー"
