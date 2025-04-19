"""
Discordイベント処理のテスト
特にチャンネル評価機能に関するテスト
"""

# type: ignore
# mypy: ignore-errors

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.events import handle_message


class TestEventHandling:
    """イベント処理のテスト"""

    @pytest.mark.asyncio
    @patch("bot.events.is_bot_mentioned")
    @patch("bot.events.channel_config")
    async def test_handle_message_deny_mode_blocked(
        self, mock_channel_config, mock_is_bot_mentioned
    ):
        """全体モード（deny）でブロックされるチャンネルのテスト"""
        # モックのセットアップ
        mock_channel_config.can_bot_speak.return_value = False
        mock_channel_config.get_mode_display_name.return_value = "全体モード"

        # メッセージのモック
        message = MagicMock()
        message.author.bot = False
        message.channel.id = 12345
        message.content = "テストメッセージ"
        message.author.id = 67890

        # ボットのモック
        bot = MagicMock()
        bot.user = MagicMock()

        # コマンド実行
        await handle_message(bot, message)

        # アサーション
        mock_channel_config.can_bot_speak.assert_called_once_with(12345)
        # メッセージチェック関数は呼ばれない（ブロックされるため）
        mock_is_bot_mentioned.assert_not_called()

    @pytest.mark.asyncio
    @patch("bot.events.is_bot_mentioned")
    @patch("bot.events.process_conversation")
    @patch("bot.events.channel_config")
    async def test_handle_message_allow_mode_permitted(
        self, mock_channel_config, mock_process_conversation, mock_is_bot_mentioned
    ):
        """限定モード（allow）で許可されるチャンネルのテスト"""
        # モックのセットアップ
        mock_channel_config.can_bot_speak.return_value = True
        mock_channel_config.get_mode_display_name.return_value = "限定モード"
        mock_is_bot_mentioned.return_value = (True, "テスト質問", True)

        # メッセージのモック
        message = MagicMock()
        message.author.bot = False
        message.channel.id = 12345
        message.content = "テストメッセージ"
        message.author.id = 67890

        # ボットのモック
        bot = MagicMock()
        bot.user = MagicMock()

        # コマンド実行
        await handle_message(bot, message)

        # アサーション
        mock_channel_config.can_bot_speak.assert_called_once_with(12345)
        # メッセージチェック関数が呼ばれる（許可されるため）
        mock_is_bot_mentioned.assert_called_once()
        # メンションされていれば会話処理が呼ばれる
        mock_process_conversation.assert_called_once_with(message, "テスト質問", True)

    @pytest.mark.asyncio
    @patch("bot.events.is_bot_mentioned")
    @patch("bot.events.process_conversation")
    @patch("bot.events.channel_config")
    async def test_handle_message_not_mentioned(
        self, mock_channel_config, mock_process_conversation, mock_is_bot_mentioned
    ):
        """ボットがメンションされていない場合のテスト"""
        # モックのセットアップ
        mock_channel_config.can_bot_speak.return_value = True
        mock_is_bot_mentioned.return_value = (False, "", False)

        # メッセージのモック
        message = MagicMock()
        message.author.bot = False
        message.channel.id = 12345
        message.content = "通常メッセージ"
        message.author.id = 67890

        # ボットのモック
        bot = MagicMock()
        bot.user = MagicMock()

        # コマンド実行
        await handle_message(bot, message)

        # アサーション
        mock_channel_config.can_bot_speak.assert_called_once_with(12345)
        # メッセージチェック関数は呼ばれる（チャンネルは許可されるため）
        mock_is_bot_mentioned.assert_called_once()
        # メンションされていないので会話処理は呼ばれない
        mock_process_conversation.assert_not_called()

    @pytest.mark.asyncio
    @patch("bot.events.channel_config")
    async def test_handle_message_bot_message(self, mock_channel_config):
        """ボット自身のメッセージを無視するテスト"""
        # メッセージのモック
        message = MagicMock()
        message.author.bot = True  # ボットからのメッセージ
        message.channel.id = 12345
        message.content = "ボットからのメッセージ"

        # ボットのモック
        bot = MagicMock()
        bot.user = MagicMock()

        # コマンド実行
        await handle_message(bot, message)

        # アサーション - ボットのメッセージは無視される
        mock_channel_config.can_bot_speak.assert_not_called()

    @pytest.mark.asyncio
    @patch("bot.events.channel_config")
    async def test_handle_message_empty_content(self, mock_channel_config):
        """空のメッセージコンテンツを無視するテスト"""
        # メッセージのモック
        message = MagicMock()
        message.author.bot = False
        message.content = None  # 空のコンテンツ
        message.channel.id = 12345

        # ボットのモック
        bot = MagicMock()
        bot.user = MagicMock()

        # コマンド実行
        await handle_message(bot, message)

        # アサーション - 空のコンテンツは無視される
        mock_channel_config.can_bot_speak.assert_not_called()

    @pytest.mark.asyncio
    @patch("bot.events.is_bot_mentioned")
    @patch("bot.events.process_conversation")
    @patch("bot.events.channel_config")
    async def test_handle_message_exception_handling(
        self, mock_channel_config, mock_process_conversation, mock_is_bot_mentioned
    ):
        """例外処理のテスト"""
        # モックのセットアップ - 例外を発生させる
        mock_channel_config.can_bot_speak.side_effect = Exception("テストエラー")

        # メッセージとチャンネルのモック
        message = MagicMock()
        message.author.bot = False
        message.channel.id = 12345
        message.content = "テストメッセージ"
        message.channel.send = AsyncMock()

        # ボットのモック
        bot = MagicMock()
        bot.user = MagicMock()

        # コマンド実行
        await handle_message(bot, message)

        # アサーション - エラーメッセージが送信されること
        message.channel.send.assert_called_once()
        args, kwargs = message.channel.send.call_args
        assert "エラー" in args[0]
        assert "テストエラー" in args[0]
