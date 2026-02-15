"""
bot/discord_bot.py と app.py のテスト
"""

# type: ignore
# mypy: ignore-errors

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.discord_bot import SpheneBot
import app


class TestBotAndApp:
    """ボット本体とエントリーポイントのテスト"""

    @patch("bot.discord_bot.load_system_prompt")
    @patch("discord.ext.commands.Bot")
    def test_sphene_bot_init_failure(self, mock_bot, mock_load_prompt):
        """システムプロンプト読み込み失敗による初期化失敗テスト"""
        mock_load_prompt.side_effect = Exception("File Not Found")
        
        with patch("sys.exit") as mock_exit:
            SpheneBot()
            mock_exit.assert_called_once_with(1)

    @pytest.mark.asyncio
    @patch("bot.discord_bot.cleanup_expired_conversations")
    @patch("memory.short_term.get_channel_buffer")
    @patch("bot.discord_bot.load_system_prompt")
    async def test_cleanup_task(self, mock_load, mock_get_buffer, mock_cleanup_conv):
        """定期クリーンアップタスクの実行テスト"""
        # SpheneBotの初期化
        with patch("discord.ext.commands.Bot"):
            bot_wrapper = SpheneBot()
        
        mock_cleanup_conv.return_value = 5
        mock_buffer = MagicMock()
        mock_buffer.cleanup_expired.return_value = 10
        mock_get_buffer.return_value = mock_buffer
        
        # タスクを直接実行
        await bot_wrapper._cleanup_task()
        
        mock_cleanup_conv.assert_called_once()
        mock_buffer.cleanup_expired.assert_called_once()

    @pytest.mark.asyncio
    @patch("bot.discord_bot.cleanup_expired_conversations")
    @patch("bot.discord_bot.load_system_prompt")
    async def test_cleanup_task_exception(self, mock_load, mock_cleanup_conv):
        """クリーンアップタスクでの例外ハンドリングテスト"""
        with patch("discord.ext.commands.Bot"):
            bot_wrapper = SpheneBot()
        
        mock_cleanup_conv.side_effect = Exception("Cleanup Error")
        
        # 例外が発生しても中断されないことを確認
        await bot_wrapper._cleanup_task()
        mock_cleanup_conv.assert_called_once()

    def test_sphene_bot_run(self):
        """bot.run が呼ばれることを確認"""
        with patch("discord.ext.commands.Bot") as mock_bot_class:
            bot_instance = mock_bot_class.return_value
            with patch("bot.discord_bot.load_system_prompt"):
                sphene_bot = SpheneBot()
                sphene_bot.run()
                bot_instance.run.assert_called_once()

    @patch("app.SpheneBot")
    def test_app_main(self, mock_sphene_bot):
        """app.main の呼び出しテスト"""
        mock_instance = mock_sphene_bot.return_value
        
        app.main()
        
        mock_sphene_bot.assert_called_once()
        mock_instance.run.assert_called_once()
