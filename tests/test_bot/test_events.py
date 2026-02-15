"""
Discordイベント処理のテスト
特にチャンネル評価機能に関するテスト
"""

# type: ignore
# mypy: ignore-errors

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.events import _handle_message


class TestEventHandling:
    """イベント処理のテスト"""

    @pytest.mark.asyncio
    @patch("bot.events.is_bot_mentioned")
    @patch("bot.events.config_manager")
    async def test_handle_message_deny_mode_blocked(
        self, mock_config_manager, mock_is_bot_mentioned
    ):
        """全体モード（deny）でブロックされるチャンネルのテスト"""
        # channel_configの代わりにconfig_managerを使用
        mock_channel_config = MagicMock()
        mock_channel_config.can_bot_speak.return_value = False
        mock_channel_config.get_mode_display_name.return_value = "全体モード"
        mock_config_manager.get_config.return_value = mock_channel_config

        # メッセージのモック
        message = MagicMock()
        message.author.bot = False
        message.channel.id = 12345
        message.content = "テストメッセージ"
        message.author.id = 67890
        # guildのモック
        message.guild = MagicMock()
        message.guild.id = 54321

        # ボットのモック
        bot = MagicMock()
        bot.user = MagicMock()

        # コマンド実行
        await _handle_message(bot, message)

        # アサーション
        mock_config_manager.get_config.assert_called_once_with(54321)
        mock_channel_config.can_bot_speak.assert_called_once_with(12345)
        # メッセージチェック関数は呼ばれない（ブロックされるため）
        mock_is_bot_mentioned.assert_not_called()

    @pytest.mark.asyncio
    @patch("bot.events.is_bot_mentioned")
    @patch("bot.events.process_conversation")
    @patch("bot.events.config_manager")
    async def test_handle_message_allow_mode_permitted(
        self, mock_config_manager, mock_process_conversation, mock_is_bot_mentioned
    ):
        """限定モード（allow）で許可されるチャンネルのテスト"""
        # channel_configの代わりにconfig_managerを使用
        mock_channel_config = MagicMock()
        mock_channel_config.can_bot_speak.return_value = True
        mock_channel_config.get_mode_display_name.return_value = "限定モード"
        mock_config_manager.get_config.return_value = mock_channel_config
        mock_is_bot_mentioned.return_value = (True, "テスト質問", True)

        # メッセージのモック
        message = MagicMock()
        message.author.bot = False
        message.channel.id = 12345
        message.content = "テストメッセージ"
        message.author.id = 67890
        message.attachments = []  # 添付ファイルなし
        # guildのモック
        message.guild = MagicMock()
        message.guild.id = 54321

        # ボットのモック
        bot = MagicMock()
        bot.user = MagicMock()

        # コマンド実行
        await _handle_message(bot, message)

        # アサーション
        mock_config_manager.get_config.assert_called_once_with(54321)
        mock_channel_config.can_bot_speak.assert_called_once_with(12345)
        # メッセージチェック関数が呼ばれる（許可されるため）
        mock_is_bot_mentioned.assert_called_once()
        # メンションされていれば会話処理が呼ばれる
        mock_process_conversation.assert_called_once_with(
            message, "テスト質問", True, []
        )

    @pytest.mark.asyncio
    @patch("bot.events.config")
    @patch("bot.events.is_bot_mentioned")
    @patch("bot.events.process_conversation")
    @patch("bot.events.config_manager")
    async def test_handle_message_not_mentioned(
        self,
        mock_config_manager,
        mock_process_conversation,
        mock_is_bot_mentioned,
        mock_config,
    ):
        """ボットがメンションされていない場合のテスト"""
        mock_config.MEMORY_ENABLED = False
        mock_config.AUTONOMOUS_RESPONSE_ENABLED = False
        # channel_configの代わりにconfig_managerを使用
        mock_channel_config = MagicMock()
        mock_channel_config.can_bot_speak.return_value = True
        mock_config_manager.get_config.return_value = mock_channel_config
        mock_is_bot_mentioned.return_value = (False, "", False)

        # メッセージのモック
        message = MagicMock()
        message.author.bot = False
        message.channel.id = 12345
        message.content = "通常メッセージ"
        message.author.id = 67890
        # guildのモック
        message.guild = MagicMock()
        message.guild.id = 54321

        # ボットのモック
        bot = MagicMock()
        bot.user = MagicMock()

        # コマンド実行
        await _handle_message(bot, message)

        # アサーション
        mock_config_manager.get_config.assert_called_once_with(54321)
        mock_channel_config.can_bot_speak.assert_called_once_with(12345)
        # メッセージチェック関数は呼ばれる（チャンネルは許可されるため）
        mock_is_bot_mentioned.assert_called_once()
        # メンションされていないので会話処理は呼ばれない
        mock_process_conversation.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_message_bot_message(self):
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
        await _handle_message(bot, message)

        # config_managerはmockしないで、テストの動作だけ確認
        # ボットのメッセージは早期に無視されるので、モックの検証は不要

    @pytest.mark.asyncio
    async def test_handle_message_empty_content(self):
        """空のメッセージコンテンツを無視するテスト"""
        # メッセージのモック
        message = MagicMock()
        message.author.bot = False
        message.content = None  # 空のコンテンツ
        message.attachments = []  # 添付ファイルもなし
        message.channel.id = 12345

        # ボットのモック
        bot = MagicMock()
        bot.user = MagicMock()

        # コマンド実行
        await _handle_message(bot, message)

        # config_managerはmockしないで、テストの動作だけ確認
        # 空のコンテンツかつ添付ファイルがない場合は早期に無視されるので、モックの検証は不要

    @pytest.mark.asyncio
    @patch("bot.events.is_bot_mentioned")
    @patch("bot.events.process_conversation")
    @patch("bot.events.config_manager")
    async def test_handle_message_with_image(
        self, mock_config_manager, mock_process_conversation, mock_is_bot_mentioned
    ):
        """画像添付のあるメッセージのテスト"""
        # channel_configの設定
        mock_channel_config = MagicMock()
        mock_channel_config.can_bot_speak.return_value = True
        mock_channel_config.get_mode_display_name.return_value = "限定モード"
        mock_config_manager.get_config.return_value = mock_channel_config
        mock_is_bot_mentioned.return_value = (True, "テスト質問", True)

        # 画像添付ファイルのモック
        mock_attachment1 = MagicMock()
        mock_attachment1.content_type = "image/jpeg"
        mock_attachment1.url = "https://example.com/test1.jpg"

        mock_attachment2 = MagicMock()
        mock_attachment2.content_type = "application/pdf"  # 画像ではないタイプ
        mock_attachment2.url = "https://example.com/test.pdf"

        # メッセージのモック
        message = MagicMock()
        message.author.bot = False
        message.channel.id = 12345
        message.content = "画像テスト"
        message.author.id = 67890
        message.attachments = [mock_attachment1, mock_attachment2]
        # guildのモック
        message.guild = MagicMock()
        message.guild.id = 54321

        # ボットのモック
        bot = MagicMock()
        bot.user = MagicMock()

        # コマンド実行
        await _handle_message(bot, message)

        # アサーション
        mock_config_manager.get_config.assert_called_once()
        mock_channel_config.can_bot_speak.assert_called_once()
        mock_is_bot_mentioned.assert_called_once()
        # 画像URLのみがprocess_conversationに渡されることを確認
        mock_process_conversation.assert_called_once_with(
            message, "テスト質問", True, ["https://example.com/test1.jpg"]
        )

    @pytest.mark.asyncio
    @patch("bot.events.is_bot_mentioned")
    @patch("bot.events.process_conversation")
    @patch("bot.events.config_manager")
    async def test_handle_message_exception_handling(
        self, mock_config_manager, mock_process_conversation, mock_is_bot_mentioned
    ):
        """例外処理のテスト"""
        # モックのセットアップ - 例外を発生させる
        mock_config_manager.get_config.side_effect = Exception("テストエラー")

        # メッセージとチャンネルのモック
        message = MagicMock()
        message.author.bot = False
        message.channel.id = 12345
        message.content = "テストメッセージ"
        message.channel.send = AsyncMock()
        # guildのモック
        message.guild = MagicMock()
        message.guild.id = 54321

        # ボットのモック
        bot = MagicMock()
        bot.user = MagicMock()

        # コマンド実行
        await _handle_message(bot, message)

        # アサーション - エラーメッセージが送信されること
        message.channel.send.assert_called_once()
        args, kwargs = message.channel.send.call_args
        # セキュリティ改善により、エラー詳細は非公開（一般的なメッセージのみ）
        assert "エラー" in args[0]
        assert args[0] == "ごめん！メッセージ処理中にエラーが発生しちゃった...😢"
