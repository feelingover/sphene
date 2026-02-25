"""
bot/discord_bot.py の追加テスト
"""

import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
import pytest
from bot.discord_bot import SpheneBot
import config

class TestDiscordBotAdditional:
    """SpheneBot の詳細なテスト"""

    @pytest.mark.asyncio
    async def test_start_cleanup_task_on_ready(self):
        """on_ready 時にクリーンアップタスクが開始されること"""
        with (
            patch("bot.discord_bot.commands.Bot") as mock_bot_cls,
            patch("bot.discord_bot.load_system_prompt"),
        ):
            
            mock_bot = MagicMock()
            mock_bot_cls.return_value = mock_bot
            
            bot_wrapper = SpheneBot()
            
            with (
                patch("bot.discord_bot.setup_commands"),
                patch("bot.discord_bot.setup_events"),
                patch.object(bot_wrapper._cleanup_task, "is_running", return_value=False),
                patch.object(bot_wrapper._cleanup_task, "start") as mock_start,
            ):
                captured_func = None
                def mock_listen(event):
                    def decorator(func):
                        nonlocal captured_func
                        if event == "on_ready":
                            captured_func = func
                        return func
                    return decorator
                
                mock_bot.listen.side_effect = mock_listen
                bot_wrapper._setup()
                
                assert captured_func is not None
                await captured_func()
                mock_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_task_full_branches(self):
        """_cleanup_task の全分岐（config 依存部分）をテスト"""
        with (
            patch("bot.discord_bot.commands.Bot"),
            patch("bot.discord_bot.load_system_prompt"),
        ):
            bot_wrapper = SpheneBot()

        with (
            patch("config.USER_PROFILE_ENABLED", True),
            patch("config.CHANNEL_CONTEXT_ENABLED", True),
            patch("config.REFLECTION_ENABLED", True),
            patch("memory.user_profile.get_user_profile_store") as mock_user_store,
            patch("memory.channel_context.get_channel_context_store") as mock_ctx_store,
            patch("memory.short_term.get_channel_buffer") as mock_buffer_fn,
            patch("memory.summarizer.get_summarizer") as mock_summ_fn,
            patch("memory.fact_store.get_fact_store") as mock_fact_store,
            patch("memory.reflection.get_reflection_engine") as mock_reflect_fn,
            patch("bot.discord_bot.cleanup_expired_conversations"),
        ):

            mock_buffer = MagicMock()
            mock_buffer_fn.return_value = mock_buffer
            mock_buffer.get_active_channel_ids.return_value = ["channel1"]
            mock_buffer.get_last_message_time.return_value = None

            mock_ctx_store.return_value.get_all_contexts.return_value = {
                123: MagicMock(should_summarize_by_time=MagicMock(return_value=True))
            }

            await bot_wrapper._cleanup_task()

            mock_user_store.return_value.persist_all.assert_called_once()
            mock_summ_fn.return_value.maybe_summarize.assert_called_once()
            mock_fact_store.return_value.persist_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_task_errors(self):
        """各セクションでのエラーが他のセクションに影響しないこと"""
        with (
            patch("bot.discord_bot.commands.Bot"),
            patch("bot.discord_bot.load_system_prompt"),
        ):
            bot_wrapper = SpheneBot()

        with (
            patch("bot.discord_bot.cleanup_expired_conversations", side_effect=Exception("error1")),
            patch("memory.short_term.get_channel_buffer", side_effect=Exception("error2")),
            patch("config.USER_PROFILE_ENABLED", True),
            patch("memory.user_profile.get_user_profile_store", side_effect=Exception("error3")),
            patch("config.CHANNEL_CONTEXT_ENABLED", True),
            patch("memory.channel_context.get_channel_context_store", side_effect=Exception("error4")),
            patch("config.REFLECTION_ENABLED", True),
            patch("memory.reflection.get_reflection_engine", side_effect=Exception("error5")),
        ):
            await bot_wrapper._cleanup_task()
