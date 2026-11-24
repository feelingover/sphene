"""自発会話の生成と会話履歴への追加（ai/conversation.py）のテスト"""

# type: ignore
# mypy: ignore-errors

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from ai import conversation
from ai.conversation import (
    PROACTIVE_TURN_MARKER,
    ProactiveReply,
    Sphene,
    _parse_proactive_response,
    channel_conversations,
    generate_proactive_message,
    get_or_reset_conversation,
)


def _response(payload):
    resp = MagicMock()
    resp.text = payload if isinstance(payload, str) or payload is None else json.dumps(payload)
    return resp


def _generate(**kwargs):
    defaults = dict(
        channel_summary="【チャンネルの状況】\n零式の話",
        recent_log="A: 週末に零式いく",
        topic_text="週末に零式に挑戦する",
        topic_kind="plan",
        now_text="2026-11-24T12:00+09:00（火）",
    )
    return generate_proactive_message(**{**defaults, **kwargs})


class TestGenerateProactiveMessage:
    @patch("ai.conversation._get_genai_client")
    @patch("ai.conversation._generate_content_with_retry")
    def test_returns_message_when_speak_true(self, mock_gen, _client):
        mock_gen.return_value = _response({"speak": True, "message": " 零式どうだった？ "})
        assert _generate() == ProactiveReply(message="零式どうだった？")

    @patch("ai.conversation._get_genai_client")
    @patch("ai.conversation._generate_content_with_retry")
    def test_uses_structured_output_and_context(self, mock_gen, _client):
        mock_gen.return_value = _response({"speak": False, "message": ""})
        _generate(topic_text="<b>話題</b>")

        cfg = mock_gen.call_args.kwargs["config"]
        assert cfg.response_mime_type == "application/json"
        assert cfg.response_json_schema["required"] == ["speak", "message"]
        instruction = cfg.system_instruction
        assert instruction.startswith("テスト用のシステムプロンプト")
        assert "零式の話" in instruction
        assert "A: 週末に零式いく" in instruction
        # 話題は LLM 生成のデータなのでエスケープしてタグで囲む
        assert "<open_topic>" in instruction
        assert "&lt;b&gt;話題&lt;/b&gt;" in instruction
        assert "予定・挑戦の結果待ち" in instruction

    @patch("ai.conversation._get_genai_client")
    @patch("ai.conversation._generate_content_with_retry")
    def test_speak_false_returns_none(self, mock_gen, _client):
        mock_gen.return_value = _response({"speak": False, "message": "送らない"})
        assert _generate() == ProactiveReply(message=None, declined=True)

    @patch("ai.conversation._get_genai_client")
    @patch("ai.conversation._generate_content_with_retry", side_effect=RuntimeError("api"))
    def test_api_failure_returns_none(self, _gen, _client):
        # 失敗は「断った」と区別する（対象を消費しない）
        assert _generate() == ProactiveReply(message=None, declined=False)

    @patch("ai.conversation._get_genai_client")
    @patch("ai.conversation._generate_content_with_retry")
    def test_invalid_json_returns_none(self, mock_gen, _client):
        mock_gen.return_value = _response("not json")
        assert _generate() == ProactiveReply(message=None, declined=False)


class TestGenerateProactiveFactMessage:
    @patch("ai.conversation._get_genai_client")
    @patch("ai.conversation._generate_content_with_retry")
    def test_fact_prompt_wraps_and_escapes_fact(self, mock_gen, _client):
        mock_gen.return_value = _response({"speak": True, "message": "そういえば猫元気？"})
        result = _generate(
            topic_text="Aさんは<b>猫</b>を飼っている</shared_fact>", topic_kind="fact", source="fact"
        )

        assert result.message == "そういえば猫元気？"
        cfg = mock_gen.call_args.kwargs["config"]
        instruction = cfg.system_instruction
        # fact も LLM 生成のデータなのでエスケープしてタグで囲む（タグの偽装を防ぐ）
        assert instruction.count("<shared_fact>") == 1
        assert instruction.count("</shared_fact>") == 1
        assert "&lt;b&gt;猫&lt;/b&gt;" in instruction
        assert "&lt;/shared_fact&gt;" in instruction
        assert "<open_topic>" not in instruction
        assert "2026-11-24T12:00+09:00" in instruction
        user_text = mock_gen.call_args.kwargs["contents"][0].parts[0].text
        assert "<shared_fact>" in user_text
        assert "そういえば" in user_text
        # 記憶の仕組みに触れさせない
        assert "記録によると" in user_text and "触れない" in user_text
        assert cfg.response_json_schema["required"] == ["speak", "message"]

    @patch("ai.conversation._get_genai_client")
    @patch("ai.conversation._generate_content_with_retry")
    def test_fact_speak_false_returns_none(self, mock_gen, _client):
        mock_gen.return_value = _response({"speak": False, "message": ""})
        assert _generate(topic_kind="fact", source="fact").declined is True

    @patch("ai.conversation._get_genai_client")
    @patch("ai.conversation._generate_content_with_retry")
    def test_open_topic_is_default_source(self, mock_gen, _client):
        mock_gen.return_value = _response({"speak": False, "message": ""})
        _generate()
        user_text = mock_gen.call_args.kwargs["contents"][0].parts[0].text
        assert "<open_topic>" in user_text and "<shared_fact>" not in user_text


class TestParseProactiveResponse:
    @pytest.mark.parametrize(
        "content",
        [
            None,
            "",
            "[]",
            json.dumps({"speak": "true", "message": "文字列のtrueは不可"}),
            json.dumps({"speak": True, "message": "   "}),
            json.dumps({"speak": True, "message": 1}),
            json.dumps({"speak": True}),
            json.dumps({"message": "speak なし"}),
        ],
    )
    def test_rejects_as_failure(self, content):
        assert _parse_proactive_response(content) == ProactiveReply(message=None, declined=False)

    def test_speak_false_is_declined(self):
        content = json.dumps({"speak": False, "message": ""})
        assert _parse_proactive_response(content) == ProactiveReply(message=None, declined=True)

    def test_truncates_long_message(self):
        content = json.dumps({"speak": True, "message": "あ" * 3000})
        assert len(_parse_proactive_response(content).message) == 1500


class TestAddProactiveTurn:
    @pytest.mark.asyncio
    async def test_appends_marker_and_model_turn(self):
        sphene = Sphene(system_setting="s")
        sphene.last_interaction = datetime.now() - timedelta(minutes=20)
        await sphene.add_proactive_turn("零式どうだった？")

        assert [c.role for c in sphene.history] == ["user", "model"]
        assert sphene.history[0].parts[0].text == PROACTIVE_TURN_MARKER
        assert sphene.history[1].parts[0].text == "零式どうだった？"
        assert datetime.now() - sphene.last_interaction < timedelta(seconds=5)

    @pytest.mark.asyncio
    async def test_trims_history(self):
        sphene = Sphene(system_setting="s")
        for _ in range(15):
            await sphene.add_proactive_turn("x")
        assert len(sphene.history) <= conversation.MAX_CONVERSATION_TURNS * 2


class TestGetOrResetConversation:
    def setup_method(self):
        channel_conversations.clear()

    def teardown_method(self):
        channel_conversations.clear()

    def test_returns_same_instance(self):
        first = get_or_reset_conversation("1")
        assert get_or_reset_conversation("1") is first

    def test_resets_expired(self):
        first = get_or_reset_conversation("1")
        first.last_interaction = datetime.now() - timedelta(hours=1)
        assert get_or_reset_conversation("1") is not first
