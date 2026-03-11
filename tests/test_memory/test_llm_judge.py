"""LLM Judgeのテスト"""

# type: ignore
# mypy: ignore-errors

import json
from unittest.mock import MagicMock, patch

import pytest

from memory.llm_judge import LLMJudge


class TestLLMJudge:
    """LLMJudgeのテスト"""

    @pytest.mark.asyncio
    @patch("memory.llm_judge.get_lite_model_name")
    @patch("memory.llm_judge._get_genai_client")
    async def test_evaluate_respond_true(
        self, mock_get_client, mock_model_name
    ):
        """LLMがrespond=trueを返す場合"""
        mock_model_name.return_value = "gemini-2.5-flash"

        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "respond": True, 
            "response_type": "full",
            "reason": "テスト"
        })
        mock_get_client.return_value.models.generate_content.return_value = (
            mock_response
        )

        judge = LLMJudge()
        should_respond, response_type, should_react, reaction_emojis = await judge.evaluate(
            message_content="Pythonの書き方を教えて",
            recent_context="UserA: プログラミングの話しよう",
            bot_name="スフェーン",
        )
        assert should_respond is True
        assert response_type == "full_response"

    @pytest.mark.asyncio
    @patch("memory.llm_judge.get_lite_model_name")
    @patch("memory.llm_judge._get_genai_client")
    async def test_evaluate_respond_false(
        self, mock_get_client, mock_model_name
    ):
        """LLMがrespond=falseを返す場合"""
        mock_model_name.return_value = "gemini-2.5-flash"

        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "respond": False, 
            "response_type": "none",
            "reason": "割り込みは不適切"
        })
        mock_get_client.return_value.models.generate_content.return_value = (
            mock_response
        )

        judge = LLMJudge()
        should_respond, response_type, should_react, reaction_emojis = await judge.evaluate(
            message_content="今日のランチ何にする？",
            recent_context="UserA: お腹空いたね\nUserB: ラーメンどう？",
            bot_name="スフェーン",
        )
        assert should_respond is False
        assert response_type == "none"

    @pytest.mark.asyncio
    @patch("memory.llm_judge.get_lite_model_name")
    @patch("memory.llm_judge._get_genai_client")
    async def test_evaluate_uses_bot_lite_model(
        self, mock_get_client, mock_model_name
    ):
        """BOT_LITE_MODELが使用されることをテスト"""
        mock_model_name.return_value = "gemini-2.5-flash"

        mock_response = MagicMock()
        mock_response.text = json.dumps({"respond": False, "reason": "test"})
        mock_get_client.return_value.models.generate_content.return_value = (
            mock_response
        )

        judge = LLMJudge()
        await judge.evaluate("test", "context", "Bot")

        call_args = mock_get_client.return_value.models.generate_content.call_args
        assert call_args.kwargs["model"] == "gemini-2.5-flash"

    @pytest.mark.asyncio
    @patch("memory.llm_judge.get_lite_model_name")
    @patch("memory.llm_judge._get_genai_client")
    async def test_evaluate_empty_response(
        self, mock_get_client, mock_model_name
    ):
        """LLMからの応答が空の場合はFalse"""
        mock_model_name.return_value = "gemini-2.5-flash"

        mock_response = MagicMock()
        mock_response.text = None
        mock_get_client.return_value.models.generate_content.return_value = (
            mock_response
        )

        judge = LLMJudge()
        should_respond, response_type, should_react, reaction_emojis = await judge.evaluate(
            "test", "context", "Bot"
        )
        assert should_respond is False
        assert response_type == "none"

    @pytest.mark.asyncio
    @patch("memory.llm_judge.get_lite_model_name")
    @patch("memory.llm_judge._get_genai_client")
    async def test_evaluate_invalid_json_returns_false(
        self, mock_get_client, mock_model_name
    ):
        """JSON解析失敗時はFalseを返す"""
        mock_model_name.return_value = "gemini-2.5-flash"

        mock_response = MagicMock()
        mock_response.text = "Yes, I think true"  # 不正なJSON
        mock_get_client.return_value.models.generate_content.return_value = (
            mock_response
        )

        judge = LLMJudge()
        should_respond, response_type, should_react, reaction_emojis = await judge.evaluate(
            "test", "context", "Bot"
        )
        # JSON解析失敗 → except → False
        assert should_respond is False
        assert response_type == "none"

    @pytest.mark.asyncio
    @patch("memory.llm_judge.get_lite_model_name")
    @patch("memory.llm_judge._get_genai_client")
    async def test_evaluate_api_error_returns_false(
        self, mock_get_client, mock_model_name
    ):
        """API呼び出しエラー時はFalseを返す（安全側フォールバック）"""
        mock_model_name.return_value = "gemini-2.5-flash"
        mock_get_client.return_value.models.generate_content.side_effect = Exception(
            "API Error"
        )

        judge = LLMJudge()
        should_respond, response_type, should_react, reaction_emojis = await judge.evaluate(
            "test", "context", "Bot"
        )
        assert should_respond is False
        assert response_type == "none"

    @pytest.mark.asyncio
    @patch("memory.llm_judge.get_lite_model_name")
    @patch("memory.llm_judge._get_genai_client")
    async def test_evaluate_list_response(
        self, mock_get_client, mock_model_name
    ):
        """LLMがJSON配列で返した場合も正常に処理できること"""
        mock_model_name.return_value = "gemini-2.5-flash"

        mock_response = MagicMock()
        # Geminiが稀にJSON配列で返すケース
        mock_response.text = json.dumps([{
            "respond": True,
            "response_type": "short",
            "reason": "テスト"
        }])
        mock_get_client.return_value.models.generate_content.return_value = (
            mock_response
        )

        judge = LLMJudge()
        should_respond, response_type, should_react, reaction_emojis = await judge.evaluate(
            message_content="おもしろいね",
            recent_context="UserA: 今日天気いいね",
            bot_name="スフェーン",
        )
        assert should_respond is True
        assert response_type == "short_ack"

    @pytest.mark.asyncio
    @patch("memory.llm_judge.get_lite_model_name")
    @patch("memory.llm_judge._get_genai_client")
    async def test_evaluate_empty_list_response(
        self, mock_get_client, mock_model_name
    ):
        """LLMが空のJSON配列を返した場合はFalseを返すこと"""
        mock_model_name.return_value = "gemini-2.5-flash"

        mock_response = MagicMock()
        mock_response.text = json.dumps([])
        mock_get_client.return_value.models.generate_content.return_value = (
            mock_response
        )

        judge = LLMJudge()
        should_respond, response_type, should_react, reaction_emojis = await judge.evaluate(
            message_content="おもしろいね",
            recent_context="UserA: 今日天気いいね",
            bot_name="スフェーン",
        )
        assert should_respond is False
        assert response_type == "none"

    @pytest.mark.asyncio
    @patch("memory.llm_judge.get_lite_model_name")
    @patch("memory.llm_judge._get_genai_client")
    async def test_evaluate_with_empty_context(
        self, mock_get_client, mock_model_name
    ):
        """コンテキストが空の場合でも動作すること"""
        mock_model_name.return_value = "gemini-2.5-flash"

        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "respond": False, 
            "response_type": "none",
            "reason": "コンテキスト不足"
        })
        mock_get_client.return_value.models.generate_content.return_value = (
            mock_response
        )

        judge = LLMJudge()
        should_respond, response_type, should_react, reaction_emojis = await judge.evaluate(
            "test", "", "Bot"
        )
        assert should_respond is False

        # プロンプトにコンテキストが含まれることを確認
        call_args = mock_get_client.return_value.models.generate_content.call_args
        contents = call_args.kwargs["contents"]
        prompt_text = contents[0].parts[0].text
        assert "最新メッセージ" in prompt_text

    @pytest.mark.asyncio
    @patch("memory.llm_judge.get_lite_model_name")
    @patch("memory.llm_judge._get_genai_client")
    async def test_evaluate_react_and_emojis_parsed(
        self, mock_get_client, mock_model_name
    ):
        """LLMがreact=true, emojisを返した場合に正しくパースされること"""
        mock_model_name.return_value = "gemini-2.5-flash"

        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "respond": True,
            "response_type": "full",
            "react": True,
            "emojis": ["🤔", "💡"],
            "reason": "テスト"
        })
        mock_get_client.return_value.models.generate_content.return_value = (
            mock_response
        )

        judge = LLMJudge()
        should_respond, response_type, should_react, reaction_emojis = await judge.evaluate(
            message_content="面白い話してるね",
            recent_context="UserA: 技術の話",
            bot_name="スフェーン",
        )
        assert should_respond is True
        assert response_type == "full_response"
        assert should_react is True
        assert reaction_emojis == ["🤔", "💡"]

    @pytest.mark.asyncio
    @patch("memory.llm_judge.get_lite_model_name")
    @patch("memory.llm_judge._get_genai_client")
    async def test_evaluate_emojis_capped_at_two(
        self, mock_get_client, mock_model_name
    ):
        """emojisが3個以上返ってきた場合は2個に制限されること"""
        mock_model_name.return_value = "gemini-2.5-flash"

        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "respond": False,
            "response_type": "none",
            "react": True,
            "emojis": ["👍", "😊", "🎉"],
            "reason": "テスト"
        })
        mock_get_client.return_value.models.generate_content.return_value = (
            mock_response
        )

        judge = LLMJudge()
        should_respond, response_type, should_react, reaction_emojis = await judge.evaluate(
            "test", "context", "Bot"
        )
        assert should_react is True
        assert len(reaction_emojis) == 2
        assert reaction_emojis == ["👍", "😊"]

    @pytest.mark.asyncio
    @patch("memory.llm_judge.get_lite_model_name")
    @patch("memory.llm_judge._get_genai_client")
    async def test_evaluate_emojis_empty_when_absent(
        self, mock_get_client, mock_model_name
    ):
        """emojisフィールドが省略された場合は空リストを返すこと"""
        mock_model_name.return_value = "gemini-2.5-flash"

        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "respond": True,
            "response_type": "full",
            "react": False,
            "reason": "テスト"
        })
        mock_get_client.return_value.models.generate_content.return_value = (
            mock_response
        )

        judge = LLMJudge()
        should_respond, response_type, should_react, reaction_emojis = await judge.evaluate(
            "test", "context", "Bot"
        )
        assert should_react is False
        assert reaction_emojis == []

    @pytest.mark.asyncio
    @patch("memory.llm_judge.get_lite_model_name")
    @patch("memory.llm_judge._get_genai_client")
    async def test_evaluate_returns_four_tuple(
        self, mock_get_client, mock_model_name
    ):
        """戻り値が4-tuple (bool, str, bool, list[str]) であること"""
        mock_model_name.return_value = "gemini-2.5-flash"

        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "respond": True,
            "response_type": "short",
            "react": True,
            "emojis": ["👀"],
            "reason": "テスト"
        })
        mock_get_client.return_value.models.generate_content.return_value = (
            mock_response
        )

        judge = LLMJudge()
        result = await judge.evaluate("test", "context", "Bot")
        assert len(result) == 4
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str)
        assert isinstance(result[2], bool)
        assert isinstance(result[3], list)
