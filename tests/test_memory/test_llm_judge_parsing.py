"""LLM Judge の出力パース（_to_bool / _to_emoji_list）のテスト"""

import pytest

from memory.llm_judge import _to_bool, _to_emoji_list


class TestToBool:
    @pytest.mark.parametrize("value", [True, "true", "True", " yes ", "1"])
    def test_truthy(self, value):
        assert _to_bool(value) is True

    @pytest.mark.parametrize("value", [False, "false", "False", "no", "", None, 1, [], {}])
    def test_falsy(self, value):
        assert _to_bool(value) is False


class TestToEmojiList:
    def test_string_is_not_split(self):
        family = "👨‍👩‍👧"
        assert _to_emoji_list(family) == [family]

    def test_list_filters_non_strings_and_caps(self):
        assert _to_emoji_list(["👍", 1, "", "🎉", "😀"]) == ["👍", "🎉"]

    @pytest.mark.parametrize("value", [None, 3, {"a": 1}])
    def test_other_types_become_empty(self, value):
        assert _to_emoji_list(value) == []
