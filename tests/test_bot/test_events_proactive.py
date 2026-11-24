"""自発会話の判定用に、人間・自分の発言時刻を記録すること（bot/events.py）のテスト"""

# type: ignore
# mypy: ignore-errors

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.events import (
    _post_response_update,
    _process_short_ack,
    _record_living_memory,
    _record_self_message,
)
from memory.channel_context import ChannelContext


def _store_with(ctx):
    store = MagicMock()
    store.get_context.return_value = ctx
    return store


class TestRecordSelfMessage:
    @patch("bot.events.config")
    def test_records_when_living_memory_enabled(self, mock_config):
        mock_config.LIVING_MEMORY_ENABLED = True
        ctx = ChannelContext(channel_id=100)
        with patch("memory.channel_context.get_channel_context_store", return_value=_store_with(ctx)):
            _record_self_message(100)
        assert ctx.last_self_message_at is not None

    @patch("bot.events.config")
    def test_skips_when_living_memory_disabled(self, mock_config):
        mock_config.LIVING_MEMORY_ENABLED = False
        with patch("memory.channel_context.get_channel_context_store") as mock_store:
            _record_self_message(100)
        mock_store.assert_not_called()

    @patch("bot.events.config")
    def test_failure_does_not_raise(self, mock_config):
        mock_config.LIVING_MEMORY_ENABLED = True
        with patch(
            "memory.channel_context.get_channel_context_store", side_effect=RuntimeError("x")
        ):
            _record_self_message(100)


class TestRecordedOnResponses:
    @patch("bot.events.config")
    def test_post_response_update_records_self(self, mock_config):
        """メンション応答・自律応答の送信後に自分の発言時刻を記録する"""
        mock_config.LIVING_MEMORY_ENABLED = False
        message = MagicMock()
        message.channel.id = 100
        with (
            patch("bot.events._record_self_message") as mock_record,
            patch("memory.short_term.get_channel_buffer"),
        ):
            _post_response_update(message, "answer", [], MagicMock())
        mock_record.assert_called_once_with(100)

    @pytest.mark.asyncio
    async def test_short_ack_records_self(self):
        bot = MagicMock()
        message = MagicMock()
        message.channel.id = 100
        message.channel.send = AsyncMock()
        message.content = "やった"
        buffer = MagicMock()
        buffer.get_context_string.return_value = "A: やった"
        with (
            patch("memory.short_term.get_channel_buffer", return_value=buffer),
            patch("memory.judge.get_judge"),
            patch("bot.events.generate_short_ack", return_value="いいね！"),
            patch("bot.events._record_self_message") as mock_record,
        ):
            await _process_short_ack(bot, message)
        mock_record.assert_called_once_with(100)


class TestHumanMessageRecorded:
    def test_record_living_memory_records_human_time(self):
        ctx = ChannelContext(channel_id=100)
        created = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
        message = MagicMock()
        message.channel.id = 100
        message.created_at = created
        buffer = MagicMock()
        buffer.count_messages_since_reflection.return_value = 0
        with (
            patch("memory.channel_context.get_channel_context_store", return_value=_store_with(ctx)),
            patch("memory.summarizer.get_summarizer"),
            patch("memory.user_profile.get_user_profile_store"),
            patch("memory.reflection.get_reflection_engine"),
        ):
            _record_living_memory(message, 1, buffer)
        assert ctx.last_human_message_at == created
        assert ctx.message_count_since_update == 1
