"""ai/conversation.pyのテスト"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

# OpenAIエラータイプをインポート
from openai import APIConnectionError  # インポートを維持
from openai import APITimeoutError  # インポートを維持
from openai import (
    APIError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)

from ai.conversation import (
    MAX_CONVERSATION_AGE_MINUTES,
    MAX_CONVERSATION_TURNS,
    Sphene,
    user_conversations,
)

# conftest.py で load_system_prompt は自動モックされるため、
# 個別のテストは不要（またはモックの上書きテストが必要な場合のみ実装）


def test_sphene_initialization() -> None:
    """Spheneクラスの初期化をテスト"""
    # conftestのautouse fixtureによりload_system_promptはモックされている
    system_text = "テスト用のシステムプロンプト from fixture"
    sphene = Sphene(system_setting=system_text)

    # 初期状態の検証
    assert sphene.system["role"] == "system"
    assert sphene.system["content"] == system_text
    assert len(sphene.input_list) == 1  # システムプロンプトのみ
    assert sphene.input_list[0] == sphene.system
    assert len(sphene.logs) == 0
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
    sphene = Sphene(system_setting="テストシステム")

    # 整理が必要なほど長い会話履歴を作成
    max_messages = 1 + (MAX_CONVERSATION_TURNS * 2)

    # システムメッセージは既に存在するので、それ以外のメッセージを追加
    for i in range(max_messages * 2):  # 上限の2倍のメッセージを追加
        if i % 2 == 0:
            sphene.input_list.append(
                {"role": "user", "content": f"テストメッセージ{i}"}
            )
        else:
            sphene.input_list.append({"role": "assistant", "content": f"応答{i}"})

    # 整理前のメッセージ数を記録
    before_count = len(sphene.input_list)
    assert before_count > max_messages

    # システムメッセージを記録
    system_message = sphene.input_list[0]

    # 会話履歴を整理
    sphene.trim_conversation_history()

    # 整理後のメッセージ数を検証
    assert len(sphene.input_list) == max_messages

    # システムメッセージが保持されているか確認
    assert sphene.input_list[0] == system_message

    # 最新のメッセージが保持されているか確認
    # ロールだけチェックして内容は型だけ確認する
    last_messages = sphene.input_list[-2:]
    assert last_messages[0]["role"] == "user"
    assert "content" in last_messages[0]

    assert last_messages[1]["role"] == "assistant"
    assert "content" in last_messages[1]


def test_input_message(mock_openai_response: MagicMock) -> None:
    """ユーザーメッセージの処理と応答をテスト"""
    sphene = Sphene(system_setting="テスト")

    # OpenAI APIのモック
    with patch("ai.conversation.aiclient.chat.completions.create") as mock_create:
        mock_create.return_value = mock_openai_response

        # メッセージ処理
        response = sphene.input_message("こんにちは")

        # APIが正しく呼び出されたか
        mock_create.assert_called_once()
        # モデル名のチェックは環境に依存するので除外し、代わりにミニマルなチェックを行う
        call_args = mock_create.call_args[1]  # キーワード引数を取得
        assert "model" in call_args  # modelパラメータが存在することを確認
        assert (
            call_args["messages"] == sphene.input_list
        )  # messagesが正しく渡されていることを確認

        # 応答が正しく処理されたか
        assert response == "これはテスト応答です。"

        # 会話履歴が更新されたか
        assert len(sphene.input_list) == 3  # システム + ユーザー + アシスタント
        assert sphene.input_list[1]["role"] == "user"
        assert sphene.input_list[1]["content"] == "こんにちは"
        assert sphene.input_list[2]["role"] == "assistant"
        assert sphene.input_list[2]["content"] == "これはテスト応答です。"


# --- エラーハンドリングテスト ---


def test_input_message_invalid_input() -> None:
    """無効な入力に対するエラーハンドリングをテスト"""
    sphene = Sphene(system_setting="テスト")
    assert sphene.input_message("") is None
    assert sphene.input_message(None) is None  # type: ignore
    assert sphene.input_message("   ") is None  # 空白のみ


# parametrizeを使って複数のAPIエラーケースをテスト
@pytest.mark.parametrize(
    "error_to_raise, expected_message_part",
    [
        (
            AuthenticationError("Invalid API key", response=MagicMock(), body={}),
            "接続設定で問題",
        ),
        (
            PermissionDeniedError("Permission denied", response=MagicMock(), body={}),
            "権限がないみたい",
        ),
        (
            NotFoundError("Model not found", response=MagicMock(), body={}),
            "指定されたAIモデル",
        ),
        (
            RateLimitError("Rate limit exceeded", response=MagicMock(), body={}),
            "混み合ってるみたい",
        ),
        # APIConnectionError and APITimeoutError are tested separately below
        (
            InternalServerError("Server error", response=MagicMock(), body={}),
            "AI側で一時的な問題",
        ),
        (
            BadRequestError("Bad request", response=MagicMock(), body={}),
            "AIとの通信で予期せぬエラー",
        ),
        (
            APIError(message="Generic API error", request=MagicMock(), body=None),
            "やり取りでエラー",
        ),
        (
            Exception("Some unexpected error"),
            "予期せぬエラーが発生",
        ),  # その他のException
    ],
)
def test_input_message_api_errors(
    error_to_raise: Exception, expected_message_part: str
) -> None:
    """各種APIエラー発生時の応答メッセージをテスト"""
    sphene = Sphene(system_setting="テスト")

    with patch("ai.conversation.aiclient.chat.completions.create") as mock_create:
        mock_create.side_effect = error_to_raise

        response = sphene.input_message("APIエラーテスト")

        assert response is not None
        # エラーメッセージの一部が含まれているかを確認
        assert expected_message_part in response


def test_input_message_api_connection_error() -> None:
    """APIConnectionError発生時の応答メッセージをテスト"""
    sphene = Sphene(system_setting="テスト")
    # APIConnectionError requires 'request' keyword argument
    error_to_raise = APIConnectionError(request=MagicMock())
    expected_message_part = "接続で問題"

    with patch("ai.conversation.aiclient.chat.completions.create") as mock_create:
        mock_create.side_effect = error_to_raise
        response = sphene.input_message("API接続エラーテスト")
        assert response is not None
        assert expected_message_part in response


def test_input_message_api_timeout_error() -> None:
    """APITimeoutError発生時の応答メッセージをテスト"""
    sphene = Sphene(system_setting="テスト")
    # APITimeoutError requires 'request' positional argument
    error_to_raise = APITimeoutError(MagicMock())  # Pass request as positional arg
    expected_message_part = "AIとの接続で問題"

    with patch("ai.conversation.aiclient.chat.completions.create") as mock_create:
        mock_create.side_effect = error_to_raise
        response = sphene.input_message("APIタイムアウトテスト")
        assert response is not None
        assert expected_message_part in response


# --- 画像処理テスト ---


def test_process_images(
    mock_requests_head: MagicMock,
    mock_requests_get: MagicMock,
    mock_base64_encode: MagicMock,
) -> None:
    """画像処理のハイブリッドアプローチをテスト"""
    sphene = Sphene(system_setting="テスト")

    # URL方式のケース
    mock_requests_head.return_value.status_code = 200
    images = sphene._process_images(["https://test.com/image1.jpg"])
    assert len(images) == 1
    assert images[0]["type"] == "image_url"
    assert images[0]["image_url"]["url"] == "https://test.com/image1.jpg"

    # Base64方式へのフォールバックケース
    mock_requests_head.return_value.status_code = 404
    mock_base64_encode.return_value = b"encoded_data"

    images = sphene._process_images(["https://test.com/image2.jpg"])
    assert len(images) == 1
    assert images[0]["type"] == "image_url"
    assert "data:image/jpeg;base64," in images[0]["image_url"]["url"]


def test_download_and_encode_image(
    mock_requests_get: MagicMock, mock_base64_encode: MagicMock
) -> None:
    """画像ダウンロードとBase64エンコードをテスト"""
    sphene = Sphene(system_setting="テスト")

    # 通常のケース（Content-Typeあり）
    mock_requests_get.return_value.headers = {"Content-Type": "image/png"}
    mock_base64_encode.return_value = b"encoded_png_data"

    result = sphene._download_and_encode_image("https://test.com/image.png")
    assert result == "data:image/png;base64,encoded_png_data"

    # Content-Typeなしで拡張子から推測するケース
    mock_requests_get.return_value.headers = {}
    result = sphene._download_and_encode_image("https://test.com/image.jpg")
    assert result == "data:image/jpeg;base64,encoded_png_data"


def test_input_message_with_images(
    mock_openai_response: MagicMock, mock_requests_head: MagicMock
) -> None:
    """画像付きメッセージの処理をテスト"""
    sphene = Sphene(system_setting="テスト")

    with patch(
        "ai.conversation.aiclient.chat.completions.create"
    ) as mock_create, patch.object(sphene, "_process_images") as mock_process:

        # 画像処理の結果をモック
        mock_process.return_value = [
            {"type": "image_url", "image_url": {"url": "https://test.com/image.jpg"}}
        ]

        mock_create.return_value = mock_openai_response

        # 画像付きメッセージの処理
        response = sphene.input_message(
            "これは画像テストです", ["https://test.com/image.jpg"]
        )

        # プロセスが呼ばれたことを確認
        mock_process.assert_called_once_with(["https://test.com/image.jpg"])

        # APIが呼ばれたことを確認
        mock_create.assert_called_once()

        # 正しい応答が返されたことを確認
        assert response == "これはテスト応答です。"

        # ユーザーメッセージが正しく追加されたことを確認
        assert len(sphene.input_list) == 3  # システム + ユーザー + アシスタント
        assert "content" in sphene.input_list[1]  # ユーザーメッセージのcontentを確認


# --- ユーザー別会話テスト ---


def test_user_conversations() -> None:
    """ユーザー別会話管理をテスト"""
    # デフォルトで新しい会話が作成されるか
    user_id = "test_user_123"
    conversation = user_conversations[user_id]
    assert isinstance(conversation, Sphene)

    # 同じユーザーIDで同じ会話インスタンスが返されるか
    same_conversation = user_conversations[user_id]
    assert conversation is same_conversation

    # 別のユーザーIDで別の会話インスタンスが作成されるか
    another_user_id = "another_user_456"
    another_conversation = user_conversations[another_user_id]
    assert another_conversation is not conversation
