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
            patch("config.LIVING_MEMORY_ENABLED", True),
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
            patch("config.LIVING_MEMORY_ENABLED", True),
            patch("memory.user_profile.get_user_profile_store", side_effect=Exception("error3")),
            patch("memory.channel_context.get_channel_context_store", side_effect=Exception("error4")),
            patch("memory.reflection.get_reflection_engine", side_effect=Exception("error5")),
        ):
            await bot_wrapper._cleanup_task()


class TestProactiveTask:
    """自発会話のタイマーループ"""

    def _bot(self):
        with (
            patch("bot.discord_bot.commands.Bot"),
            patch("bot.discord_bot.load_system_prompt"),
        ):
            return SpheneBot()

    def test_not_started_when_disabled(self):
        bot_wrapper = self._bot()
        with (
            patch("config.PROACTIVE_ENABLED", False),
            patch.object(bot_wrapper._proactive_task, "start") as mock_start,
        ):
            bot_wrapper._start_proactive_task()
        mock_start.assert_not_called()

    def test_started_with_configured_interval(self):
        bot_wrapper = self._bot()
        with (
            patch("config.PROACTIVE_ENABLED", True),
            patch("config.PROACTIVE_CHECK_INTERVAL_MINUTES", 7),
            patch.object(bot_wrapper._proactive_task, "is_running", return_value=False),
            patch.object(bot_wrapper._proactive_task, "change_interval") as mock_interval,
            patch.object(bot_wrapper._proactive_task, "start") as mock_start,
        ):
            bot_wrapper._start_proactive_task()
        mock_interval.assert_called_once_with(minutes=7)
        mock_start.assert_called_once()

    def test_not_restarted_on_reconnect(self):
        bot_wrapper = self._bot()
        with (
            patch("config.PROACTIVE_ENABLED", True),
            patch.object(bot_wrapper._proactive_task, "is_running", return_value=True),
            patch.object(bot_wrapper._proactive_task, "start") as mock_start,
        ):
            bot_wrapper._start_proactive_task()
        mock_start.assert_not_called()

    @pytest.mark.asyncio
    async def test_loop_body_runs_check(self):
        bot_wrapper = self._bot()
        with patch("memory.proactive.run_proactive_check", new_callable=AsyncMock) as mock_run:
            await bot_wrapper._proactive_task()
        mock_run.assert_awaited_once_with(bot_wrapper.bot)

    @pytest.mark.asyncio
    async def test_cancelled_on_shutdown(self):
        bot_wrapper = self._bot()
        bot_wrapper.bot.close = AsyncMock()
        with (
            patch.object(bot_wrapper._proactive_task, "is_running", return_value=True),
            patch.object(bot_wrapper._proactive_task, "cancel") as mock_cancel,
            patch("bot.discord_bot._persist_memory_on_shutdown"),
        ):
            await bot_wrapper._graceful_shutdown()
        mock_cancel.assert_called_once()
        bot_wrapper.bot.close.assert_awaited_once()
