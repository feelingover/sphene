"""ai/router.py のテスト"""

# type: ignore
# mypy: ignore-errors

import json
from unittest.mock import MagicMock, patch

import pytest
from google.genai import types

from ai.router import detect_tool_mode, _call_router_llm, _PREFILT_MAX_CHARS


class TestPrefilt:
    """プリフィルタ（文字数ベースの短文判定）のテスト"""

    def test_short_message_returns_none(self):
        """_PREFILT_MAX_CHARS以下のメッセージはRouterを呼ばずnoneを返す"""
        short = "a" * _PREFILT_MAX_CHARS
        with patch("ai.router._call_router_llm") as mock_llm:
            result = detect_tool_mode(short)
        assert result == "none"
        mock_llm.assert_not_called()

    def test_empty_message_returns_none(self):
        """空文字列もnoneを返す"""
        with patch("ai.router._call_router_llm") as mock_llm:
            result = detect_tool_mode("")
        assert result == "none"
        mock_llm.assert_not_called()

    def test_whitespace_only_message_returns_none(self):
        """空白のみのメッセージもnoneを返す（strip後に判定）"""
        with patch("ai.router._call_router_llm") as mock_llm:
            result = detect_tool_mode("   ")
        assert result == "none"
        mock_llm.assert_not_called()

    def test_long_message_calls_router(self):
        """_PREFILT_MAX_CHARSを超えるメッセージはRouterを呼ぶ"""
        long_msg = "a" * (_PREFILT_MAX_CHARS + 1)
        with patch("ai.router._call_router_llm", return_value="function_calling") as mock_llm:
            result = detect_tool_mode(long_msg)
        assert result == "function_calling"
        mock_llm.assert_called_once()

    def test_boundary_message_is_none(self):
        """ちょうど_PREFILT_MAX_CHARSはnone（以下なので）"""
        boundary = "a" * _PREFILT_MAX_CHARS
        with patch("ai.router._call_router_llm") as mock_llm:
            result = detect_tool_mode(boundary)
        assert result == "none"
        mock_llm.assert_not_called()


class TestRouterDisabled:
    """ROUTER_ENABLED=Falseの時の動作テスト"""

    def test_router_disabled_returns_function_calling(self):
        """ROUTER_ENABLED=Falseの時はfunction_callingを返す"""
        long_msg = "FF14のカッパーオアの入手方法を教えて"
        with patch("ai.router.config") as mock_config:
            mock_config.ROUTER_ENABLED = False
            mock_config.ROUTER_MODEL = ""
            mock_config.JUDGE_MODEL = ""
            with patch("ai.router._call_router_llm") as mock_llm:
                result = detect_tool_mode(long_msg)
        assert result == "function_calling"
        mock_llm.assert_not_called()


class TestRouterLLMCall:
    """Router LLM呼び出しのテスト"""

    def _make_mock_response(self, tool_mode: str, reason: str = "test") -> MagicMock:
        mock_response = MagicMock()
        mock_response.text = json.dumps({"tool_mode": tool_mode, "reason": reason})
        return mock_response

    @patch("ai.router._generate_content_with_retry")
    @patch("ai.router.get_model_name", return_value="gemini-flash")
    @patch("ai.router._get_genai_client")
    @patch("ai.router.config")
    def test_grounding_mode_detection(self, mock_config, mock_client, mock_model, mock_gen):
        """groundingモードが正しく判定されるテスト"""
        mock_config.ROUTER_MODEL = ""
        mock_config.JUDGE_MODEL = ""
        mock_gen.return_value = self._make_mock_response("grounding", "最新ニュースが必要")
        result = _call_router_llm("今日のニュースを教えて", None)
        assert result == "grounding"

    @patch("ai.router._generate_content_with_retry")
    @patch("ai.router.get_model_name", return_value="gemini-flash")
    @patch("ai.router._get_genai_client")
    @patch("ai.router.config")
    def test_function_calling_mode_detection(self, mock_config, mock_client, mock_model, mock_gen):
        """function_callingモードが正しく判定されるテスト"""
        mock_config.ROUTER_MODEL = ""
        mock_config.JUDGE_MODEL = ""
        mock_gen.return_value = self._make_mock_response("function_calling", "XIVAPIが必要")
        result = _call_router_llm("カッパーオアのレシピを調べて", None)
        assert result == "function_calling"

    @patch("ai.router._generate_content_with_retry")
    @patch("ai.router.get_model_name", return_value="gemini-flash")
    @patch("ai.router._get_genai_client")
    @patch("ai.router.config")
    def test_none_mode_detection(self, mock_config, mock_client, mock_model, mock_gen):
        """noneモードが正しく判定されるテスト"""
        mock_config.ROUTER_MODEL = ""
        mock_config.JUDGE_MODEL = ""
        mock_gen.return_value = self._make_mock_response("none", "雑談")
        result = _call_router_llm("今日もよろしくね！", None)
        assert result == "none"

    @patch("ai.router._generate_content_with_retry")
    @patch("ai.router.get_model_name", return_value="gemini-flash")
    @patch("ai.router._get_genai_client")
    @patch("ai.router.config")
    def test_invalid_mode_falls_back_to_function_calling(self, mock_config, mock_client, mock_model, mock_gen):
        """不正なtool_modeはfunction_callingにフォールバックする"""
        mock_config.ROUTER_MODEL = ""
        mock_config.JUDGE_MODEL = ""
        mock_gen.return_value = self._make_mock_response("unknown_mode")
        result = _call_router_llm("何かを調べて", None)
        assert result == "function_calling"

    @patch("ai.router._generate_content_with_retry")
    @patch("ai.router.get_model_name", return_value="gemini-flash")
    @patch("ai.router._get_genai_client")
    @patch("ai.router.config")
    def test_empty_response_falls_back_to_function_calling(self, mock_config, mock_client, mock_model, mock_gen):
        """空レスポンスはfunction_callingにフォールバックする"""
        mock_config.ROUTER_MODEL = ""
        mock_config.JUDGE_MODEL = ""
        mock_response = MagicMock()
        mock_response.text = ""
        mock_gen.return_value = mock_response
        result = _call_router_llm("何かを調べて", None)
        assert result == "function_calling"

    @patch("ai.router._generate_content_with_retry")
    @patch("ai.router.get_model_name", return_value="gemini-flash")
    @patch("ai.router._get_genai_client")
    @patch("ai.router.config")
    def test_list_response_uses_first_element(self, mock_config, mock_client, mock_model, mock_gen):
        """LLMがリスト形式で返した場合も最初の要素を使う"""
        mock_config.ROUTER_MODEL = ""
        mock_config.JUDGE_MODEL = ""
        mock_response = MagicMock()
        mock_response.text = json.dumps([{"tool_mode": "grounding", "reason": "test"}])
        mock_gen.return_value = mock_response
        result = _call_router_llm("今日の天気は？", None)
        assert result == "grounding"

    @patch("ai.router._generate_content_with_retry")
    @patch("ai.router.get_model_name", return_value="gemini-flash")
    @patch("ai.router._get_genai_client")
    @patch("ai.router.config")
    def test_context_is_passed_to_prompt(self, mock_config, mock_client, mock_model, mock_gen):
        """contextが渡された場合、promptに含まれること"""
        mock_config.ROUTER_MODEL = ""
        mock_config.JUDGE_MODEL = ""
        mock_gen.return_value = self._make_mock_response("none")
        _call_router_llm("続きを教えて", context="過去の会話コンテキスト")

        call_args = mock_gen.call_args
        contents = call_args.kwargs["contents"]
        prompt_text = contents[0].parts[0].text
        assert "過去の会話コンテキスト" in prompt_text

    @patch("ai.router._generate_content_with_retry")
    @patch("ai.router.get_model_name", return_value="gemini-flash")
    @patch("ai.router._get_genai_client")
    @patch("ai.router.config")
    def test_router_model_priority(self, mock_config, mock_client, mock_model, mock_gen):
        """ROUTER_MODEL > JUDGE_MODEL > GEMINI_MODELの優先順位テスト"""
        mock_config.ROUTER_MODEL = "custom-router-model"
        mock_config.JUDGE_MODEL = "judge-model"
        mock_gen.return_value = self._make_mock_response("none")
        _call_router_llm("テスト", None)

        call_args = mock_gen.call_args
        assert call_args.kwargs["model"] == "custom-router-model"

    @patch("ai.router._generate_content_with_retry")
    @patch("ai.router.get_model_name", return_value="default-model")
    @patch("ai.router._get_genai_client")
    @patch("ai.router.config")
    def test_judge_model_fallback(self, mock_config, mock_client, mock_model, mock_gen):
        """ROUTER_MODEL未設定時はJUDGE_MODELを使うテスト"""
        mock_config.ROUTER_MODEL = ""
        mock_config.JUDGE_MODEL = "judge-model"
        mock_gen.return_value = self._make_mock_response("none")
        _call_router_llm("テスト", None)

        call_args = mock_gen.call_args
        assert call_args.kwargs["model"] == "judge-model"

    @patch("ai.router._generate_content_with_retry")
    @patch("ai.router.get_model_name", return_value="default-model")
    @patch("ai.router._get_genai_client")
    @patch("ai.router.config")
    def test_default_model_fallback(self, mock_config, mock_client, mock_model, mock_gen):
        """ROUTER_MODELもJUDGE_MODELも未設定時はデフォルトモデルを使うテスト"""
        mock_config.ROUTER_MODEL = ""
        mock_config.JUDGE_MODEL = ""
        mock_gen.return_value = self._make_mock_response("none")
        _call_router_llm("テスト", None)

        call_args = mock_gen.call_args
        assert call_args.kwargs["model"] == "default-model"


class TestDetectToolModeIntegration:
    """detect_tool_mode の統合的な動作テスト"""

    @patch("ai.router._call_router_llm")
    @patch("ai.router.config")
    def test_exception_falls_back_to_function_calling(self, mock_config, mock_llm):
        """Router LLM呼び出しで例外が発生した場合はfunction_callingにフォールバック"""
        mock_config.ROUTER_ENABLED = True
        mock_llm.side_effect = Exception("API Error")
        result = detect_tool_mode("長めのメッセージでRouterを呼ぶはず")
        assert result == "function_calling"

    @patch("ai.router._call_router_llm", return_value="grounding")
    @patch("ai.router.config")
    def test_enabled_router_passes_context(self, mock_config, mock_llm):
        """contextが正しくRouter LLMに渡されるテスト"""
        mock_config.ROUTER_ENABLED = True
        detect_tool_mode("今日のニュースを教えて", context="会話のコンテキスト")
        mock_llm.assert_called_once_with("今日のニュースを教えて", "会話のコンテキスト")

    @patch("ai.router._call_router_llm", return_value="function_calling")
    @patch("ai.router.config")
    def test_tool_mode_passed_to_llm(self, mock_config, mock_llm):
        """detect_tool_modeがRouter LLMの結果をそのまま返すテスト"""
        mock_config.ROUTER_ENABLED = True
        result = detect_tool_mode("カッパーオアのレシピを調べて")
        assert result == "function_calling"
