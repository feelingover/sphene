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
    _handle_reaction,
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
        assert kwargs["reference"] == message

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
        assert kwargs["reference"] == message


class TestReactionHandling:
    """リアクション処理のテスト"""

    @pytest.mark.asyncio
    @patch("bot.events.translate_and_reply")
    @patch("bot.events.config_manager")
    async def test_handle_reaction_us_flag(
        self, mock_config_manager, mock_translate_and_reply
    ):
        """アメリカ国旗リアクションが検出されるテスト"""
        # config_managerのモック設定
        mock_channel_config = MagicMock()
        mock_channel_config.can_bot_speak.return_value = True
        mock_config_manager.get_config.return_value = mock_channel_config

        # ボットのモック
        bot = MagicMock()

        # リアクションとユーザーのモック
        user = MagicMock()
        user.bot = False
        user.id = 12345

        # 絵文字のモック（アメリカ国旗）
        emoji = MagicMock()
        emoji.__str__ = MagicMock(return_value="flag_us")

        # メッセージのモック
        message = MagicMock()
        message.guild.id = 67890
        message.channel.id = 54321
        message.id = 98765

        # リアクションのモック
        reaction = MagicMock()
        reaction.emoji = emoji
        reaction.message = message

        # 関数実行
        await _handle_reaction(bot, reaction, user)

        # アサーション
        mock_config_manager.get_config.assert_called_once_with(67890)
        mock_channel_config.can_bot_speak.assert_called_once_with(54321)
        mock_translate_and_reply.assert_called_once_with(message, "english")

    @pytest.mark.asyncio
    @patch("bot.events.translate_and_reply")
    @patch("bot.events.config_manager")
    async def test_handle_reaction_non_us_flag(
        self, mock_config_manager, mock_translate_and_reply
    ):
        """アメリカ国旗以外のリアクションでは翻訳されないテスト"""
        # config_managerのモック設定
        mock_channel_config = MagicMock()
        mock_channel_config.can_bot_speak.return_value = True
        mock_config_manager.get_config.return_value = mock_channel_config

        # ボットのモック
        bot = MagicMock()

        # リアクションとユーザーのモック
        user = MagicMock()
        user.bot = False

        # 絵文字のモック（別の絵文字）
        emoji = MagicMock()
        emoji.__str__ = MagicMock(return_value="👍")

        # メッセージのモック
        message = MagicMock()
        message.guild.id = 67890
        message.channel.id = 54321

        # リアクションのモック
        reaction = MagicMock()
        reaction.emoji = emoji
        reaction.message = message

        # 関数実行
        await _handle_reaction(bot, reaction, user)

        # アサーション - translate_and_replyは呼ばれないはず
        mock_config_manager.get_config.assert_called_once_with(67890)
        mock_channel_config.can_bot_speak.assert_called_once_with(54321)
        mock_translate_and_reply.assert_not_called()

    @pytest.mark.asyncio
    @patch("bot.events.translate_and_reply")
    @patch("bot.events.config_manager")
    async def test_handle_reaction_bot_user(
        self, mock_config_manager, mock_translate_and_reply
    ):
        """ボットユーザーのリアクションは無視されるテスト"""
        # リアクションとユーザーのモック (ボットユーザー)
        user = MagicMock()
        user.bot = True  # ボットユーザー

        # ボットとリアクションのモック
        bot = MagicMock()
        reaction = MagicMock()

        # 関数実行
        await _handle_reaction(bot, reaction, user)

        # アサーション - 早期リターンによりconfig_managerは呼ばれないはず
        mock_config_manager.get_config.assert_not_called()
        mock_translate_and_reply.assert_not_called()

    @pytest.mark.asyncio
    @patch("bot.events.config_manager")
    async def test_handle_reaction_not_in_guild(self, mock_config_manager):
        """ギルドに所属していないメッセージのテスト"""
        # ボットとユーザーのモック
        bot = MagicMock()
        user = MagicMock()
        user.bot = False

        # メッセージのモック (ギルドなし)
        message = MagicMock()
        message.guild = None

        # リアクションのモック
        reaction = MagicMock()
        reaction.message = message

        # 関数実行
        await _handle_reaction(bot, reaction, user)

        # アサーション - 早期リターンによりconfig_managerは呼ばれないはず
        mock_config_manager.get_config.assert_not_called()

    @pytest.mark.asyncio
    @patch("bot.events.translate_and_reply")
    @patch("bot.events.config_manager")
    async def test_handle_reaction_cannot_speak(
        self, mock_config_manager, mock_translate_and_reply
    ):
        """発言できないチャンネルでのリアクションテスト"""
        # config_managerのモック設定 (発言不可)
        mock_channel_config = MagicMock()
        mock_channel_config.can_bot_speak.return_value = False
        mock_config_manager.get_config.return_value = mock_channel_config

        # ボットのモック
        bot = MagicMock()

        # リアクションとユーザーのモック
        user = MagicMock()
        user.bot = False

        # 絵文字のモック（アメリカ国旗）
        emoji = MagicMock()
        emoji.__str__ = MagicMock(return_value="flag_us")

        # メッセージのモック
        message = MagicMock()
        message.guild.id = 67890
        message.channel.id = 54321

        # リアクションのモック
        reaction = MagicMock()
        reaction.emoji = emoji
        reaction.message = message

        # 関数実行
        await _handle_reaction(bot, reaction, user)

        # アサーション
        mock_config_manager.get_config.assert_called_once_with(67890)
        mock_channel_config.can_bot_speak.assert_called_once_with(54321)
        # 発言不可なのでtranslate_and_replyは呼ばれないはず
        mock_translate_and_reply.assert_not_called()

    @pytest.mark.asyncio
    @patch("bot.events.translate_and_reply")
    @patch("bot.events.config_manager")
    async def test_handle_reaction_translation_disabled(
        self, mock_config_manager, mock_translate_and_reply
    ):
        """翻訳機能が無効の場合のテスト"""
        # config_managerのモック設定 (発言可能だが翻訳無効)
        mock_channel_config = MagicMock()
        mock_channel_config.can_bot_speak.return_value = True
        mock_channel_config.get_translation_enabled.return_value = False  # 翻訳無効
        mock_config_manager.get_config.return_value = mock_channel_config

        # ボットのモック
        bot = MagicMock()

        # リアクションとユーザーのモック
        user = MagicMock()
        user.bot = False

        # 絵文字のモック（アメリカ国旗）
        emoji = MagicMock()
        emoji.__str__ = MagicMock(return_value="flag_us")

        # メッセージのモック
        message = MagicMock()
        message.guild.id = 67890
        message.channel.id = 54321

        # リアクションのモック
        reaction = MagicMock()
        reaction.emoji = emoji
        reaction.message = message

        # 関数実行
        await _handle_reaction(bot, reaction, user)

        # アサーション
        mock_config_manager.get_config.assert_called_once_with(67890)
        mock_channel_config.can_bot_speak.assert_called_once_with(54321)
        mock_channel_config.get_translation_enabled.assert_called_once()
        # 翻訳機能が無効なのでtranslate_and_replyは呼ばれないはず
        mock_translate_and_reply.assert_not_called()

    @pytest.mark.asyncio
    @patch("bot.events.translate_and_reply")
    @patch("bot.events.config_manager")
    async def test_handle_reaction_jp_flag(
        self, mock_config_manager, mock_translate_and_reply
    ):
        """日本国旗リアクションが検出されるテスト"""
        # config_managerのモック設定
        mock_channel_config = MagicMock()
        mock_channel_config.can_bot_speak.return_value = True
        mock_channel_config.get_translation_enabled.return_value = True  # 翻訳有効
        mock_config_manager.get_config.return_value = mock_channel_config

        # ボットのモック
        bot = MagicMock()

        # リアクションとユーザーのモック
        user = MagicMock()
        user.bot = False
        user.id = 12345

        # 絵文字のモック（日本国旗）
        emoji = MagicMock()
        emoji.__str__ = MagicMock(return_value="🇯🇵")

        # メッセージのモック
        message = MagicMock()
        message.guild.id = 67890
        message.channel.id = 54321
        message.id = 98765

        # リアクションのモック
        reaction = MagicMock()
        reaction.emoji = emoji
        reaction.message = message

        # 関数実行
        await _handle_reaction(bot, reaction, user)

        # アサーション
        mock_config_manager.get_config.assert_called_once_with(67890)
        mock_channel_config.can_bot_speak.assert_called_once_with(54321)
        mock_channel_config.get_translation_enabled.assert_called_once()
        # 日本語翻訳が呼ばれるはず
        mock_translate_and_reply.assert_called_once_with(message, "japanese")

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
        assert kwargs["reference"] == message

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
        assert kwargs["reference"] == message

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
        assert kwargs["reference"] == message

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
        assert kwargs["reference"] == message
