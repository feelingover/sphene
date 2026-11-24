"""自発会話（memory/proactive.py）のテスト"""

# type: ignore
# mypy: ignore-errors

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import discord
import pytest

from memory import proactive
from memory.channel_context import ChannelContext
from memory.fact_store import Fact
from memory.open_topics import OpenTopic
from memory.proactive import (
    ProactiveTarget,
    _history_allows,
    is_quiet_time,
    load_shareable_facts,
    plan_proactive,
    run_proactive_check,
    select_fact,
    select_topic,
)

JST = ZoneInfo("Asia/Tokyo")
# JST 12:00（静音時間帯 0-8 の外）
NOW = datetime(2026, 11, 24, 3, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def proactive_config():
    """自発会話の設定を既定値に固定する"""
    values = {
        "PROACTIVE_MIN_SILENCE_MINUTES": 120,
        "PROACTIVE_MAX_SILENCE_HOURS": 24,
        "PROACTIVE_COOLDOWN_HOURS": 24,
        "PROACTIVE_FACT_COOLDOWN_HOURS": 72,
        "PROACTIVE_QUIET_HOURS": "0-8",
        "PROACTIVE_TIMEZONE": "Asia/Tokyo",
        "PROACTIVE_FOLLOW_UP_WINDOW_HOURS": 24,
        "INSTANCE_NAME": "me",
    }
    patches = [patch(f"config.{k}", v) for k, v in values.items()]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


@pytest.fixture(autouse=True)
def fact_store():
    """実際の FactStore に触れないよう、shareable な fact なしで固定する"""
    store = MagicMock()
    store.get_shareable_facts.return_value = []
    with patch("memory.proactive.get_fact_store", return_value=store):
        yield store


def _fact(fact_id="f1", content="Aさんは猫を飼っている"):
    return Fact(
        fact_id=fact_id,
        channel_id=100,
        content=content,
        keywords=[],
        source_user_ids=[1],
        created_at=NOW - timedelta(days=1),
        shareable=True,
    )


def _topic(topic_id="t1", follow_up_after=None, kind="plan", text="週末に零式に挑戦する"):
    return OpenTopic(id=topic_id, text=text, kind=kind, follow_up_after=follow_up_after)


def _ctx(silence=timedelta(hours=3), self_at=None, topics=None, **kwargs):
    human_at = NOW - silence if silence is not None else None
    return ChannelContext(
        channel_id=100,
        summary="要約",
        last_human_message_at=human_at,
        last_self_message_at=self_at,
        open_topics=topics if topics is not None else [_topic()],
        **kwargs,
    )


class TestIsQuietTime:
    """静音時間帯の判定"""

    @pytest.mark.parametrize(
        ("hour", "expected"),
        [(0, True), (7, True), (8, False), (23, False), (12, False)],
    )
    def test_same_day_range_includes_start_excludes_end(self, hour, expected):
        now = datetime(2026, 11, 24, hour, 0, tzinfo=JST)
        assert is_quiet_time(now, (0, 8), JST) is expected

    def test_boundary_one_minute_before_end(self):
        now = datetime(2026, 11, 24, 7, 59, tzinfo=JST)
        assert is_quiet_time(now, (0, 8), JST) is True

    @pytest.mark.parametrize(
        ("hour", "expected"),
        [(22, True), (23, True), (0, True), (5, True), (6, False), (21, False), (12, False)],
    )
    def test_overnight_range(self, hour, expected):
        now = datetime(2026, 11, 24, hour, 0, tzinfo=JST)
        assert is_quiet_time(now, (22, 6), JST) is expected

    def test_none_means_never_quiet(self):
        assert is_quiet_time(NOW, None, JST) is False

    def test_converts_utc_to_timezone(self):
        # UTC 20:00 = JST 05:00（静音時間帯内）
        now = datetime(2026, 11, 24, 20, 0, tzinfo=timezone.utc)
        assert is_quiet_time(now, (0, 8), JST) is True


class TestPlanProactiveConditions:
    """話題によらない送信条件"""

    def test_sends_when_all_conditions_met(self):
        assert plan_proactive(_ctx(), NOW).id == "t1"

    def test_unknown_last_human_time_skips(self):
        assert plan_proactive(_ctx(silence=None), NOW) is None

    def test_silence_at_min_boundary_sends(self):
        assert plan_proactive(_ctx(silence=timedelta(minutes=120)), NOW) is not None

    def test_silence_below_min_skips(self):
        assert plan_proactive(_ctx(silence=timedelta(minutes=119)), NOW) is None

    def test_silence_at_max_boundary_sends(self):
        assert plan_proactive(_ctx(silence=timedelta(hours=24)), NOW) is not None

    def test_silence_over_max_skips(self):
        ctx = _ctx(silence=timedelta(hours=24, minutes=1))
        assert plan_proactive(ctx, NOW) is None

    def test_last_speaker_self_skips(self):
        ctx = _ctx(self_at=NOW - timedelta(hours=2))
        assert plan_proactive(ctx, NOW) is None

    def test_self_at_same_time_as_human_skips(self):
        ctx = _ctx()
        ctx.last_self_message_at = ctx.last_human_message_at
        assert plan_proactive(ctx, NOW) is None

    def test_self_before_human_sends(self):
        ctx = _ctx(self_at=NOW - timedelta(hours=5))
        assert plan_proactive(ctx, NOW) is not None

    def test_quiet_hours_skip(self):
        quiet_now = datetime(2026, 11, 24, 7, 59, tzinfo=JST).astimezone(timezone.utc)
        ctx = _ctx()
        ctx.last_human_message_at = quiet_now - timedelta(hours=3)
        assert plan_proactive(ctx, quiet_now) is None

    def test_quiet_hours_end_boundary_sends(self):
        end_now = datetime(2026, 11, 24, 8, 0, tzinfo=JST).astimezone(timezone.utc)
        ctx = _ctx()
        ctx.last_human_message_at = end_now - timedelta(hours=3)
        assert plan_proactive(ctx, end_now) is not None

    def test_cooldown_skips(self):
        ctx = _ctx(last_proactive_at=NOW - timedelta(hours=23, minutes=59))
        assert plan_proactive(ctx, NOW) is None

    def test_cooldown_boundary_sends(self):
        ctx = _ctx(last_proactive_at=NOW - timedelta(hours=24))
        assert plan_proactive(ctx, NOW) is not None

    def test_no_topics_skips(self):
        assert plan_proactive(_ctx(topics=[]), NOW) is None


class TestFollowUp:
    """follow_up_after を持つ話題"""

    def test_before_follow_up_time_not_selected(self):
        ctx = _ctx(topics=[_topic(follow_up_after=NOW + timedelta(minutes=1))])
        assert plan_proactive(ctx, NOW) is None

    def test_within_window_selected(self):
        ctx = _ctx(topics=[_topic(follow_up_after=NOW - timedelta(hours=1))])
        assert plan_proactive(ctx, NOW).id == "t1"

    def test_window_end_boundary_selected(self):
        ctx = _ctx(topics=[_topic(follow_up_after=NOW - timedelta(hours=24))])
        assert plan_proactive(ctx, NOW) is not None

    def test_past_window_not_selected(self):
        ctx = _ctx(topics=[_topic(follow_up_after=NOW - timedelta(hours=24, minutes=1))])
        assert plan_proactive(ctx, NOW) is None

    def test_ignores_max_silence(self):
        ctx = _ctx(
            silence=timedelta(days=3),
            topics=[_topic(follow_up_after=NOW - timedelta(hours=1))],
        )
        assert plan_proactive(ctx, NOW).id == "t1"

    def test_plain_topic_not_selected_over_max_silence(self):
        ctx = _ctx(silence=timedelta(days=3), topics=[_topic()])
        assert plan_proactive(ctx, NOW) is None

    def test_follow_up_still_respects_min_silence(self):
        ctx = _ctx(
            silence=timedelta(minutes=30),
            topics=[_topic(follow_up_after=NOW - timedelta(hours=1))],
        )
        assert plan_proactive(ctx, NOW) is None

    def test_follow_up_still_respects_cooldown(self):
        ctx = _ctx(
            topics=[_topic(follow_up_after=NOW - timedelta(hours=1))],
            last_proactive_at=NOW - timedelta(hours=1),
        )
        assert plan_proactive(ctx, NOW) is None

    def test_follow_up_still_respects_quiet_hours(self):
        quiet_now = datetime(2026, 11, 24, 3, 0, tzinfo=JST).astimezone(timezone.utc)
        ctx = _ctx(topics=[_topic(follow_up_after=quiet_now - timedelta(hours=1))])
        ctx.last_human_message_at = quiet_now - timedelta(hours=3)
        assert plan_proactive(ctx, quiet_now) is None


class TestSelectTopic:
    """話題の選び方"""

    def test_due_follow_up_preferred_over_plain(self):
        topics = [_topic("plain"), _topic("due", follow_up_after=NOW - timedelta(hours=1))]
        assert select_topic(_ctx(topics=topics), NOW, True).id == "due"

    def test_earliest_due_first(self):
        topics = [
            _topic("late", follow_up_after=NOW - timedelta(hours=1)),
            _topic("early", follow_up_after=NOW - timedelta(hours=5)),
        ]
        assert select_topic(_ctx(topics=topics), NOW, True).id == "early"

    def test_falls_back_to_plain_when_follow_up_not_due(self):
        topics = [_topic("future", follow_up_after=NOW + timedelta(hours=1)), _topic("plain")]
        assert select_topic(_ctx(topics=topics), NOW, True).id == "plain"

    def test_excludes_mentioned(self):
        topics = [_topic("a"), _topic("b")]
        ctx = _ctx(topics=topics, mentioned_topic_ids=["a"])
        assert select_topic(ctx, NOW, True).id == "b"

    def test_all_mentioned_returns_none(self):
        due = _topic("a", follow_up_after=NOW - timedelta(hours=1))
        ctx = _ctx(topics=[due], mentioned_topic_ids=["a"])
        assert select_topic(ctx, NOW, True) is None


def _message(author_id, created_at, content="hi", bot=False):
    msg = MagicMock()
    msg.author.id = author_id
    msg.author.bot = bot
    msg.author.display_name = f"user{author_id}"
    msg.created_at = created_at
    msg.content = content
    msg.channel.id = 100
    msg.guild.id = 1
    msg.id = author_id * 10
    return msg


def _bot(user_id=999):
    bot = MagicMock()
    bot.user.id = user_id
    return bot


class TestHistoryAllows:
    """送信直前の Discord 履歴による確認"""

    def test_empty_history_allows(self):
        assert _history_allows([], _bot(), NOW) is True

    def test_latest_self_blocks(self):
        history = [_message(999, NOW - timedelta(hours=3))]
        assert _history_allows(history, _bot(), NOW) is False

    def test_recent_message_blocks(self):
        history = [_message(1, NOW - timedelta(minutes=10))]
        assert _history_allows(history, _bot(), NOW) is False

    def test_old_human_message_allows(self):
        history = [_message(1, NOW - timedelta(hours=3))]
        assert _history_allows(history, _bot(), NOW) is True


def _text_channel(channel_id=100):
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = channel_id
    channel.guild.id = 1
    channel.guild.me.id = 999
    channel.guild.me.display_name = "スフェーン"
    channel.send = AsyncMock()
    return channel


def _async_history(messages):
    async def gen(limit):
        for m in messages:
            yield m

    return gen


class _Env:
    """_maybe_speak 周りの依存をまとめてモックする"""

    def __init__(self, ctx, owner="me", generated="こんにちは！"):
        self.ctx = ctx
        self.store = MagicMock()
        self.store.get_context.return_value = ctx
        self.store.save_context.return_value = True
        self.registry = MagicMock()
        self.registry.get_owner.return_value = owner
        self.buffer = MagicMock()
        self.judge = MagicMock()
        self.conversation = MagicMock()
        self.conversation.add_proactive_turn = AsyncMock()
        self.generate = MagicMock(return_value=generated)
        self._patches = [
            patch("memory.proactive.get_channel_context_store", return_value=self.store),
            patch("memory.proactive.get_proactive_registry", return_value=self.registry),
            patch("memory.proactive.get_channel_buffer", return_value=self.buffer),
            patch("memory.judge.get_judge", return_value=self.judge),
            patch("memory.proactive.get_or_reset_conversation", return_value=self.conversation),
            patch("memory.proactive.generate_proactive_message", self.generate),
            patch("memory.proactive.datetime", wraps=datetime),
        ]

    def __enter__(self):
        mocks = [p.start() for p in self._patches]
        mocks[-1].now.return_value = NOW
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


class TestMaybeSpeak:
    """生成・送信・記録"""

    @pytest.mark.asyncio
    async def test_sends_and_records_everything(self):
        channel = _text_channel()
        channel.history = _async_history([_message(1, NOW - timedelta(hours=3))])
        with _Env(_ctx()) as env:
            await proactive._maybe_speak(_bot(), channel)

        channel.send.assert_awaited_once_with("こんにちは！")
        assert env.ctx.mentioned_topic_ids == ["t1"]
        assert env.ctx.last_proactive_at is not None
        assert env.ctx.last_self_message_at == env.ctx.last_proactive_at
        env.store.save_context.assert_called_once_with(env.ctx)
        env.conversation.add_proactive_turn.assert_awaited_once_with("こんにちは！")
        added = env.buffer.add_message.call_args.args[0]
        assert added.is_bot is True and added.content == "こんにちは！"
        assert added.author_id == 999
        env.judge.record_response.assert_called_once_with(100)

    @pytest.mark.asyncio
    async def test_generation_receives_summary_log_and_topic(self):
        channel = _text_channel()
        channel.history = _async_history(
            [_message(2, NOW - timedelta(hours=3), "二件目"), _message(1, NOW - timedelta(hours=4), "一件目")]
        )
        with _Env(_ctx()) as env:
            await proactive._maybe_speak(_bot(), channel)

        summary, log, text, kind, _now = env.generate.call_args.args
        assert "要約" in summary
        assert log.index("一件目") < log.index("二件目")
        assert (text, kind) == ("週末に零式に挑戦する", "plan")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("generated", [None, ""])
    async def test_no_message_does_not_send(self, generated):
        channel = _text_channel()
        channel.history = _async_history([])
        with _Env(_ctx(), generated=generated) as env:
            await proactive._maybe_speak(_bot(), channel)

        channel.send.assert_not_awaited()
        assert env.ctx.mentioned_topic_ids == []
        env.judge.record_response.assert_not_called()

    @pytest.mark.asyncio
    async def test_ineligible_does_not_generate(self):
        channel = _text_channel()
        with _Env(_ctx(silence=None)) as env:
            await proactive._maybe_speak(_bot(), channel)
        env.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_load_failed_context_skips(self):
        channel = _text_channel()
        ctx = _ctx()
        ctx.load_failed = True
        with _Env(ctx) as env:
            await proactive._maybe_speak(_bot(), channel)
        env.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_history_blocks_generation(self):
        channel = _text_channel()
        channel.history = _async_history([_message(999, NOW - timedelta(hours=3))])
        with _Env(_ctx()) as env:
            await proactive._maybe_speak(_bot(), channel)
        env.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_history_fetch_failure_skips(self):
        channel = _text_channel()

        def failing(limit):
            raise discord.HTTPException(MagicMock(status=403), "forbidden")

        channel.history = failing
        with _Env(_ctx()) as env:
            await proactive._maybe_speak(_bot(), channel)
        env.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_owner_changed_before_send_skips(self):
        channel = _text_channel()
        channel.history = _async_history([])
        with _Env(_ctx(), owner="other") as env:
            await proactive._maybe_speak(_bot(), channel)
        channel.send.assert_not_awaited()
        assert env.ctx.last_proactive_at is None

    @pytest.mark.asyncio
    async def test_human_spoke_during_generation_skips(self):
        channel = _text_channel()
        channel.history = _async_history([])
        with _Env(_ctx()) as env:

            def generate(*args, **kwargs):
                env.ctx.last_human_message_at = NOW
                return "こんにちは！"

            env.generate.side_effect = generate
            await proactive._maybe_speak(_bot(), channel)
        channel.send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_send_failure_does_not_record(self):
        channel = _text_channel()
        channel.history = _async_history([])
        channel.send.side_effect = discord.HTTPException(MagicMock(status=500), "err")
        with _Env(_ctx()) as env:
            await proactive._maybe_speak(_bot(), channel)
        assert env.ctx.mentioned_topic_ids == []
        env.store.save_context.assert_not_called()

    @pytest.mark.asyncio
    async def test_mentioned_topic_never_reused(self):
        channel = _text_channel()
        channel.history = _async_history([])
        ctx = _ctx()
        with _Env(ctx) as env:
            await proactive._maybe_speak(_bot(), channel)
            # クールダウンが明けても、同じ話題には触れない
            ctx.last_proactive_at = NOW - timedelta(days=2)
            ctx.last_self_message_at = None
            env.generate.reset_mock()
            await proactive._maybe_speak(_bot(), channel)
        env.generate.assert_not_called()


def _guild(channels, proactive_ids, can_speak=True):
    guild = MagicMock()
    guild.id = 1
    guild.get_channel.side_effect = lambda cid: channels.get(cid)
    channel_config = MagicMock()
    channel_config.get_proactive_channels.return_value = proactive_ids
    channel_config.can_bot_speak.return_value = can_speak
    return guild, channel_config


class TestTargetChannels:
    """対象チャンネルの収集"""

    async def _collect(self, guild, channel_config, owner="me"):
        bot = MagicMock()
        bot.guilds = [guild]
        manager = MagicMock()
        manager.get_config.return_value = channel_config
        registry = MagicMock()
        registry.get_owner.return_value = owner
        with (
            patch("memory.proactive.ChannelConfigManager.get_instance", return_value=manager),
            patch("memory.proactive.get_proactive_registry", return_value=registry),
        ):
            return await proactive._collect_target_channels(bot)

    @pytest.mark.asyncio
    async def test_owner_text_channel_collected(self):
        channel = _text_channel(100)
        guild, cfg = _guild({100: channel}, ["100"])
        assert await self._collect(guild, cfg) == [channel]

    @pytest.mark.asyncio
    async def test_other_owner_excluded(self):
        guild, cfg = _guild({100: _text_channel(100)}, ["100"])
        assert await self._collect(guild, cfg, owner="other") == []

    @pytest.mark.asyncio
    async def test_unregistered_excluded(self):
        guild, cfg = _guild({100: _text_channel(100)}, ["100"])
        assert await self._collect(guild, cfg, owner=None) == []

    @pytest.mark.asyncio
    async def test_not_opted_in_excluded(self):
        guild, cfg = _guild({100: _text_channel(100)}, [])
        assert await self._collect(guild, cfg) == []

    @pytest.mark.asyncio
    async def test_cannot_speak_excluded(self):
        guild, cfg = _guild({100: _text_channel(100)}, ["100"], can_speak=False)
        assert await self._collect(guild, cfg) == []

    @pytest.mark.asyncio
    async def test_thread_and_missing_and_invalid_ids_excluded(self):
        thread = MagicMock(spec=discord.Thread)
        guild, cfg = _guild({200: thread}, ["200", "300", "abc"])
        assert await self._collect(guild, cfg) == []

    @pytest.mark.asyncio
    async def test_guild_failure_does_not_stop_others(self):
        bot = MagicMock()
        bad = MagicMock(id=2)
        channel = _text_channel(100)
        good, cfg = _guild({100: channel}, ["100"])
        bot.guilds = [bad, good]
        manager = MagicMock()
        manager.get_config.side_effect = lambda gid: (_ for _ in ()).throw(RuntimeError()) if gid == 2 else cfg
        registry = MagicMock()
        registry.get_owner.return_value = "me"
        with (
            patch("memory.proactive.ChannelConfigManager.get_instance", return_value=manager),
            patch("memory.proactive.get_proactive_registry", return_value=registry),
        ):
            assert await proactive._collect_target_channels(bot) == [channel]


class TestRunProactiveCheck:
    """ループ1回分"""

    @pytest.mark.asyncio
    async def test_one_channel_error_does_not_stop_others(self):
        ch1, ch2 = _text_channel(1), _text_channel(2)
        speak = AsyncMock(side_effect=[RuntimeError("boom"), None])
        with (
            patch("memory.proactive._collect_target_channels", AsyncMock(return_value=[ch1, ch2])),
            patch("memory.proactive._maybe_speak", speak),
        ):
            await run_proactive_check(MagicMock())
        assert speak.await_count == 2

    @pytest.mark.asyncio
    async def test_collect_failure_does_not_raise(self):
        with patch(
            "memory.proactive._collect_target_channels", AsyncMock(side_effect=RuntimeError())
        ):
            await run_proactive_check(MagicMock())


def _facts_loader(*facts):
    return MagicMock(return_value=list(facts))


class TestFactFallback:
    """未解決の話題がないときの facts へのフォールバック（未解決の話題 > facts）"""

    def test_open_topic_preferred_and_facts_not_loaded(self):
        loader = _facts_loader(_fact())
        target = plan_proactive(_ctx(), NOW, loader)
        assert (target.source, target.id) == ("open_topic", "t1")
        loader.assert_not_called()

    def test_no_topics_falls_back_to_fact(self):
        loader = _facts_loader(_fact())
        target = plan_proactive(_ctx(topics=[]), NOW, loader)
        assert target == ProactiveTarget(
            source="fact", id="f1", text="Aさんは猫を飼っている", kind="fact"
        )
        loader.assert_called_once_with(100)

    def test_all_topics_mentioned_falls_back_to_fact(self):
        ctx = _ctx(mentioned_topic_ids=["t1"])
        assert plan_proactive(ctx, NOW, _facts_loader(_fact())).source == "fact"

    def test_follow_up_not_yet_due_falls_back_to_fact(self):
        ctx = _ctx(topics=[_topic(follow_up_after=NOW + timedelta(hours=1))])
        assert plan_proactive(ctx, NOW, _facts_loader(_fact())).source == "fact"

    def test_follow_up_window_passed_falls_back_to_fact(self):
        ctx = _ctx(topics=[_topic(follow_up_after=NOW - timedelta(hours=25))])
        assert plan_proactive(ctx, NOW, _facts_loader(_fact())).source == "fact"

    def test_fact_respects_max_silence(self):
        loader = _facts_loader(_fact())
        ctx = _ctx(silence=timedelta(hours=24, minutes=1), topics=[])
        assert plan_proactive(ctx, NOW, loader) is None
        loader.assert_not_called()

    def test_fact_respects_min_silence(self):
        ctx = _ctx(silence=timedelta(minutes=119), topics=[])
        assert plan_proactive(ctx, NOW, _facts_loader(_fact())) is None

    def test_fact_respects_quiet_hours(self):
        quiet_now = datetime(2026, 11, 24, 3, 0, tzinfo=JST)
        ctx = _ctx(topics=[])
        ctx.last_human_message_at = quiet_now - timedelta(hours=3)
        assert plan_proactive(ctx, quiet_now, _facts_loader(_fact())) is None

    def test_fact_cooldown_active_skips_without_loading(self):
        loader = _facts_loader(_fact())
        ctx = _ctx(topics=[], last_fact_proactive_at=NOW - timedelta(hours=71, minutes=59))
        assert plan_proactive(ctx, NOW, loader) is None
        loader.assert_not_called()

    def test_fact_cooldown_boundary_sends(self):
        ctx = _ctx(topics=[], last_fact_proactive_at=NOW - timedelta(hours=72))
        assert plan_proactive(ctx, NOW, _facts_loader(_fact())).source == "fact"

    def test_combined_cooldown_also_applies_to_facts(self):
        # facts のクールダウンは明けていても、合算の1日1回が優先される
        ctx = _ctx(
            topics=[],
            last_proactive_at=NOW - timedelta(hours=23),
            last_fact_proactive_at=NOW - timedelta(days=5),
        )
        assert plan_proactive(ctx, NOW, _facts_loader(_fact())) is None

    def test_fact_cooldown_does_not_block_open_topics(self):
        ctx = _ctx(last_fact_proactive_at=NOW - timedelta(hours=30))
        assert plan_proactive(ctx, NOW, _facts_loader(_fact())).source == "open_topic"

    def test_no_shareable_facts_skips(self):
        assert plan_proactive(_ctx(topics=[]), NOW, _facts_loader()) is None

    def test_all_facts_used_skips(self):
        ctx = _ctx(topics=[], used_fact_ids=["f1", "f2"])
        loader = _facts_loader(_fact("f1"), _fact("f2"))
        assert plan_proactive(ctx, NOW, loader) is None

    def test_default_loader_uses_fact_store(self, fact_store):
        fact_store.get_shareable_facts.return_value = [_fact()]
        assert plan_proactive(_ctx(topics=[]), NOW).id == "f1"
        fact_store.get_shareable_facts.assert_called_once_with(100)


class TestSelectFact:
    """話題にする fact の選び方"""

    def test_first_in_given_order(self):
        assert select_fact(_ctx(), [_fact("f2"), _fact("f1")]).fact_id == "f2"

    def test_excludes_used(self):
        ctx = _ctx(used_fact_ids=["f1"])
        assert select_fact(ctx, [_fact("f1"), _fact("f2")]).fact_id == "f2"

    def test_skips_blank_content(self):
        assert select_fact(_ctx(), [_fact("f1", " "), _fact("f2")]).fact_id == "f2"

    def test_empty_returns_none(self):
        assert select_fact(_ctx(), []) is None


class TestLoadShareableFacts:
    def test_store_failure_returns_empty(self, fact_store):
        fact_store.get_shareable_facts.side_effect = RuntimeError("io")
        assert load_shareable_facts(100) == []


class TestMaybeSpeakFact:
    """facts での生成・送信・記録"""

    @pytest.mark.asyncio
    async def test_sends_and_records_fact(self, fact_store):
        fact_store.get_shareable_facts.return_value = [_fact()]
        channel = _text_channel()
        channel.history = _async_history([])
        with _Env(_ctx(topics=[])) as env:
            await proactive._maybe_speak(_bot(), channel)

        channel.send.assert_awaited_once_with("こんにちは！")
        args, kwargs = env.generate.call_args
        assert args[2:4] == ("Aさんは猫を飼っている", "fact")
        assert kwargs == {"source": "fact"}
        assert env.ctx.used_fact_ids == ["f1"]
        assert env.ctx.mentioned_topic_ids == []
        assert env.ctx.last_fact_proactive_at is not None
        assert env.ctx.last_proactive_at == env.ctx.last_fact_proactive_at
        env.store.save_context.assert_called_once_with(env.ctx)
        env.judge.record_response.assert_called_once_with(100)

    @pytest.mark.asyncio
    async def test_open_topic_send_does_not_touch_fact_state(self):
        channel = _text_channel()
        channel.history = _async_history([])
        with _Env(_ctx()) as env:
            await proactive._maybe_speak(_bot(), channel)
        assert env.generate.call_args.kwargs == {"source": "open_topic"}
        assert env.ctx.used_fact_ids == []
        assert env.ctx.last_fact_proactive_at is None

    @pytest.mark.asyncio
    async def test_speak_false_does_not_record_fact(self, fact_store):
        fact_store.get_shareable_facts.return_value = [_fact()]
        channel = _text_channel()
        channel.history = _async_history([])
        with _Env(_ctx(topics=[]), generated=None) as env:
            await proactive._maybe_speak(_bot(), channel)
        channel.send.assert_not_awaited()
        assert env.ctx.used_fact_ids == []
        assert env.ctx.last_fact_proactive_at is None

    @pytest.mark.asyncio
    async def test_used_fact_never_reused(self, fact_store):
        fact_store.get_shareable_facts.return_value = [_fact()]
        channel = _text_channel()
        channel.history = _async_history([])
        ctx = _ctx(topics=[])
        with _Env(ctx) as env:
            await proactive._maybe_speak(_bot(), channel)
            # 両方のクールダウンが明けても、同じ fact は使わない
            ctx.last_proactive_at = NOW - timedelta(days=10)
            ctx.last_fact_proactive_at = NOW - timedelta(days=10)
            ctx.last_self_message_at = None
            env.generate.reset_mock()
            await proactive._maybe_speak(_bot(), channel)
        env.generate.assert_not_called()
