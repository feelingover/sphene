"""国旗リアクション（raw イベント）による翻訳のテスト"""

# type: ignore
# mypy: ignore-errors

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

import bot.events as events
from bot.events import _handle_raw_reaction

GUILD_ID = 1
CHANNEL_ID = 2
MESSAGE_ID = 3
USER_ID = 4
BOT_ID = 99


def _payload(
    emoji: str = "🇺🇸",
    user_id: int = USER_ID,
    message_id: int = MESSAGE_ID,
    channel_id: int = CHANNEL_ID,
    guild_id: int | None = GUILD_ID,
    member_bot: bool = False,
) -> MagicMock:
    payload = MagicMock(spec=discord.RawReactionActionEvent)
    payload.emoji = emoji
    payload.user_id = user_id
    payload.message_id = message_id
    payload.channel_id = channel_id
    payload.guild_id = guild_id
    payload.member = MagicMock()
    payload.member.bot = member_bot
    return payload


def _bot(cached: list | None = None) -> MagicMock:
    """キャッシュ済みメッセージとチャンネルを持つ bot モック"""
    bot = MagicMock()
    bot.user.id = BOT_ID
    bot.cached_messages = cached or []
    channel = MagicMock(spec=discord.TextChannel)
    channel.fetch_message = AsyncMock()
    channel.send = AsyncMock()
    bot.get_channel.return_value = channel
    partial = MagicMock()
    partial.get_partial_message.return_value.add_reaction = AsyncMock()
    bot.get_partial_messageable.return_value = partial
    return bot


def _message(message_id: int = MESSAGE_ID) -> MagicMock:
    message = MagicMock(spec=discord.Message)
    message.id = message_id
    return message


@pytest.fixture
def channel_config():
    with patch("bot.events.config_manager") as manager:
        cfg = MagicMock()
        cfg.can_bot_speak.return_value = True
        cfg.get_translation_enabled.return_value = True
        manager.get_config.return_value = cfg
        yield cfg


@pytest.fixture
def mock_translate():
    with patch("bot.events.translate_and_reply", new_callable=AsyncMock) as mock:
        yield mock


class TestFlagDispatch:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("emoji", "language"),
        [("🇺🇸", "english"), ("flag_us", "english"), ("🇯🇵", "japanese"), ("flag_jp", "japanese")],
    )
    async def test_flag_translates_cached_message(
        self, channel_config, mock_translate, emoji, language
    ):
        message = _message()
        bot = _bot(cached=[message])

        await _handle_raw_reaction(bot, _payload(emoji=emoji))

        mock_translate.assert_awaited_once_with(message, language)
        bot.get_channel.return_value.fetch_message.assert_not_called()
        channel_config.can_bot_speak.assert_called_once_with(CHANNEL_ID)

    @pytest.mark.asyncio
    async def test_non_flag_is_ignored_without_config_lookup(self, mock_translate):
        with patch("bot.events.config_manager") as manager:
            await _handle_raw_reaction(_bot(), _payload(emoji="👍"))
            manager.get_config.assert_not_called()
        mock_translate.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [
            _payload(guild_id=None),
            _payload(member_bot=True),
            _payload(user_id=BOT_ID),
        ],
        ids=["dm", "bot_member", "self"],
    )
    async def test_ignored_sources(self, channel_config, mock_translate, payload):
        await _handle_raw_reaction(_bot(), payload)
        mock_translate.assert_not_called()

    @pytest.mark.asyncio
    async def test_member_none_is_not_treated_as_bot(self, channel_config, mock_translate):
        payload = _payload()
        payload.member = None
        message = _message()

        await _handle_raw_reaction(_bot(cached=[message]), payload)

        mock_translate.assert_awaited_once_with(message, "english")

    @pytest.mark.asyncio
    async def test_cannot_speak(self, channel_config, mock_translate):
        channel_config.can_bot_speak.return_value = False
        await _handle_raw_reaction(_bot(), _payload())
        mock_translate.assert_not_called()

    @pytest.mark.asyncio
    async def test_translation_disabled(self, channel_config, mock_translate):
        channel_config.get_translation_enabled.return_value = False
        await _handle_raw_reaction(_bot(), _payload())
        mock_translate.assert_not_called()


class TestUncachedMessage:
    @pytest.mark.asyncio
    async def test_fetches_uncached_message(self, channel_config, mock_translate):
        bot = _bot()
        fetched = _message()
        bot.get_channel.return_value.fetch_message.return_value = fetched

        await _handle_raw_reaction(bot, _payload())

        bot.get_channel.return_value.fetch_message.assert_awaited_once_with(MESSAGE_ID)
        mock_translate.assert_awaited_once_with(fetched, "english")

    @pytest.mark.asyncio
    async def test_falls_back_to_partial_messageable(self, channel_config, mock_translate):
        bot = _bot()
        bot.get_channel.return_value = None
        partial = bot.get_partial_messageable.return_value
        fetched = _message()
        partial.fetch_message = AsyncMock(return_value=fetched)

        await _handle_raw_reaction(bot, _payload())

        bot.get_partial_messageable.assert_called_with(CHANNEL_ID, guild_id=GUILD_ID)
        mock_translate.assert_awaited_once_with(fetched, "english")

    @pytest.mark.asyncio
    async def test_fetch_failure_skips_without_error_notice(self, channel_config, mock_translate):
        bot = _bot()
        bot.get_channel.return_value.fetch_message.side_effect = discord.NotFound(
            MagicMock(status=404), "gone"
        )

        await _handle_raw_reaction(bot, _payload())

        mock_translate.assert_not_called()
        bot.get_channel.return_value.send.assert_not_called()


class TestTranslationRateLimit:
    @pytest.mark.asyncio
    async def test_user_limit_adds_hourglass(self, channel_config, mock_translate, monkeypatch):
        monkeypatch.setattr(events._user_translation_limiter, "max_events", 2)
        messages = [_message(i) for i in range(3)]
        bot = _bot(cached=messages)

        for i in range(3):
            await _handle_raw_reaction(bot, _payload(message_id=i))

        assert mock_translate.await_count == 2
        partial = bot.get_partial_messageable.return_value
        partial.get_partial_message.assert_called_once_with(2)
        partial.get_partial_message.return_value.add_reaction.assert_awaited_once_with("⏳")

    @pytest.mark.asyncio
    async def test_limit_counts_reactor_not_author(
        self, channel_config, mock_translate, monkeypatch
    ):
        monkeypatch.setattr(events._user_translation_limiter, "max_events", 1)
        bot = _bot(cached=[_message(1), _message(2)])

        await _handle_raw_reaction(bot, _payload(message_id=1, user_id=10))
        await _handle_raw_reaction(bot, _payload(message_id=2, user_id=11))

        assert mock_translate.await_count == 2

    @pytest.mark.asyncio
    async def test_channel_limit_across_users(self, channel_config, mock_translate, monkeypatch):
        monkeypatch.setattr(events._channel_translation_limiter, "max_events", 2)
        bot = _bot(cached=[_message(i) for i in range(3)])

        for i in range(3):
            await _handle_raw_reaction(bot, _payload(message_id=i, user_id=100 + i))

        assert mock_translate.await_count == 2

    @pytest.mark.asyncio
    async def test_channel_rejection_does_not_consume_user_quota(
        self, channel_config, mock_translate, monkeypatch
    ):
        monkeypatch.setattr(events._user_translation_limiter, "max_events", 1)
        monkeypatch.setattr(events._channel_translation_limiter, "max_events", 1)
        bot = _bot(cached=[_message(1), _message(2)])

        await _handle_raw_reaction(bot, _payload(message_id=1, user_id=10))
        await _handle_raw_reaction(bot, _payload(message_id=2, user_id=11))

        assert (GUILD_ID, 11) not in events._user_translation_limiter._events

    @pytest.mark.asyncio
    async def test_already_translated_does_not_consume_quota(
        self, channel_config, mock_translate, monkeypatch
    ):
        monkeypatch.setattr(events._user_translation_limiter, "max_events", 1)
        events._translated_messages[(MESSAGE_ID, "english")] = events.time.monotonic()
        bot = _bot(cached=[_message()])

        await _handle_raw_reaction(bot, _payload())

        mock_translate.assert_not_called()
        assert (GUILD_ID, USER_ID) not in events._user_translation_limiter._events

    @pytest.mark.asyncio
    async def test_expired_claim_is_not_treated_as_translated(
        self, channel_config, mock_translate
    ):
        with patch("config.TRANSLATION_DEDUP_SECONDS", 100):
            events._translated_messages[(MESSAGE_ID, "english")] = events.time.monotonic() - 100
            await _handle_raw_reaction(_bot(cached=[_message()]), _payload())

        mock_translate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_hourglass_failure_is_logged(self, channel_config, mock_translate, monkeypatch):
        monkeypatch.setattr(events._user_translation_limiter, "max_events", 1)
        bot = _bot(cached=[_message(1), _message(2)])
        add_reaction = bot.get_partial_messageable.return_value.get_partial_message.return_value
        add_reaction.add_reaction.side_effect = discord.HTTPException(MagicMock(), "x")

        await _handle_raw_reaction(bot, _payload(message_id=1))
        with patch("bot.events.logger") as mock_logger:
            await _handle_raw_reaction(bot, _payload(message_id=2))

        assert mock_translate.await_count == 1
        assert any(c.kwargs.get("exc_info") for c in mock_logger.warning.call_args_list)


    @pytest.mark.asyncio
    async def test_hourglass_sent_once_per_message(self, channel_config, mock_translate, monkeypatch):
        monkeypatch.setattr(events._user_translation_limiter, "max_events", 1)
        bot = _bot(cached=[_message(1), _message(2)])

        await _handle_raw_reaction(bot, _payload(message_id=1))
        for _ in range(3):
            await _handle_raw_reaction(bot, _payload(message_id=2))

        partial = bot.get_partial_messageable.return_value
        partial.get_partial_message.return_value.add_reaction.assert_awaited_once_with("⏳")

class TestReactionErrorNotice:
    @pytest.mark.asyncio
    async def test_error_notice_is_throttled_per_channel(self, channel_config, mock_translate):
        mock_translate.side_effect = RuntimeError("boom")
        bot = _bot(cached=[_message(1), _message(2)])
        channel = bot.get_channel.return_value

        await _handle_raw_reaction(bot, _payload(message_id=1))
        await _handle_raw_reaction(bot, _payload(message_id=2))

        channel.send.assert_awaited_once()
        assert "エラーが発生しました" in channel.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_error_notice_is_separate_per_channel(self, channel_config, mock_translate):
        mock_translate.side_effect = RuntimeError("boom")
        bot = _bot(cached=[_message(1), _message(2)])

        await _handle_raw_reaction(bot, _payload(message_id=1, channel_id=10))
        await _handle_raw_reaction(bot, _payload(message_id=2, channel_id=11))

        assert bot.get_channel.return_value.send.await_count == 2

    @pytest.mark.asyncio
    async def test_error_notice_send_failure_is_logged(self, channel_config, mock_translate):
        mock_translate.side_effect = RuntimeError("boom")
        bot = _bot(cached=[_message()])
        bot.get_channel.return_value.send.side_effect = discord.Forbidden(
            MagicMock(status=403), "no"
        )

        with patch("bot.events.logger") as mock_logger:
            await _handle_raw_reaction(bot, _payload())

        mock_logger.error.assert_called_once()
        assert mock_logger.warning.call_args.kwargs.get("exc_info") is True


def test_setup_events_registers_raw_reaction_handler():
    bot = MagicMock()
    registered = []
    bot.event.side_effect = lambda f: registered.append(f.__name__) or f

    events.setup_events(bot, MagicMock())

    assert "on_raw_reaction_add" in registered
    assert "on_reaction_add" not in registered
