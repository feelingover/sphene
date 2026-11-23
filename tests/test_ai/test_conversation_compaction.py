"""ai/conversation.py の過去ターン軽量化テスト"""

from google.genai import types

from ai.conversation import _IMAGE_PLACEHOLDER, _compact_past_turns


def _user(text: str, image: bool = False) -> types.Content:
    parts = [types.Part.from_text(text=text)]
    if image:
        parts.append(types.Part.from_bytes(data=b"\x89PNG", mime_type="image/png"))
    return types.Content(role="user", parts=parts)


def _model(text: str) -> types.Content:
    return types.Content(role="model", parts=[types.Part.from_text(text=text)])


def _tool_round(name: str) -> list[types.Content]:
    return [
        types.Content(
            role="model",
            parts=[types.Part(function_call=types.FunctionCall(name=name, args={}))],
        ),
        types.Content(
            role="user",
            parts=[types.Part.from_function_response(name=name, response={"raw": "x" * 100})],
        ),
    ]


def _has_function_parts(contents: list[types.Content]) -> bool:
    return any(
        p.function_call or p.function_response for c in contents for p in (c.parts or [])
    )


class TestCompactPastTurns:
    def test_past_tool_parts_removed_latest_turn_kept(self):
        past = [_user("q1"), *_tool_round("search_item"), _model("a1")]
        latest = [_user("q2"), *_tool_round("search_action"), _model("a2")]

        compacted = _compact_past_turns(past + latest)

        assert [c.role for c in compacted[:2]] == ["user", "model"]
        assert not _has_function_parts(compacted[:2])
        assert compacted[1].parts[0].text == "a1"
        assert compacted[2:] == latest

    def test_past_images_replaced_with_placeholder(self):
        history = [_user("見て", image=True), _model("かわいい"), _user("q2", image=True), _model("a2")]

        compacted = _compact_past_turns(history)

        assert [p.text for p in compacted[0].parts] == ["見て", _IMAGE_PLACEHOLDER]
        assert compacted[0].parts[1].inline_data is None
        # 直近ターンの画像はそのまま
        assert compacted[2].parts[1].inline_data is not None

    def test_preamble_text_merged_into_single_model_content(self):
        preamble = types.Content(
            role="model",
            parts=[
                types.Part.from_text(text="調べるね"),
                types.Part(function_call=types.FunctionCall(name="search_item", args={})),
            ],
        )
        tool_response = _tool_round("search_item")[1]
        history = [_user("q1"), preamble, tool_response, _model("a1"), _user("q2"), _model("a2")]

        compacted = _compact_past_turns(history)

        assert [c.role for c in compacted] == ["user", "model", "user", "model"]
        assert [p.text for p in compacted[1].parts] == ["調べるね", "a1"]

    def test_single_turn_history_unchanged(self):
        history = [_user("q1"), *_tool_round("search_item"), _model("a1")]
        assert _compact_past_turns(history) == history

    def test_empty_history(self):
        assert _compact_past_turns([]) == []
