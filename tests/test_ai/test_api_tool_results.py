"""ai/api.py の function_response 生成テスト"""

import json
from unittest.mock import MagicMock, patch

from google.genai import types

from ai.api import _execute_tool_calls, _to_response_dict, rebuild_contents


class TestExecuteToolCalls:
    @patch("ai.api.TOOL_FUNCTIONS")
    def test_unnamed_call_still_returns_response(self, mock_tools):
        """名前のない呼び出しもスキップせず、呼び出しと同数の応答を返す"""
        mock_tools.get.return_value = MagicMock(return_value='{"ok": true}')
        calls = [
            types.FunctionCall(name=None, args={}),
            types.FunctionCall(name="search_item", args={"query": "x"}),
        ]

        results = _execute_tool_calls(calls)

        assert len(results) == len(calls)
        assert results[0].function_response.name == "unknown"
        assert "error" in results[0].function_response.response
        assert results[1].function_response.response == {"ok": True}

    @patch("ai.api.TOOL_FUNCTIONS")
    def test_call_id_is_echoed(self, mock_tools):
        mock_tools.get.return_value = MagicMock(return_value="{}")
        calls = [
            types.FunctionCall(id="call-1", name="search_item", args={}),
            types.FunctionCall(id="call-2", name="search_action", args={}),
        ]

        results = _execute_tool_calls(calls)

        assert [r.function_response.id for r in results] == ["call-1", "call-2"]

    @patch("ai.api.TOOL_FUNCTIONS")
    def test_call_without_id_keeps_none(self, mock_tools):
        mock_tools.get.return_value = MagicMock(return_value="{}")

        results = _execute_tool_calls([types.FunctionCall(name="search_item", args={})])

        assert results[0].function_response.id is None


class TestToResponseDict:
    def test_json_object_string_is_parsed(self):
        assert _to_response_dict('{"found": true}') == {"found": True}

    def test_json_array_is_wrapped(self):
        assert _to_response_dict("[1, 2]") == {"result": [1, 2]}

    def test_json_scalar_is_wrapped(self):
        assert _to_response_dict("42") == {"result": 42}
        assert _to_response_dict('"text"') == {"result": "text"}

    def test_non_json_string_is_wrapped_as_content(self):
        assert _to_response_dict("plain text") == {"content": "plain text"}

    def test_dict_is_returned_as_is(self):
        assert _to_response_dict({"error": "x"}) == {"error": "x"}

    @patch("ai.api.MAX_TOOL_RESULT_CHARS", 50)
    def test_long_result_is_truncated(self):
        long_result = json.dumps({"items": ["あ" * 100]}, ensure_ascii=False)

        response = _to_response_dict(long_result)

        assert response["truncated"] is True
        assert len(response["content"]) == 50
        assert long_result.startswith(response["content"])

    @patch("ai.api.MAX_TOOL_RESULT_CHARS", 50)
    def test_result_at_limit_is_not_truncated(self):
        result = {"k": "v" * 40}  # JSON化で50文字以内
        assert len(json.dumps(result)) <= 50
        assert _to_response_dict(result) == result


class TestRebuildContents:
    def test_none_parts_removed_and_same_roles_merged(self):
        contents = [
            types.Content(role="user", parts=[types.Part.from_text(text="q")]),
            types.Content(role="model", parts=[types.Part.from_text(text="a1")]),
            types.Content(role="user", parts=[types.Part.from_text(text="drop")]),
            types.Content(role="model", parts=[types.Part.from_text(text="a2")]),
        ]

        rebuilt = rebuild_contents(contents, lambda p: None if p.text == "drop" else p)

        assert [c.role for c in rebuilt] == ["user", "model"]
        assert [p.text for p in rebuilt[1].parts] == ["a1", "a2"]
        # 元の履歴は変更しない
        assert len(contents) == 4


def test_extract_text_skips_thought_parts() -> None:
    """_extract_text は thought パートを応答テキストに含めない"""
    from google.genai import types as genai_types

    from ai.api import _extract_text

    content = genai_types.Content(
        role="model",
        parts=[
            genai_types.Part(text="考え中…", thought=True),
            genai_types.Part(text="答えだよ"),
        ],
    )
    assert _extract_text(content) == "答えだよ"
    assert _extract_text(genai_types.Content(role="model", parts=[genai_types.Part(text="x", thought=True)])) is None
