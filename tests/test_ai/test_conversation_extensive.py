"""
ai/conversation.py の広範なテスト
"""

# type: ignore
# mypy: ignore-errors

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from google.genai import types

from ai.conversation import (
    Sphene,
    _call_genai_with_tools,
    _execute_tool_calls,
    _handle_api_error,
    cleanup_expired_conversations,
    generate_contextual_response,
    load_system_prompt,
    reload_system_prompt,
    user_conversations,
    _prompt_cache,
)


class TestConversationExtensive:
    """Spheneクラスと関連機能の広範なテスト"""

    def setup_method(self):
        """テストごとのセットアップ"""
        _prompt_cache.clear()
        user_conversations.clear()

    @patch("ai.conversation._load_prompt_from_local")
    def test_load_system_prompt_cache(self, mock_load_local):
        """システムプロンプトのキャッシュ動作テスト"""
        mock_load_local.return_value = "Custom Prompt"

        # 1回目：ロードされる
        p1 = load_system_prompt()
        assert p1 == "Custom Prompt"
        assert mock_load_local.call_count == 1

        # 2回目：キャッシュから返される
        p2 = load_system_prompt()
        assert p2 == "Custom Prompt"
        assert mock_load_local.call_count == 1

        # 強制リロード
        p3 = load_system_prompt(force_reload=True)
        assert p3 == "Custom Prompt"
        assert mock_load_local.call_count == 2

    @patch("ai.conversation._load_prompt_from_local")
    def test_reload_system_prompt_success(self, mock_load_local):
        """プロンプト再読み込み成功テスト"""
        mock_load_local.return_value = "Reloaded Prompt"
        result = reload_system_prompt()
        assert result is True
        assert load_system_prompt() == "Reloaded Prompt"

    @patch("ai.conversation.load_system_prompt")
    def test_reload_system_prompt_failure(self, mock_load_prompt):
        """プロンプト再読み込み失敗テスト"""
        mock_load_prompt.side_effect = Exception("Load Error")

        # fail_on_error=False
        result = reload_system_prompt(fail_on_error=False)
        assert result is False

        # fail_on_error=True
        with pytest.raises(Exception):
            reload_system_prompt(fail_on_error=True)

    def test_trim_conversation_history_safety(self):
        """トリミング時の安全な切断ポイントのテスト"""
        sphene = Sphene("System")

        # 往復上限を超えるメッセージを追加
        for i in range(30):
            content = MagicMock()
            content.role = "user" if i % 2 == 0 else "model"
            sphene.history.append(content)

        sphene.trim_conversation_history()

        # MAX_CONVERSATION_TURNS * 2 以下であること
        assert len(sphene.history) <= 20
        # 先頭がuserメッセージであること
        assert sphene.history[0].role == "user"

    def test_handle_api_error_mapping(self):
        """APIエラーハンドリングのマッピングテスト"""
        errors = [
            (Exception("404 Not Found"), "指定されたAIモデル"),
            (Exception("429 Too Many Requests"), "混み合ってる"),
            (Exception("General Error"), "通信中にエラー"),
        ]

        for err, expected_part in errors:
            msg = _handle_api_error(err)
            assert expected_part in msg

    @patch("ai.conversation.TOOL_FUNCTIONS")
    def test_execute_tool_calls_success(self, mock_tools):
        """ツール呼び出し実行の成功テスト"""
        mock_func = MagicMock(return_value={"result": "success"})
        mock_tools.get.return_value = mock_func

        mock_call = MagicMock()
        mock_call.name = "test_tool"
        mock_call.args = {"arg": "val"}

        results = _execute_tool_calls([mock_call])

        assert len(results) == 1
        mock_func.assert_called_once_with(arg="val")

    @patch("ai.conversation.TOOL_FUNCTIONS")
    def test_execute_tool_calls_unknown_function(self, mock_tools):
        """未知のツール関数の呼び出しテスト"""
        mock_tools.get.return_value = None

        mock_call = MagicMock()
        mock_call.name = "unknown_tool"
        mock_call.args = {}

        results = _execute_tool_calls([mock_call])

        assert len(results) == 1
        # エラーは発生せず、結果が返される

    @patch("ai.conversation.TOOL_FUNCTIONS")
    def test_execute_tool_calls_function_error(self, mock_tools):
        """ツール関数がエラーを投げた場合のテスト"""
        mock_func = MagicMock(side_effect=Exception("ツール内部エラー"))
        mock_tools.get.return_value = mock_func

        mock_call = MagicMock()
        mock_call.name = "error_tool"
        mock_call.args = {"key": "value"}

        results = _execute_tool_calls([mock_call])

        assert len(results) == 1
        # エラーは捕捉されて結果が返される

    @patch("ai.conversation.get_model_name")
    @patch("ai.conversation._get_genai_client")
    def test_call_genai_with_tools_max_rounds(
        self, mock_get_client, mock_model_name
    ):
        """ツール呼び出しの無限ループ防止テスト"""
        mock_model_name.return_value = "gemini-2.5-flash"

        # 常にfunction_callを返すレスポンスを作成
        mock_fc = MagicMock()
        mock_fc.name = "loop_tool"
        mock_fc.args = {}

        mock_part = MagicMock()
        mock_part.function_call = mock_fc
        mock_part.text = None

        mock_content = MagicMock()
        mock_content.parts = [mock_part]

        mock_response = MagicMock()
        mock_response.candidates = [MagicMock(content=mock_content)]
        mock_get_client.return_value.models.generate_content.return_value = (
            mock_response
        )

        # 実際のtypes.Partオブジェクトを使う（pydanticバリデーション対策）
        fn_response_part = types.Part.from_function_response(
            name="loop_tool", response={"result": "ok"}
        )
        with patch(
            "ai.conversation._execute_tool_calls",
            return_value=[fn_response_part],
        ):
            success, msg, _ = _call_genai_with_tools([], "system")

        assert success is False
        assert "複雑すぎて" in msg

    @patch("ai.conversation._call_genai_with_tools")
    def test_generate_contextual_response_success(self, mock_call):
        """コンテキスト付き応答生成の成功テスト"""
        mock_call.return_value = (True, "Contextual Answer", [])

        result = generate_contextual_response("Recent context", "Trigger")
        assert result == "Contextual Answer"

    @patch("ai.conversation._call_genai_with_tools")
    def test_generate_contextual_response_failure(self, mock_call):
        """コンテキスト付き応答生成の失敗テスト"""
        mock_call.return_value = (False, "エラー", [])

        result = generate_contextual_response("Recent context", "Trigger")
        assert result is None

    def test_cleanup_expired_conversations(self):
        """期限切れ会話のクリーンアップテスト"""
        # 有効な会話
        s1 = Sphene("S1")
        user_conversations["u1"] = s1

        # 期限切れの会話
        s2 = Sphene("S2")
        s2.last_interaction = datetime.now() - timedelta(hours=1)
        user_conversations["u2"] = s2

        count = cleanup_expired_conversations()
        assert count == 1
        assert "u1" in user_conversations
        assert "u2" not in user_conversations

    @patch("ai.conversation.get_model_name")
    @patch("ai.conversation._get_genai_client")
    def test_call_genai_with_tools_text_response(
        self, mock_get_client, mock_model_name
    ):
        """テキスト応答の正常処理テスト"""
        mock_model_name.return_value = "gemini-2.5-flash"

        # テキスト応答のみを返すレスポンス
        mock_part = MagicMock()
        mock_part.function_call = None
        mock_part.text = "Hello from GenAI"

        mock_content = MagicMock()
        mock_content.parts = [mock_part]

        mock_response = MagicMock()
        mock_response.candidates = [MagicMock(content=mock_content)]
        mock_get_client.return_value.models.generate_content.return_value = (
            mock_response
        )

        success, text, history = _call_genai_with_tools([], "system")

        assert success is True
        assert text == "Hello from GenAI"

    @patch("ai.conversation.get_model_name")
    @patch("ai.conversation._get_genai_client")
    def test_call_genai_with_tools_empty_candidates(
        self, mock_get_client, mock_model_name
    ):
        """空のcandidatesが返された場合のテスト"""
        mock_model_name.return_value = "gemini-2.5-flash"

        mock_response = MagicMock()
        mock_response.candidates = []
        mock_get_client.return_value.models.generate_content.return_value = (
            mock_response
        )

        success, text, _ = _call_genai_with_tools([], "system")

        assert success is False
        assert "空" in text

    @patch("ai.conversation.get_model_name")
    @patch("ai.conversation._get_genai_client")
    def test_call_genai_with_grounding_config(
        self, mock_get_client, mock_model_name
    ):
        """Groundingが有効な時に正しいツール構成でSDKが呼ばれるかテスト"""
        mock_model_name.return_value = "gemini-3-flash"
        
        # モックの戻り値設定
        mock_response = MagicMock()
        mock_response.candidates = [MagicMock()]
        mock_response.candidates[0].content.parts = [types.Part.from_text(text="response")]
        mock_get_client.return_value.models.generate_content.return_value = mock_response

        with patch("ai.conversation.ENABLE_GOOGLE_SEARCH_GROUNDING", True):
            _call_genai_with_tools([], "system_instruction")
            
            # generate_content の呼び出し引数を確認
            args, kwargs = mock_get_client.return_value.models.generate_content.call_args
            config = kwargs["config"]
            
            # toolsの中にgoogle_searchが含まれていること
            grounding_tools = [t for t in config.tools if hasattr(t, "google_search") and t.google_search]
            assert len(grounding_tools) == 1
            assert isinstance(grounding_tools[0].google_search, types.GoogleSearch)

    @patch("ai.conversation._call_genai_with_tools")
    def test_input_message_includes_tool_instruction(self, mock_call):
        """通常の会話入力時にツール使用指示が含まれているかテスト"""
        mock_call.return_value = (True, "Answer", [])
        sphene = Sphene("Base Prompt")
        
        sphene.input_message("Hello")
        
        # _call_genai_with_tools の引数を確認
        _, kwargs = mock_call.call_args
        instruction = kwargs["system_instruction"]
        assert "Base Prompt" in instruction
        assert "積極的にツールを使って調べてね" in instruction

    @patch("ai.conversation._call_genai_with_tools")
    def test_generate_contextual_response_includes_tool_instruction(self, mock_call):
        """自律応答生成時にツール使用指示が含まれているかテスト"""
        mock_call.return_value = (True, "Answer", [])
        
        generate_contextual_response("Context", "Trigger", system_prompt="System Prompt")
        
        # _call_genai_with_tools の引数を確認
        _, kwargs = mock_call.call_args
        instruction = kwargs["system_instruction"]
        assert "System Prompt" in instruction
        assert "積極的にツールを使って調べてね" in instruction

    @patch("ai.conversation.get_model_name")
    @patch("ai.conversation._get_genai_client")
    def test_call_genai_with_grounding_metadata(
        self, mock_get_client, mock_model_name
    ):
        """Groundingメタデータが含まれるレスポンスの処理テスト"""
        mock_model_name.return_value = "gemini-3-flash"

        candidate = MagicMock()
        candidate.content.parts = [types.Part.from_text(text="grounded response")]
        candidate.grounding_metadata = MagicMock() # メタデータあり
        
        mock_response = MagicMock()
        mock_response.candidates = [candidate]
        mock_get_client.return_value.models.generate_content.return_value = mock_response

        success, text, _ = _call_genai_with_tools([], "system")

        assert success is True
        assert text == "grounded response"
        # ログ出力されるはず（副作用の検証は省略するが、クラッシュしないことが重要）
