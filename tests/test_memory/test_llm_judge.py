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
    @patch("memory.llm_judge.get_model_name")
    @patch("memory.llm_judge._get_genai_client")
    @patch("memory.llm_judge.config")
    async def test_evaluate_respond_true(
        self, mock_config, mock_get_client, mock_model_name
    ):
        """LLMがrespond=trueを返す場合"""
        mock_config.JUDGE_MODEL = "gemini-2.5-flash"
        mock_model_name.return_value = "gemini-2.5-flash"

        mock_response = MagicMock()
        mock_response.text = json.dumps({"respond": True, "reason": "テスト"})
        mock_get_client.return_value.models.generate_content.return_value = (
            mock_response
        )

        judge = LLMJudge()
        result = await judge.evaluate(
            message_content="Pythonの書き方を教えて",
            recent_context="UserA: プログラミングの話しよう",
            bot_name="アサヒ",
        )
        assert result is True

    @pytest.mark.asyncio
    @patch("memory.llm_judge.get_model_name")
    @patch("memory.llm_judge._get_genai_client")
    @patch("memory.llm_judge.config")
    async def test_evaluate_respond_false(
        self, mock_config, mock_get_client, mock_model_name
    ):
        """LLMがrespond=falseを返す場合"""
        mock_config.JUDGE_MODEL = ""
        mock_model_name.return_value = "gemini-2.5-flash"

        mock_response = MagicMock()
        mock_response.text = json.dumps(
            {"respond": False, "reason": "割り込みは不適切"}
        )
        mock_get_client.return_value.models.generate_content.return_value = (
            mock_response
        )

        judge = LLMJudge()
        result = await judge.evaluate(
            message_content="今日のランチ何にする？",
            recent_context="UserA: お腹空いたね\nUserB: ラーメンどう？",
            bot_name="アサヒ",
        )
        assert result is False

    @pytest.mark.asyncio
    @patch("memory.llm_judge.get_model_name")
    @patch("memory.llm_judge._get_genai_client")
    @patch("memory.llm_judge.config")
    async def test_evaluate_uses_judge_model(
        self, mock_config, mock_get_client, mock_model_name
    ):
        """JUDGE_MODELが設定されている場合それを使用する"""
        mock_config.JUDGE_MODEL = "gemini-2.5-flash"
        mock_model_name.return_value = "gemini-2.5-pro"  # fallback（使われないはず）

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
    @patch("memory.llm_judge.get_model_name")
    @patch("memory.llm_judge._get_genai_client")
    @patch("memory.llm_judge.config")
    async def test_evaluate_falls_back_to_model_name(
        self, mock_config, mock_get_client, mock_model_name
    ):
        """JUDGE_MODELが空の場合get_model_name()を使用する"""
        mock_config.JUDGE_MODEL = ""
        mock_model_name.return_value = "gemini-2.5-pro"

        mock_response = MagicMock()
        mock_response.text = json.dumps({"respond": False, "reason": "test"})
        mock_get_client.return_value.models.generate_content.return_value = (
            mock_response
        )

        judge = LLMJudge()
        await judge.evaluate("test", "context", "Bot")

        call_args = mock_get_client.return_value.models.generate_content.call_args
        assert call_args.kwargs["model"] == "gemini-2.5-pro"

    @pytest.mark.asyncio
    @patch("memory.llm_judge.get_model_name")
    @patch("memory.llm_judge._get_genai_client")
    @patch("memory.llm_judge.config")
    async def test_evaluate_empty_response(
        self, mock_config, mock_get_client, mock_model_name
    ):
        """LLMからの応答が空の場合はFalse"""
        mock_config.JUDGE_MODEL = ""
        mock_model_name.return_value = "gemini-2.5-flash"

        mock_response = MagicMock()
        mock_response.text = None
        mock_get_client.return_value.models.generate_content.return_value = (
            mock_response
        )

        judge = LLMJudge()
        result = await judge.evaluate("test", "context", "Bot")
        assert result is False

    @pytest.mark.asyncio
    @patch("memory.llm_judge.get_model_name")
    @patch("memory.llm_judge._get_genai_client")
    @patch("memory.llm_judge.config")
    async def test_evaluate_invalid_json_returns_false(
        self, mock_config, mock_get_client, mock_model_name
    ):
        """JSON解析失敗時はFalseを返す"""
        mock_config.JUDGE_MODEL = ""
        mock_model_name.return_value = "gemini-2.5-flash"

        mock_response = MagicMock()
        mock_response.text = "Yes, I think true"  # 不正なJSON
        mock_get_client.return_value.models.generate_content.return_value = (
            mock_response
        )

        judge = LLMJudge()
        result = await judge.evaluate("test", "context", "Bot")
        # JSON解析失敗 → except → False
        assert result is False

    @pytest.mark.asyncio
    @patch("memory.llm_judge.get_model_name")
    @patch("memory.llm_judge._get_genai_client")
    @patch("memory.llm_judge.config")
    async def test_evaluate_api_error_returns_false(
        self, mock_config, mock_get_client, mock_model_name
    ):
        """API呼び出しエラー時はFalseを返す（安全側フォールバック）"""
        mock_config.JUDGE_MODEL = ""
        mock_model_name.return_value = "gemini-2.5-flash"
        mock_get_client.return_value.models.generate_content.side_effect = Exception(
            "API Error"
        )

        judge = LLMJudge()
        result = await judge.evaluate("test", "context", "Bot")
        assert result is False

    @pytest.mark.asyncio
    @patch("memory.llm_judge.get_model_name")
    @patch("memory.llm_judge._get_genai_client")
    @patch("memory.llm_judge.config")
    async def test_evaluate_with_empty_context(
        self, mock_config, mock_get_client, mock_model_name
    ):
        """コンテキストが空の場合でも動作すること"""
        mock_config.JUDGE_MODEL = ""
        mock_model_name.return_value = "gemini-2.5-flash"

        mock_response = MagicMock()
        mock_response.text = json.dumps(
            {"respond": False, "reason": "コンテキスト不足"}
        )
        mock_get_client.return_value.models.generate_content.return_value = (
            mock_response
        )

        judge = LLMJudge()
        result = await judge.evaluate("test", "", "Bot")
        assert result is False

        # プロンプトにコンテキストが含まれることを確認
        call_args = mock_get_client.return_value.models.generate_content.call_args
        prompt = call_args.kwargs["contents"]
        assert "最新メッセージ" in prompt
