"""memory/sanitize.py のテスト"""

from memory.sanitize import sanitize_llm_text, sanitize_llm_text_list


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
