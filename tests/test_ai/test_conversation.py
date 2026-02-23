"""ai/conversation.pyのテスト"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from google.genai import errors as genai_errors
from google.api_core import exceptions as google_exceptions

from ai.conversation import (
    MAX_CONVERSATION_AGE_MINUTES,
    MAX_CONVERSATION_TURNS,
    Sphene,
    _handle_api_error,
    load_system_prompt,
    channel_conversations,
)

# conftest.py で load_system_prompt は自動モックされるため、
# 個別のテストは不要（またはモックの上書きテストが必要な場合のみ実装）


def test_sphene_initialization() -> None:
    """Spheneクラスの初期化をテスト"""
    system_text = "テスト用のシステムプロンプト"
    sphene = Sphene(system_setting=system_text)

    assert sphene.system_prompt == system_text
    assert len(sphene.history) == 0
    assert sphene.last_interaction is not None


def test_is_expired() -> None:
    """会話の期限切れ判定をテスト"""
    sphene = Sphene(system_setting="テスト")

    # 期限切れでない場合
    assert not sphene.is_expired()

    # 期限切れの場合
    old_time = datetime.now() - timedelta(minutes=MAX_CONVERSATION_AGE_MINUTES + 5)
    sphene.last_interaction = old_time
    assert sphene.is_expired()

    # last_interactionがNoneの場合
    sphene.last_interaction = None
    assert not sphene.is_expired()


def test_update_interaction_time() -> None:
    """会話時間の更新をテスト"""
    sphene = Sphene(system_setting="テスト")
    old_time = sphene.last_interaction

    # 少し待ってから更新
    with patch("ai.conversation.datetime") as mock_datetime:
        new_time = datetime.now() + timedelta(minutes=1)
        mock_datetime.now.return_value = new_time

        sphene.update_interaction_time()
        assert sphene.last_interaction == new_time
        assert sphene.last_interaction != old_time


def test_trim_conversation_history() -> None:
    """会話履歴の整理をテスト"""
    sphene = Sphene(system_setting="テスト")

    # 整理が必要なほど長い会話履歴を作成
    for i in range(MAX_CONVERSATION_TURNS * 3):
        content = MagicMock()
        content.role = "user" if i % 2 == 0 else "model"
        sphene.history.append(content)

    before_count = len(sphene.history)
    assert before_count > MAX_CONVERSATION_TURNS * 2

    sphene.trim_conversation_history()

    # 整理後のメッセージ数を検証
    assert len(sphene.history) <= MAX_CONVERSATION_TURNS * 2
    # 先頭がuserメッセージであること
    assert sphene.history[0].role == "user"


def test_input_message() -> None:
    """ユーザーメッセージの処理と応答をテスト"""
    sphene = Sphene(system_setting="テスト")

    with patch("ai.conversation._call_genai_with_tools") as mock_call:
        # _call_genai_with_tools は (success, response_text, updated_history) を返す
        mock_history = [MagicMock(), MagicMock()]
        mock_call.return_value = (True, "これはテスト応答です。", mock_history)

        response = sphene.input_message("こんにちは")

        assert response == "これはテスト応答です。"
        mock_call.assert_called_once()
        # 履歴が更新されていること
        assert sphene.history == mock_history


# --- エラーハンドリングテスト ---


def test_input_message_invalid_input() -> None:
    """無効な入力に対するエラーハンドリングをテスト"""
    sphene = Sphene(system_setting="テスト")
    assert sphene.input_message("") is None
    assert sphene.input_message(None) is None  # type: ignore
    assert sphene.input_message("   ") is None  # 空白のみ


def test_handle_api_error_404() -> None:
    """404エラー時のメッセージをテスト"""
    error = genai_errors.APIError(code=404, response_json={"error": "not found"})
    msg = _handle_api_error(error)
    assert "指定されたAIモデル" in msg


def test_handle_api_error_404_google_exception() -> None:
    """google.api_core.exceptions.NotFoundの場合のメッセージをテスト"""
    error = google_exceptions.NotFound("Model not found")
    msg = _handle_api_error(error)
    assert "指定されたAIモデル" in msg


def test_handle_api_error_429() -> None:
    """429エラー（レート制限）時のメッセージをテスト"""
    error = genai_errors.APIError(code=429, response_json={"error": "rate limited"})
    msg = _handle_api_error(error)
    assert "混み合ってる" in msg


def test_handle_api_error_429_google_exception() -> None:
    """google.api_core.exceptions.TooManyRequestsの場合のメッセージをテスト"""
    error = google_exceptions.TooManyRequests("Rate limited")
    msg = _handle_api_error(error)
    assert "混み合ってる" in msg


def test_handle_api_error_generic() -> None:
    """汎用APIエラー時のメッセージをテスト"""
    msg = _handle_api_error(Exception("Some unexpected error"))
    assert "通信中にエラー" in msg


def test_input_message_api_error() -> None:
    """API呼び出しエラー時の応答をテスト"""
    sphene = Sphene(system_setting="テスト")

    with patch("ai.conversation._call_genai_with_tools") as mock_call:
        mock_call.return_value = (False, "ごめん！AIとの通信中にエラーが発生しちゃった...😢", [])

        response = sphene.input_message("APIエラーテスト")

        assert response is not None
        assert "エラー" in response


def test_input_message_unexpected_exception() -> None:
    """予期せぬ例外が発生した場合のテスト"""
    sphene = Sphene(system_setting="テスト")

    with patch("ai.conversation._call_genai_with_tools") as mock_call:
        mock_call.side_effect = RuntimeError("予期せぬエラー")

        response = sphene.input_message("例外テスト")

        assert response is not None
        assert "予期せぬエラー" in response


# --- 画像処理テスト ---


def test_input_message_with_images() -> None:
    """画像付きメッセージの処理をテスト"""
    sphene = Sphene(system_setting="テスト")

    with patch("ai.conversation._call_genai_with_tools") as mock_call, patch(
        "ai.conversation.requests.get"
    ) as mock_get:
        # requests.getのコンテキストマネージャモック
        mock_resp = MagicMock()
        mock_resp.headers = {
            "Content-Type": "image/jpeg",
            "Content-Length": "1000",
        }
        mock_resp.iter_content.return_value = [b"image_data"]
        mock_resp.raise_for_status = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_get.return_value = mock_resp

        mock_call.return_value = (
            True,
            "画像を確認しました",
            [MagicMock(), MagicMock()],
        )

        response = sphene.input_message(
            "この画像は何？", image_urls=["https://cdn.discordapp.com/image.jpg"]
        )

        assert response == "画像を確認しました"
        mock_call.assert_called_once()


def test_input_message_with_disallowed_image_domain() -> None:
    """許可されていないドメインの画像URLをスキップするテスト"""
    sphene = Sphene(system_setting="テスト")

    with patch("ai.conversation._call_genai_with_tools") as mock_call, patch(
        "ai.conversation.requests.get"
    ) as mock_get:
        mock_call.return_value = (True, "テスト応答", [MagicMock()])

        response = sphene.input_message(
            "テスト", image_urls=["https://evil.com/image.jpg"]
        )

        # requests.getは呼ばれないこと（ドメインが許可されていない）
        mock_get.assert_not_called()
        assert response == "テスト応答"


# --- ユーザー別会話テスト ---


def test_channel_conversations() -> None:
    """チャンネル別会話管理をテスト"""
    # デフォルトで新しい会話が作成されるか
    channel_id = "test_channel_123"
    conversation = channel_conversations[channel_id]
    assert isinstance(conversation, Sphene)

    # 同じチャンネルIDで同じ会話インスタンスが返されるか
    same_conversation = channel_conversations[channel_id]
    assert conversation is same_conversation

    # 別のチャンネルIDで別の会話インスタンスが作成されるか
    another_channel_id = "another_channel_456"
    another_conversation = channel_conversations[another_channel_id]
    assert another_conversation is not conversation


def test_load_system_prompt_edge_cases(mock_load_system_prompt: MagicMock) -> None:
    """システムプロンプト読み込みのエッジケース"""
    # conftest.pyで自動モックされたload_system_promptを一時的に元の実装に戻す
    with patch("ai.conversation.load_system_prompt", side_effect=load_system_prompt):
        # 1. ファイル内容が空の場合
        with patch("pathlib.Path.read_text", return_value=""):
            prompt = load_system_prompt(force_reload=True)
            assert prompt == "あなたは役立つAIアシスタントです。"

        # 2. ファイルの権限エラー
        with patch("pathlib.Path.read_text", side_effect=PermissionError("権限なし")):
            prompt = load_system_prompt(force_reload=True)
            assert prompt == "あなたは役立つAIアシスタントです。"

        # 3. ローカルから正常に読み込める場合
        with patch(
            "ai.conversation._load_prompt_from_local",
            return_value="ローカルプロンプト",
        ):
            prompt = load_system_prompt(force_reload=True)
            assert prompt == "ローカルプロンプト"


def test_input_message_with_non_string_input() -> None:
    """文字列以外の入力に対する堅牢性テスト"""
    sphene = Sphene(system_setting="テスト")

    invalid_inputs = [
        123,  # 整数
        ["テスト"],  # リスト
        {"message": "テスト"},  # 辞書
        0,  # ゼロ
        False,  # ブール値
    ]

    for invalid in invalid_inputs:
        assert sphene.input_message(invalid) is None  # type: ignore


def test_generate_short_ack_success() -> None:
    """generate_short_ack 正常系"""
    with patch("ai.conversation._get_genai_client") as mock_client_fn, \
         patch("ai.conversation.get_model_name", return_value="test-model"):
        mock_part = MagicMock()
        mock_part.text = "そだねー"

        mock_content = MagicMock()
        mock_content.parts = [mock_part]

        mock_candidate = MagicMock()
        mock_candidate.content = mock_content

        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_client_fn.return_value = mock_client

        from ai.conversation import generate_short_ack
        result = generate_short_ack(
            channel_context="User1: 今日疲れた",
            trigger_message="ほんとねー",
        )

        assert result == "そだねー"


def test_generate_short_ack_error() -> None:
    """generate_short_ack エラー時はNone"""
    with patch("ai.conversation._get_genai_client") as mock_client_fn, \
         patch("ai.conversation.get_model_name", return_value="test-model"):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("API error")
        mock_client_fn.return_value = mock_client

        from ai.conversation import generate_short_ack
        result = generate_short_ack(
            channel_context="User1: hello",
            trigger_message="hi",
        )

        assert result is None


def test_generate_content_retry_logic() -> None:
    """_generate_content_with_retryのリトライロジックをテスト"""
    from ai.conversation import _generate_content_with_retry
    from google.api_core import exceptions as google_exceptions
    
    # 429エラーを3回投げた後に成功するケース
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = [
        google_exceptions.TooManyRequests("Busy"),
        google_exceptions.TooManyRequests("Busy"),
        google_exceptions.TooManyRequests("Busy"),
        "Success"
    ]
    
    # tenacityのsleepをスキップ
    with patch("time.sleep", return_value=None):
        result = _generate_content_with_retry(
            client=mock_client,
            model="test-model",
            contents=[],
            config=MagicMock()
        )
        
    assert result == "Success"
    assert mock_client.models.generate_content.call_count == 4


def test_generate_content_retry_on_genai_apierror() -> None:
    """google.genai.errors.APIError に対するリトライをテスト"""
    from ai.conversation import _generate_content_with_retry
    from google.genai import errors as genai_errors
    
    # 429エラーを投げた後に成功するケース
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = [
        genai_errors.APIError(code=429, response_json={"error": {"code": 429, "message": "Rate limit"}}),
        "Success"
    ]
    
    with patch("time.sleep", return_value=None):
        result = _generate_content_with_retry(
            client=mock_client,
            model="test-model",
            contents=[],
            config=MagicMock()
        )
        
    assert result == "Success"
    assert mock_client.models.generate_content.call_count == 2


# --- relevant_facts パラメータのテスト ---


def test_input_message_with_relevant_facts() -> None:
    """relevant_facts が context_section に含まれること"""
    sphene = Sphene(system_setting="テストプロンプト")

    with patch("ai.conversation._call_genai_with_tools") as mock_call:
        mock_call.return_value = (True, "テスト応答", [MagicMock()])
        sphene.input_message(
            "こんにちは",
            relevant_facts="【関連する過去の記憶】\n- AさんはRustを始めた",
        )

        mock_call.assert_called_once()
        call_kwargs = mock_call.call_args
        system_instruction = call_kwargs[1]["system_instruction"]
        assert "【関連する過去の記憶】" in system_instruction
        assert "AさんはRustを始めた" in system_instruction


def test_input_message_empty_relevant_facts_not_injected() -> None:
    """relevant_facts が空の場合、context_section に余分なテキストが入らないこと"""
    sphene = Sphene(system_setting="テストプロンプト")

    with patch("ai.conversation._call_genai_with_tools") as mock_call:
        mock_call.return_value = (True, "テスト応答", [MagicMock()])
        sphene.input_message("こんにちは", relevant_facts="")

        call_kwargs = mock_call.call_args
        system_instruction = call_kwargs[1]["system_instruction"]
        assert "【関連する過去の記憶】" not in system_instruction
