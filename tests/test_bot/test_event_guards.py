"""二重リアクション防止・翻訳の重複抑止・メンションのレート制限のテスト"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

import bot.events as events
from bot.events import (
    _acquire_mention_quota,
    _dispatch_response,
    _handle_message,
    translate_and_reply,
)


class TestDispatchReactOnly:
    @pytest.mark.asyncio
    @patch("memory.judge.get_judge")
    @patch("bot.events._send_reaction")
    async def test_already_reacted_skips_second_reaction(self, mock_reaction, mock_get_judge):
        message = MagicMock()
        message.channel.id = 100

        await _dispatch_response(MagicMock(), message, [], "react_only", already_reacted=True)

        mock_reaction.assert_not_called()
        mock_get_judge.return_value.record_response.assert_called_once_with(100)

    @pytest.mark.asyncio
    @patch("bot.events._send_reaction")
    async def test_not_reacted_sends_reaction(self, mock_reaction):
        message = MagicMock()

        await _dispatch_response(MagicMock(), message, [], "react_only", already_reacted=False)

        mock_reaction.assert_called_once_with(message)


class TestHighScoreReactOnly:
    @pytest.mark.asyncio
    @patch("bot.events._dispatch_response", new_callable=AsyncMock)
    @patch("bot.events._send_reaction", new_callable=AsyncMock)
    @patch("memory.judge.get_judge")
    @patch("memory.short_term.get_channel_buffer")
    async def test_high_score_react_only_dispatches_as_already_reacted(
        self, mock_get_buffer, mock_get_judge, mock_reaction, mock_dispatch
    ):
        """高スコアの react_only でもリアクション済みとして dispatch される（クールダウン記録のため）"""
        result = MagicMock(
            should_react=True,
            reaction_emojis=["👍"],
            score=90,
            response_type="react_only",
            reason="test",
        )
        mock_get_judge.return_value.evaluate.return_value = result
        message = MagicMock()
        message.content = "hi"
        message.created_at = datetime.now(timezone.utc)

        with patch("config.JUDGE_LLM_THRESHOLD_HIGH", 60):
            await events._try_autonomous_response(MagicMock(), message, [])

        mock_dispatch.assert_awaited_once()
        assert mock_dispatch.await_args.kwargs["already_reacted"] is True


def _translation_message(message_id: int = 1) -> MagicMock:
    message = MagicMock()
    message.id = message_id
    message.content = "テキスト"
    message.author.id = 2
    message.channel.send = AsyncMock()
    return message


class TestTranslationDedup:
    @pytest.mark.asyncio
    @patch("utils.text_utils.translate_to_english", new_callable=AsyncMock)
    async def test_same_message_and_language_translated_once(self, mock_translate):
        mock_translate.return_value = "Text"
        message = _translation_message()

        await translate_and_reply(message, "english")
        await translate_and_reply(message, "english")

        mock_translate.assert_awaited_once()
        message.channel.send.assert_called_once()

    @pytest.mark.asyncio
    @patch("utils.text_utils.translate_to_japanese", new_callable=AsyncMock)
    @patch("utils.text_utils.translate_to_english", new_callable=AsyncMock)
    async def test_other_language_is_allowed(self, mock_en, mock_ja):
        mock_en.return_value = "Text"
        mock_ja.return_value = "テキスト"
        message = _translation_message()

        await translate_and_reply(message, "english")
        await translate_and_reply(message, "japanese")

        mock_en.assert_awaited_once()
        mock_ja.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("utils.text_utils.translate_to_english", new_callable=AsyncMock)
    async def test_failed_translation_can_be_retried(self, mock_translate):
        mock_translate.side_effect = [None, "Text"]
        message = _translation_message()

        await translate_and_reply(message, "english")
        await translate_and_reply(message, "english")

        assert mock_translate.await_count == 2

    @pytest.mark.asyncio
    @patch("utils.text_utils.translate_to_english", new_callable=AsyncMock)
    async def test_exception_releases_claim(self, mock_translate):
        mock_translate.side_effect = [RuntimeError("boom"), "Text"]
        message = _translation_message()

        with pytest.raises(RuntimeError):
            await translate_and_reply(message, "english")
        await translate_and_reply(message, "english")

        assert mock_translate.await_count == 2

    @pytest.mark.asyncio
    @patch("bot.events.time.monotonic")
    @patch("utils.text_utils.translate_to_english", new_callable=AsyncMock)
    async def test_claim_expires_after_dedup_period(self, mock_translate, mock_monotonic):
        mock_translate.return_value = "Text"
        message = _translation_message()

        with patch("config.TRANSLATION_DEDUP_SECONDS", 100):
            mock_monotonic.return_value = 0.0
            await translate_and_reply(message, "english")
            mock_monotonic.return_value = 99.0
            await translate_and_reply(message, "english")
            mock_monotonic.return_value = 100.0
            await translate_and_reply(message, "english")

        assert mock_translate.await_count == 2
        assert len(events._translated_messages) == 1


def _mention_message(user_id: int = 10, channel_id: int = 20) -> MagicMock:
    message = MagicMock()
    message.author.id = user_id
    message.channel.id = channel_id
    message.add_reaction = AsyncMock()
    return message


class TestMentionQuota:
    @pytest.mark.asyncio
    async def test_user_limit(self, monkeypatch):
        monkeypatch.setattr(events._user_mention_limiter, "max_events", 2)
        message = _mention_message()

        results = [await _acquire_mention_quota(message, 1) for _ in range(3)]

        assert results == [True, True, False]
        message.add_reaction.assert_awaited_once_with("⏳")

    @pytest.mark.asyncio
    async def test_user_limit_is_per_guild(self, monkeypatch):
        monkeypatch.setattr(events._user_mention_limiter, "max_events", 1)
        message = _mention_message()

        assert await _acquire_mention_quota(message, 1)
        assert await _acquire_mention_quota(message, 2)

    @pytest.mark.asyncio
    async def test_channel_limit_across_users(self, monkeypatch):
        monkeypatch.setattr(events._channel_mention_limiter, "max_events", 2)

        results = [
            await _acquire_mention_quota(_mention_message(user_id=u), 1) for u in range(3)
        ]

        assert results == [True, True, False]

    @pytest.mark.asyncio
    async def test_channel_rejection_does_not_consume_user_quota(self, monkeypatch):
        monkeypatch.setattr(events._user_mention_limiter, "max_events", 1)
        monkeypatch.setattr(events._channel_mention_limiter, "max_events", 1)
        assert await _acquire_mention_quota(_mention_message(user_id=1), 1)

        assert not await _acquire_mention_quota(_mention_message(user_id=2), 1)
        assert (1, 2) not in events._user_mention_limiter._events

    @pytest.mark.asyncio
    async def test_reaction_failure_is_ignored(self, monkeypatch):
        monkeypatch.setattr(events._user_mention_limiter, "max_events", 1)
        message = _mention_message()
        message.add_reaction.side_effect = discord.HTTPException(MagicMock(), "x")

        assert await _acquire_mention_quota(message, 1)
        assert not await _acquire_mention_quota(message, 1)


    @pytest.mark.asyncio
    async def test_hourglass_sent_once_per_message(self, monkeypatch):
        monkeypatch.setattr(events._user_mention_limiter, "max_events", 1)
        message = _mention_message()
        message.id = 99

        results = [await _acquire_mention_quota(message, 1) for _ in range(4)]

        assert results == [True, False, False, False]
        message.add_reaction.assert_awaited_once_with("⏳")

class TestHandleMessageRateLimit:
    @pytest.mark.asyncio
    @patch("bot.events._record_memory", new_callable=AsyncMock)
    @patch("bot.events.is_bot_mentioned", new_callable=AsyncMock)
    @patch("bot.events.process_conversation", new_callable=AsyncMock)
    @patch("bot.events.config_manager")
    async def test_throttled_mention_is_not_processed(
        self, mock_config_manager, mock_process, mock_is_mentioned, _mock_record, monkeypatch
    ):
        monkeypatch.setattr(events._user_mention_limiter, "max_events", 1)
        mock_config_manager.get_config.return_value.can_bot_speak.return_value = True
        mock_is_mentioned.return_value = (True, "質問", False)
        message = _mention_message()
        message.author.bot = False
        message.content = "スフェーン"
        message.attachments = []
        message.guild.id = 1

        await _handle_message(MagicMock(), message)
        await _handle_message(MagicMock(), message)

        mock_process.assert_awaited_once()
        message.add_reaction.assert_awaited_once_with("⏳")
