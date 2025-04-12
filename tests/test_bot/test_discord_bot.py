"""bot/discord_bot.pyのテスト"""

from unittest.mock import MagicMock, patch

import discord

from bot.discord_bot import SpheneBot


def test_sphene_bot_initialization() -> None:
    """SpheneBot の初期化をテスト"""
    # discord.py コンポーネントをモック
    with patch("bot.discord_bot.commands.Bot") as mock_bot_cls, patch(
        "bot.discord_bot.setup_commands"
    ) as mock_setup_commands, patch(
        "bot.discord_bot.setup_events"
    ) as mock_setup_events:

        # モックの戻り値を設定
        mock_bot = MagicMock()
        mock_bot_cls.return_value = mock_bot
        mock_command_group = MagicMock()
        mock_setup_commands.return_value = mock_command_group

        # SpheneBot インスタンス作成
        SpheneBot()

        # 初期化の検証
        mock_bot_cls.assert_called_once()

        # インテントが正しく設定されているか
        call_kwargs = mock_bot_cls.call_args.kwargs
        assert call_kwargs["command_prefix"] == "!"
        assert isinstance(call_kwargs["intents"], discord.Intents)
        assert call_kwargs["intents"].message_content is True
        assert call_kwargs["intents"].members is True

        # コマンドとイベントが設定されたか
        mock_setup_commands.assert_called_once_with(mock_bot)
        mock_setup_events.assert_called_once_with(mock_bot, mock_command_group)


def test_sphene_bot_run() -> None:
    """SpheneBot の実行メソッドをテスト"""
    with patch("bot.discord_bot.commands.Bot") as mock_bot_cls, patch(
        "bot.discord_bot.config"
    ) as mock_config:

        # モックの設定
        mock_bot = MagicMock()
        mock_bot_cls.return_value = mock_bot
        mock_config.DISCORD_TOKEN = "mock-token"

        # セットアップメソッドのモック
        with patch.object(SpheneBot, "_setup") as mock_setup:
            bot = SpheneBot()
            mock_setup.assert_called_once()  # 初期化時に_setupが呼ばれるか

            # run メソッドのテスト
            bot.run()
            mock_bot.run.assert_called_once_with(mock_config.DISCORD_TOKEN)
