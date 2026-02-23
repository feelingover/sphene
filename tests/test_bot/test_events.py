"""
Discordイベント処理のテスト
特にチャンネル評価機能に関するテスト
"""

# type: ignore
# mypy: ignore-errors

from datetime import datetime, timezone
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
        message.created_at = datetime.now(timezone.utc)
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
        mock_config.AUTONOMOUS_RESPONSE_ENABLED = False
        mock_config.CHANNEL_CONTEXT_ENABLED = False
        mock_config.USER_PROFILE_ENABLED = False
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
        message.created_at = datetime.now(timezone.utc)
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
        message.created_at = datetime.now(timezone.utc)
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


class TestDispatchResponse:
    """_dispatch_response のテスト"""

    @pytest.mark.asyncio
    @patch("bot.events._process_autonomous_response")
    async def test_dispatch_full_response(self, mock_process):
        """full_responseの場合_process_autonomous_responseが呼ばれる"""
        bot = MagicMock()
        message = MagicMock()

        from bot.events import _dispatch_response
        await _dispatch_response(bot, message, [], "full_response")

        mock_process.assert_called_once_with(bot, message, [])

    @pytest.mark.asyncio
    @patch("bot.events._send_reaction")
    async def test_dispatch_react_only(self, mock_reaction):
        """react_onlyの場合_send_reactionが呼ばれる"""
        bot = MagicMock()
        message = MagicMock()

        from bot.events import _dispatch_response
        await _dispatch_response(bot, message, [], "react_only")

        mock_reaction.assert_called_once_with(message)

    @pytest.mark.asyncio
    @patch("bot.events._process_short_ack")
    async def test_dispatch_short_ack(self, mock_ack):
        """short_ackの場合_process_short_ackが呼ばれる"""
        bot = MagicMock()
        message = MagicMock()

        from bot.events import _dispatch_response
        await _dispatch_response(bot, message, [], "short_ack")

        mock_ack.assert_called_once_with(bot, message)


class TestSendReaction:
    """_send_reaction のテスト"""

    @pytest.mark.asyncio
    @patch("memory.judge.get_judge")
    async def test_send_reaction_adds_emoji(self, mock_get_judge):
        """リアクションが追加される"""
        mock_judge = MagicMock()
        mock_get_judge.return_value = mock_judge

        message = MagicMock()
        message.add_reaction = AsyncMock()
        message.channel.id = 100

        from bot.events import _send_reaction
        await _send_reaction(message)

        message.add_reaction.assert_called_once()
        mock_judge.record_response.assert_called_once_with(100)


class TestProcessShortAck:
    """_process_short_ack のテスト"""

    @pytest.mark.asyncio
    @patch("asyncio.to_thread")
    @patch("memory.judge.get_judge")
    @patch("memory.short_term.get_channel_buffer")
    async def test_short_ack_success(self, mock_buffer_fn, mock_get_judge, mock_to_thread):
        """相槌が正常に送信される"""
        mock_buffer = MagicMock()
        mock_buffer.get_context_string.return_value = "User1: hello"
        mock_buffer_fn.return_value = mock_buffer

        mock_judge = MagicMock()
        mock_get_judge.return_value = mock_judge

        mock_to_thread.return_value = "なるほどー"

        bot = MagicMock()
        bot.user = MagicMock()
        bot.user.id = 999
        bot.user.display_name = "Bot"

        message = MagicMock()
        message.channel.id = 100
        message.channel.send = AsyncMock()
        message.content = "テスト"
        message.created_at = MagicMock()

        from bot.events import _process_short_ack
        await _process_short_ack(bot, message)

        message.channel.send.assert_called_once_with("なるほどー")
        mock_judge.record_response.assert_called_once_with(100)
