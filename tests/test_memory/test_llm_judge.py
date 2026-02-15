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
    @patch("memory.llm_judge.get_client")
    @patch("memory.llm_judge.config")
    async def test_evaluate_respond_true(self, mock_config, mock_get_client):
        """LLMがrespond=trueを返す場合"""
        mock_config.JUDGE_MODEL = "gpt-4o-mini"
        mock_config.OPENAI_MODEL = "gpt-4o"

        mock_response = MagicMock()
        mock_response.choices[0].message.content = json.dumps(
            {"respond": True, "reason": "テスト"}
        )
        mock_get_client.return_value.chat.completions.create.return_value = (
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
    @patch("memory.llm_judge.get_client")
    @patch("memory.llm_judge.config")
    async def test_evaluate_respond_false(self, mock_config, mock_get_client):
        """LLMがrespond=falseを返す場合"""
        mock_config.JUDGE_MODEL = ""
        mock_config.OPENAI_MODEL = "gpt-4o-mini"

        mock_response = MagicMock()
        mock_response.choices[0].message.content = json.dumps(
            {"respond": False, "reason": "割り込みは不適切"}
        )
        mock_get_client.return_value.chat.completions.create.return_value = (
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
    @patch("memory.llm_judge.get_client")
    @patch("memory.llm_judge.config")
    async def test_evaluate_uses_judge_model(self, mock_config, mock_get_client):
        """JUDGE_MODELが設定されている場合それを使用する"""
        mock_config.JUDGE_MODEL = "gpt-4o-mini"
        mock_config.OPENAI_MODEL = "gpt-4o"

        mock_response = MagicMock()
        mock_response.choices[0].message.content = json.dumps(
            {"respond": False, "reason": "test"}
        )
        mock_get_client.return_value.chat.completions.create.return_value = (
            mock_response
        )

        judge = LLMJudge()
        await judge.evaluate("test", "context", "Bot")

        call_args = (
            mock_get_client.return_value.chat.completions.create.call_args
        )
        assert call_args.kwargs["model"] == "gpt-4o-mini"

    @pytest.mark.asyncio
    @patch("memory.llm_judge.get_client")
    @patch("memory.llm_judge.config")
    async def test_evaluate_falls_back_to_openai_model(
        self, mock_config, mock_get_client
    ):
        """JUDGE_MODELが空の場合OPENAI_MODELを使用する"""
        mock_config.JUDGE_MODEL = ""
        mock_config.OPENAI_MODEL = "gpt-4o"

        mock_response = MagicMock()
        mock_response.choices[0].message.content = json.dumps(
            {"respond": False, "reason": "test"}
        )
        mock_get_client.return_value.chat.completions.create.return_value = (
            mock_response
        )

        judge = LLMJudge()
        await judge.evaluate("test", "context", "Bot")

        call_args = (
            mock_get_client.return_value.chat.completions.create.call_args
        )
        assert call_args.kwargs["model"] == "gpt-4o"

    @pytest.mark.asyncio
    @patch("memory.llm_judge.get_client")
    @patch("memory.llm_judge.config")
    async def test_evaluate_empty_response(self, mock_config, mock_get_client):
        """LLMからの応答が空の場合はFalse"""
        mock_config.JUDGE_MODEL = ""
        mock_config.OPENAI_MODEL = "gpt-4o-mini"

        mock_response = MagicMock()
        mock_response.choices[0].message.content = None
        mock_get_client.return_value.chat.completions.create.return_value = (
            mock_response
        )

        judge = LLMJudge()
        result = await judge.evaluate("test", "context", "Bot")
        assert result is False

    @pytest.mark.asyncio
    @patch("memory.llm_judge.get_client")
    @patch("memory.llm_judge.config")
    async def test_evaluate_invalid_json_fallback(
        self, mock_config, mock_get_client
    ):
        """JSON解析失敗時のフォールバック"""
        mock_config.JUDGE_MODEL = ""
        mock_config.OPENAI_MODEL = "gpt-4o-mini"

        mock_response = MagicMock()
        mock_response.choices[0].message.content = "Yes, I think true"
        mock_get_client.return_value.chat.completions.create.return_value = (
            mock_response
        )

        judge = LLMJudge()
        result = await judge.evaluate("test", "context", "Bot")
        # "true" が含まれるので True
        assert result is True

    @pytest.mark.asyncio
    @patch("memory.llm_judge.get_client")
    @patch("memory.llm_judge.config")
    async def test_evaluate_invalid_json_no_true(
        self, mock_config, mock_get_client
    ):
        """JSON解析失敗かつ"true"を含まない場合はFalse"""
        mock_config.JUDGE_MODEL = ""
        mock_config.OPENAI_MODEL = "gpt-4o-mini"

        mock_response = MagicMock()
        mock_response.choices[0].message.content = "No, don't respond"
        mock_get_client.return_value.chat.completions.create.return_value = (
            mock_response
        )

        judge = LLMJudge()
        result = await judge.evaluate("test", "context", "Bot")
        assert result is False

    @pytest.mark.asyncio
    @patch("memory.llm_judge.get_client")
    @patch("memory.llm_judge.config")
    async def test_evaluate_api_error_returns_false(
        self, mock_config, mock_get_client
    ):
        """API呼び出しエラー時はFalseを返す（安全側フォールバック）"""
        mock_config.JUDGE_MODEL = ""
        mock_config.OPENAI_MODEL = "gpt-4o-mini"
        mock_get_client.return_value.chat.completions.create.side_effect = (
            Exception("API Error")
        )

        judge = LLMJudge()
        result = await judge.evaluate("test", "context", "Bot")
        assert result is False

    @pytest.mark.asyncio
    @patch("memory.llm_judge.get_client")
    @patch("memory.llm_judge.config")
    async def test_evaluate_with_empty_context(self, mock_config, mock_get_client):
        """コンテキストが空の場合でも動作すること"""
        mock_config.JUDGE_MODEL = ""
        mock_config.OPENAI_MODEL = "gpt-4o-mini"

        mock_response = MagicMock()
        mock_response.choices[0].message.content = json.dumps(
            {"respond": False, "reason": "コンテキスト不足"}
        )
        mock_get_client.return_value.chat.completions.create.return_value = (
            mock_response
        )

        judge = LLMJudge()
        result = await judge.evaluate("test", "", "Bot")
        assert result is False

        # プロンプトに "(会話履歴なし)" が含まれることを確認
        call_args = (
            mock_get_client.return_value.chat.completions.create.call_args
        )
        messages = call_args.kwargs["messages"]
        assert "(会話履歴なし)" in messages[0]["content"]
