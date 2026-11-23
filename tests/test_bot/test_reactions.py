"""
リアクション処理のテスト
特にスタンプによる翻訳機能のテスト
"""

# type: ignore
# mypy: ignore-errors

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from bot.events import (
    get_message_type,
    send_translation_response,
    translate_and_reply,
)


class TestMessageTypeDetection:
    """メッセージタイプ判定機能のテスト"""

    def test_get_message_type_normal(self):
        """通常メッセージのタイプ判定テスト"""
        # 通常メッセージのモック
        message = MagicMock()
        message.reference = None
        message.thread = None

        # 関数実行
        result = get_message_type(message)

        # アサーション
        assert result == "normal"

    def test_get_message_type_reply(self):
        """リプライメッセージのタイプ判定テスト"""
        # リプライメッセージのモック
        message = MagicMock()
        message.reference = MagicMock()  # リプライがある
        message.thread = None

        # 関数実行
        result = get_message_type(message)

        # アサーション
        assert result == "reply"

    def test_get_message_type_thread(self):
        """スレッドメッセージのタイプ判定テスト"""
        # スレッド内メッセージのモック（channel が discord.Thread であることで判定）
        message = MagicMock()
        message.reference = None
        message.channel = MagicMock(spec=discord.Thread)

        # 関数実行
        result = get_message_type(message)

        # アサーション
        assert result == "thread"


class TestTranslationResponse:
    """翻訳レスポンス送信機能のテスト"""

    @pytest.mark.asyncio
    async def test_send_translation_response_normal(self):
        """通常メッセージへの翻訳返信テスト"""
        # 通常メッセージのモック
        message = MagicMock()
        message.reference = None
        message.thread = None
        message.channel.send = AsyncMock()

        # 関数実行
        await send_translation_response(message, "Translated text", "🇺🇸")

        # アサーション
        message.channel.send.assert_called_once()
        args, kwargs = message.channel.send.call_args
        assert "🇺🇸 Translated text" == args[0]
        assert kwargs["reference"] is message.to_reference.return_value
        message.to_reference.assert_called_once_with(fail_if_not_exists=False)

    @pytest.mark.asyncio
    async def test_send_translation_response_thread(self):
        """スレッド内メッセージへの翻訳返信テスト"""
        # スレッド内メッセージ: message.channel が Thread オブジェクト
        message = MagicMock()
        message.reference = None
        message.channel = MagicMock(spec=discord.Thread)
        message.channel.send = AsyncMock()

        # 関数実行
        await send_translation_response(message, "Translated text", "🇺🇸")

        # アサーション: message.channel（Thread）に送信される
        message.channel.send.assert_called_once()
        args, kwargs = message.channel.send.call_args
        assert "🇺🇸 Translated text" == args[0]
        assert kwargs["reference"] is message.to_reference.return_value
        message.to_reference.assert_called_once_with(fail_if_not_exists=False)


class TestTranslateAndReply:
    """translate_and_reply のテスト"""

    @pytest.mark.asyncio
    @patch("utils.text_utils.translate_to_english")
    async def test_translate_and_reply_success(self, mock_translate_to_english):
        """翻訳成功時のテスト"""
        # 翻訳関数のモック
        mock_translate_to_english.return_value = "This is a translated text."

        # メッセージのモック
        message = MagicMock()
        message.content = "これは翻訳用のテキストです。"
        message.author.id = 12345
        message.channel.send = AsyncMock()

        # 関数実行
        await translate_and_reply(message)

        # アサーション
        mock_translate_to_english.assert_called_once_with(
            "これは翻訳用のテキストです。"
        )
        message.channel.send.assert_called_once()
        args, kwargs = message.channel.send.call_args
        assert "🇺🇸 This is a translated text." == args[0]
        assert kwargs["reference"] is message.to_reference.return_value
        message.to_reference.assert_called_once_with(fail_if_not_exists=False)

    @pytest.mark.asyncio
    @patch("utils.text_utils.translate_to_english")
    async def test_translate_and_reply_error(self, mock_translate_to_english):
        """翻訳エラー時のテスト"""
        # 翻訳関数のモック (エラー時はNoneを返す)
        mock_translate_to_english.return_value = None

        # メッセージのモック
        message = MagicMock()
        message.content = "これは翻訳エラーのテスト用テキストです。"
        message.author.id = 12345
        message.channel.send = AsyncMock()

        # 関数実行
        await translate_and_reply(message)

        # アサーション
        mock_translate_to_english.assert_called_once_with(
            "これは翻訳エラーのテスト用テキストです。"
        )
        message.channel.send.assert_called_once()
        args, kwargs = message.channel.send.call_args
        assert "エラー" in args[0]
        assert kwargs["reference"] is message.to_reference.return_value
        message.to_reference.assert_called_once_with(fail_if_not_exists=False)

    @pytest.mark.asyncio
    @patch("utils.text_utils.translate_to_english")
    async def test_translate_and_reply_empty_message(self, mock_translate_to_english):
        """空のメッセージコンテンツは処理されないテスト"""
        # メッセージのモック (空のコンテンツ)
        message = MagicMock()
        message.content = None

        # 関数実行
        await translate_and_reply(message)

        # アサーション - 早期リターンにより翻訳関数は呼ばれないはず
        mock_translate_to_english.assert_not_called()

    @pytest.mark.asyncio
    @patch("utils.text_utils.translate_to_japanese")
    async def test_translate_and_reply_japanese(self, mock_translate_to_japanese):
        """日本語翻訳のテスト"""
        # 翻訳関数のモック
        mock_translate_to_japanese.return_value = "これは翻訳されたテキストです。"

        # メッセージのモック
        message = MagicMock()
        message.content = "This is a text for translation."
        message.author.id = 12345
        message.channel.send = AsyncMock()

        # 関数実行
        await translate_and_reply(message, "japanese")

        # アサーション
        mock_translate_to_japanese.assert_called_once_with(
            "This is a text for translation."
        )
        message.channel.send.assert_called_once()
        args, kwargs = message.channel.send.call_args
        assert "🇯🇵 これは翻訳されたテキストです。" in args[0]
        assert kwargs["reference"] is message.to_reference.return_value
        message.to_reference.assert_called_once_with(fail_if_not_exists=False)

    @pytest.mark.asyncio
    @patch("utils.text_utils.translate_to_japanese")
    async def test_translate_and_reply_japanese_error(self, mock_translate_to_japanese):
        """日本語翻訳エラー時のテスト"""
        # 翻訳関数のモック (エラー時はNoneを返す)
        mock_translate_to_japanese.return_value = None

        # メッセージのモック
        message = MagicMock()
        message.content = "This is a text that causes translation error."
        message.author.id = 12345
        message.channel.send = AsyncMock()

        # 関数実行
        await translate_and_reply(message, "japanese")

        # アサーション
        mock_translate_to_japanese.assert_called_once_with(
            "This is a text that causes translation error."
        )
        message.channel.send.assert_called_once()
        args, kwargs = message.channel.send.call_args
        assert "エラー" in args[0]
        assert kwargs["reference"] is message.to_reference.return_value
        message.to_reference.assert_called_once_with(fail_if_not_exists=False)
