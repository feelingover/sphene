"""ai/conversation.pyのテスト"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from ai.conversation import (
    MAX_CONVERSATION_AGE_MINUTES,
    MAX_CONVERSATION_TURNS,
    Sphene,
    load_system_prompt,
    user_conversations,
)


def test_load_system_prompt() -> None:
    """システムプロンプトの読み込みをテスト"""
    # テスト用のシステムプロンプトを設定
    test_content = "これはテスト用のシステムプロンプトです。\n"
    test_filename = "test_system.txt"

    # 環境変数とファイル読み込みをパッチ
    with patch("ai.conversation.SYSTEM_PROMPT_FILENAME", test_filename), patch(
        "ai.conversation.Path.read_text", return_value=test_content
    ) as mock_read:
        result = load_system_prompt()

        # 読み込みが1回だけ呼ばれていることを確認
        mock_read.assert_called_once()
        assert result == test_content.strip()


def test_sphene_initialization() -> None:
    """Spheneクラスの初期化をテスト"""
    system_text = "テストシステムプロンプト"
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
        mock_create.assert_called_with(model="gpt-4o-mini", messages=sphene.input_list)

        # 応答が正しく処理されたか
        assert response == "これはテスト応答です。"

        # 会話履歴が更新されたか
        assert len(sphene.input_list) == 3  # システム + ユーザー + アシスタント
        assert sphene.input_list[1]["role"] == "user"
        assert sphene.input_list[1]["content"] == "こんにちは"
        assert sphene.input_list[2]["role"] == "assistant"
        assert sphene.input_list[2]["content"] == "これはテスト応答です。"


def test_input_message_error_handling() -> None:
    """メッセージ処理のエラーハンドリングをテスト"""
    sphene = Sphene(system_setting="テスト")

    # 無効な入力のケース
    assert sphene.input_message("") is None
    assert sphene.input_message(None) is None  # type: ignore

    # APIエラーのケース
    with patch("ai.conversation.aiclient.chat.completions.create") as mock_create:
        mock_create.side_effect = Exception("API Error")

        response = sphene.input_message("APIエラーテスト")
        assert response is None


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
