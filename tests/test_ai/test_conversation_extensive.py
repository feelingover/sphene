"""
ai/conversation.py の広範なテスト
"""

# type: ignore
# mypy: ignore-errors

import json
import logging
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)

from ai.conversation import (
    Sphene,
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
        # load_system_prompt が例外を投げた場合、reload_system_prompt は False を返すか再スローする
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
        # role: user で始まるように調整
        sphene.input_list = [{"role": "system", "content": "System"}]
        for i in range(15):
            sphene.input_list.append({"role": "user", "content": f"User {i}"})
            sphene.input_list.append({"role": "assistant", "content": f"Asst {i}"})
        
        sphene.trim_conversation_history()
        
        # システムメッセージ(1) + 往復10回(20) = 21メッセージ
        assert len(sphene.input_list) == 21
        assert sphene.input_list[0]["role"] == "system"
        # 最初が assistant か user かを確認（trimのロジックでは user または tool_callsなしassistantを探す）
        assert sphene.input_list[1]["role"] in ["user", "assistant"]

    def test_handle_openai_error_mapping(self):
        """OpenAIエラーハンドリングのマッピングテスト"""
        sphene = Sphene("System")
        
        # 各エラータイプに対するユーザーメッセージを確認
        errors = [
            (AuthenticationError("auth", response=MagicMock(), body={}), "接続設定で問題"),
            (RateLimitError("rate", response=MagicMock(), body={}), "混み合ってる"),
            (APIConnectionError(request=MagicMock()), "接続で問題"),
            (APITimeoutError(request=MagicMock()), "時間内"), # "タイムアウト" は含まれていない
            (APIStatusError("status", response=MagicMock(status_code=502), body={}), "通信で予期せぬエラー"),
            (Exception("General Error"), "通信中に予期せぬエラー"),
        ]
        
        for err, expected_part in errors:
            msg = sphene._handle_openai_error(err)
            assert expected_part in msg

    @patch("ai.conversation.TOOL_FUNCTIONS")
    def test_execute_tool_calls_success(self, mock_tools):
        """ツール呼び出し実行の成功テスト"""
        mock_func = MagicMock(return_value="Tool Result")
        mock_tools.get.return_value = mock_func
        
        sphene = Sphene("System")
        
        mock_tool_call = MagicMock()
        mock_tool_call.function.name = "test_tool"
        mock_tool_call.function.arguments = '{"arg": "val"}'
        mock_tool_call.id = "call_123"
        
        results = sphene._execute_tool_calls([mock_tool_call])
        
        assert len(results) == 1
        assert results[0]["role"] == "tool"
        assert results[0]["content"] == "Tool Result"
        assert results[0]["tool_call_id"] == "call_123"
        mock_func.assert_called_once_with(arg="val")

    @patch("ai.conversation.TOOL_FUNCTIONS")
    def test_execute_tool_calls_json_error(self, mock_tools):
        """ツール引数のJSONエラーテスト"""
        mock_tools.get.return_value = MagicMock()
        sphene = Sphene("System")
        
        mock_tool_call = MagicMock()
        mock_tool_call.function.name = "test_tool"
        mock_tool_call.function.arguments = "invalid json"
        mock_tool_call.id = "call_err"
        
        results = sphene._execute_tool_calls([mock_tool_call])
        assert "パースに失敗" in results[0]["content"]

    @patch("ai.conversation.get_client")
    def test_call_with_tool_loop_max_rounds(self, mock_get_client):
        """ツール呼び出しの無限ループ防止テスト"""
        # 常にツール呼び出しを返すモック
        mock_msg = MagicMock()
        mock_tool_call = MagicMock()
        mock_tool_call.function.name = "loop_tool"
        mock_tool_call.function.arguments = "{}"
        mock_msg.tool_calls = [mock_tool_call]
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=mock_msg)]
        mock_get_client().chat.completions.create.return_value = mock_response
        
        sphene = Sphene("System")
        # 内部で実行される _execute_tool_calls をモック
        sphene._execute_tool_calls = MagicMock(return_value=[{"role": "tool", "content": "res", "tool_call_id": "id"}])
        
        success, msg = sphene._call_with_tool_loop()
        assert success is False
        assert "複雑すぎて" in msg
        # MAX_TOOL_CALL_ROUNDS (3) + 1 = 4 回呼ばれるはず
        assert mock_get_client().chat.completions.create.call_count == 4

    @patch("ai.conversation.load_system_prompt")
    @patch("ai.conversation.get_client")
    def test_generate_contextual_response_success(self, mock_get_client, mock_load_prompt):
        """コンテキスト付き応答生成の成功テスト"""
        mock_load_prompt.return_value = "System"
        mock_get_client().chat.completions.create.return_value.choices[0].message.content = "Contextual Answer"
        
        result = generate_contextual_response("Recent context", "Trigger")
        assert result == "Contextual Answer"

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

    @patch("requests.head")
    @patch("requests.get")
    def test_process_images_complete_failure(self, mock_get, mock_head):
        """画像処理が完全に失敗する場合のテスト"""
        mock_head.side_effect = Exception("Head Error")
        mock_get.side_effect = Exception("Get Error")
        
        sphene = Sphene("System")
        results = sphene._process_images(["https://bad.url/img.jpg"])
        
        # 失敗した場合は結果リストが空になる
        assert len(results) == 0

    def test_download_and_encode_image_extension_guessing(self):
        """MIMEタイプ推測のテスト"""
        sphene = Sphene("System")
        
        with patch("requests.get") as mock_get:
            mock_get.return_value.content = b"data"
            mock_get.return_value.headers = {}
            
            # .png
            res1 = sphene._download_and_encode_image("https://t.com/i.png")
            assert "image/png" in res1
            
            # .webp
            res2 = sphene._download_and_encode_image("https://t.com/i.webp")
            assert "image/webp" in res2
            
            # .gif
            res3 = sphene._download_and_encode_image("https://t.com/i.gif")
            assert "image/gif" in res3
            
            # 不明な拡張子はデフォルト image/jpeg
            res4 = sphene._download_and_encode_image("https://t.com/i.unknown")
            assert "image/jpeg" in res4
