"""自発会話 (issue #104): 沈黙明けに、会話に残った未解決の話題へさりげなく触れる

タイマーループ（bot/discord_bot.py）から ``run_proactive_check`` を呼ぶ。``on_message`` には
依存せず、opt-in したチャンネルのうち登録簿で自分が担当のチャンネルだけを対象にする。

判定に使う時刻（最後の人間の発言・自分の発言・前回の自発会話）は永続化される
``ChannelContext`` に持つ。チャンネルバッファは TTL で消えるため沈黙の判定には使わない。
"""

import asyncio
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands

import config
from ai.conversation import generate_proactive_message, get_or_reset_conversation
from log_utils.logger import logger
from memory.channel_context import ChannelContext, get_channel_context_store
from memory.open_topics import OpenTopic, format_now_jst
from memory.short_term import ChannelMessage, format_context_line, get_channel_buffer
from utils.channel_config import ChannelConfigManager
from utils.proactive_registry import get_proactive_registry
from utils.text_utils import split_message, truncate_text

# 生成プロンプトに渡す直近ログの件数（Discord の履歴から取得する）
RECENT_HISTORY_LIMIT = 10


@lru_cache(maxsize=None)
def _zone(name: str) -> ZoneInfo:
    """タイムゾーンを取得する（起動時に検証済みの名前を渡す）"""
    return ZoneInfo(name)


def is_quiet_time(now: datetime, quiet_hours: tuple[int, int] | None, tz: ZoneInfo) -> bool:
    """静音時間帯かを判定する（開始を含み終了を含まない。日またぎにも対応する）

    Args:
        now: 判定する時刻（aware）
        quiet_hours: (開始時, 終了時)。None なら静音時間帯なし
        tz: 判定に使うタイムゾーン

    Returns:
        静音時間帯なら True
    """
    if quiet_hours is None:
        return False
    start, end = quiet_hours
    hour = now.astimezone(tz).hour
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def _skip_reason(ctx: ChannelContext, now: datetime) -> str | None:
    """話題によらない送信条件を確認し、送れない理由を返す（送れるなら None）"""
    human_at = ctx.last_human_message_at
    if human_at is None:
        return "最後の人間の発言時刻が不明"
    if ctx.last_self_message_at is not None and ctx.last_self_message_at >= human_at:
        return "最後の発言が自分"
    if now - human_at < timedelta(minutes=config.PROACTIVE_MIN_SILENCE_MINUTES):
        return "沈黙が短い"
    quiet = config.parse_quiet_hours(config.PROACTIVE_QUIET_HOURS)
    if is_quiet_time(now, quiet, _zone(config.PROACTIVE_TIMEZONE)):
        return "静音時間帯"
    cooldown = timedelta(hours=config.PROACTIVE_COOLDOWN_HOURS)
    if ctx.last_proactive_at is not None and now - ctx.last_proactive_at < cooldown:
        return "クールダウン中"
    return None


def select_topic(
    ctx: ChannelContext, now: datetime, within_max_silence: bool
) -> OpenTopic | None:
    """触れる話題を1件選ぶ

    言及済みの話題は除く。``follow_up_after`` を過ぎてウィンドウ内の話題を優先し
    （沈黙の上限は無視する）、なければ沈黙が上限内のときだけ ``follow_up_after`` を
    持たない話題から選ぶ。時刻前・ウィンドウ超過の話題は選ばない。

    Args:
        ctx: チャンネルコンテキスト
        now: 現在時刻（UTC）
        within_max_silence: 沈黙が PROACTIVE_MAX_SILENCE_HOURS 以内か

    Returns:
        選んだ話題。候補がなければ None
    """
    mentioned = set(ctx.mentioned_topic_ids)
    candidates = [t for t in ctx.open_topics if t.id not in mentioned]
    window = timedelta(hours=config.PROACTIVE_FOLLOW_UP_WINDOW_HOURS)
    due = [
        t
        for t in candidates
        if t.follow_up_after is not None
        and t.follow_up_after <= now <= t.follow_up_after + window
    ]
    if due:
        # ウィンドウが先に閉じる（時刻の早い）話題から触れる
        return min(due, key=lambda t: t.follow_up_after or now)
    if not within_max_silence:
        return None
    return next((t for t in candidates if t.follow_up_after is None), None)


def plan_proactive(ctx: ChannelContext, now: datetime) -> OpenTopic | None:
    """送信条件を満たしていれば、触れる話題を返す

    Args:
        ctx: チャンネルコンテキスト
        now: 現在時刻（UTC）

    Returns:
        触れる話題。送らない場合は None
    """
    reason = _skip_reason(ctx, now)
    if reason is not None or ctx.last_human_message_at is None:
        logger.debug(f"自発会話をスキップ: channel_id={ctx.channel_id}, 理由={reason}")
        return None
    silence = now - ctx.last_human_message_at
    within_max = silence <= timedelta(hours=config.PROACTIVE_MAX_SILENCE_HOURS)
    topic = select_topic(ctx, now, within_max)
    if topic is None:
        logger.debug(f"自発会話をスキップ: channel_id={ctx.channel_id}, 理由=触れる話題がない")
    return topic


async def run_proactive_check(bot: commands.Bot) -> None:
    """担当チャンネルを1巡して、条件を満たすチャンネルで自発会話を送る

    1チャンネルの失敗で他のチャンネルの判定を止めない。例外を外に出さない
    （``tasks.loop`` は例外でループが止まるため）。

    Args:
        bot: Discordクライアント
    """
    try:
        channels = await _collect_target_channels(bot)
    except Exception:
        logger.error("自発会話の対象チャンネルの収集に失敗しました", exc_info=True)
        return
    for channel in channels:
        try:
            await _maybe_speak(bot, channel)
        except Exception:
            logger.error(
                f"自発会話の処理中にエラーが発生しました: channel_id={channel.id}",
                exc_info=True,
            )


async def _collect_target_channels(bot: commands.Bot) -> list[discord.TextChannel]:
    """全ギルドから自発会話の対象チャンネルを集める（1ギルドの失敗で止めない）"""
    targets: list[discord.TextChannel] = []
    for guild in bot.guilds:
        try:
            targets.extend(await _guild_target_channels(guild))
        except Exception:
            logger.error(
                f"自発会話の対象チャンネルの取得に失敗しました: guild_id={guild.id}",
                exc_info=True,
            )
    return targets


async def _guild_target_channels(guild: discord.Guild) -> list[discord.TextChannel]:
    """opt-in 済み・発言可能・自分が担当のテキストチャンネルを返す（スレッドは除く）"""
    manager = ChannelConfigManager.get_instance()
    channel_config = await asyncio.to_thread(manager.get_config, guild.id)
    targets: list[discord.TextChannel] = []
    for raw_id in channel_config.get_proactive_channels():
        channel = _resolve_text_channel(guild, raw_id)
        if channel is None or not channel_config.can_bot_speak(channel.id):
            continue
        if await _is_owner(channel.id):
            targets.append(channel)
    return targets


def _resolve_text_channel(guild: discord.Guild, raw_id: str) -> discord.TextChannel | None:
    """チャンネルIDからテキストチャンネルを取得する（取得できない・スレッド等は None）"""
    try:
        channel = guild.get_channel(int(raw_id))
    except ValueError:
        return None
    return channel if isinstance(channel, discord.TextChannel) else None


async def _is_owner(channel_id: int) -> bool:
    """登録簿でこのインスタンスがチャンネルの担当かを確認する"""
    owner = await asyncio.to_thread(get_proactive_registry().get_owner, channel_id)
    return owner == config.INSTANCE_NAME


async def _maybe_speak(bot: commands.Bot, channel: discord.TextChannel) -> None:
    """1チャンネル分の判定・生成・送信・記録を行う"""
    ctx = await asyncio.to_thread(get_channel_context_store().get_context, channel.id)
    if ctx.load_failed:
        return
    now = datetime.now(timezone.utc)
    topic = plan_proactive(ctx, now)
    if topic is None:
        return
    history = await _fetch_recent_history(channel)
    if history is None or not _history_allows(history, bot, now):
        return
    human_at = ctx.last_human_message_at
    message = await asyncio.to_thread(
        generate_proactive_message,
        ctx.format_for_injection(),
        _format_history(history),
        topic.text,
        topic.kind,
        format_now_jst(now),
    )
    if not message:
        return
    # 生成中に人間が発言した・担当が変わった場合は送らない
    if ctx.last_human_message_at != human_at or not await _is_owner(channel.id):
        logger.info(f"生成中に状況が変わったため自発会話を見送りました: channel_id={channel.id}")
        return
    if await _send(channel, message):
        await _record_sent(channel, ctx, topic, message)


async def _fetch_recent_history(channel: discord.TextChannel) -> list[discord.Message] | None:
    """チャンネルの直近のメッセージを新しい順に取得する（失敗したら None）"""
    try:
        return [m async for m in channel.history(limit=RECENT_HISTORY_LIMIT)]
    except discord.HTTPException:
        logger.warning(
            f"自発会話用の履歴取得に失敗したため見送ります: channel_id={channel.id}",
            exc_info=True,
        )
        return None


def _history_allows(history: list[discord.Message], bot: commands.Bot, now: datetime) -> bool:
    """Discord の実際の履歴でも沈黙していて、最後の発言が自分ではないかを確認する

    ChannelContext の時刻は要約時・終了時にしか永続化されず、クラッシュ後は古い値が
    残りうるため、送る直前に実際の履歴で確かめる。

    Args:
        history: 直近のメッセージ（新しい順）
        bot: Discordクライアント
        now: 現在時刻（UTC）

    Returns:
        送ってよい場合 True
    """
    if not history:
        return True
    latest = history[0]
    if bot.user is not None and latest.author.id == bot.user.id:
        logger.debug(f"自発会話をスキップ: channel_id={latest.channel.id}, 理由=履歴の最後が自分")
        return False
    threshold = now - timedelta(minutes=config.PROACTIVE_MIN_SILENCE_MINUTES)
    if latest.created_at > threshold:
        logger.debug(f"自発会話をスキップ: channel_id={latest.channel.id}, 理由=履歴上は沈黙が短い")
        return False
    return True


def _format_history(history: list[discord.Message]) -> str:
    """直近のメッセージを古い順の会話ログにする（1発言1行、偽装対策済み）"""
    lines = [
        format_context_line(_to_channel_message(m))
        for m in reversed(history)
        if m.content
    ]
    return "\n".join(lines)


def _to_channel_message(message: discord.Message) -> ChannelMessage:
    """Discord のメッセージを ChannelMessage にする"""
    return ChannelMessage(
        message_id=message.id,
        channel_id=message.channel.id,
        guild_id=message.guild.id if message.guild else None,
        author_id=message.author.id,
        author_name=message.author.display_name,
        content=message.content,
        timestamp=message.created_at,
        is_bot=message.author.bot,
    )


async def _send(channel: discord.TextChannel, message: str) -> bool:
    """チャンネルに直接送信する（1チャンクでも送れたら True）"""
    sent = 0
    try:
        for chunk in split_message(message):
            await channel.send(chunk)
            sent += 1
    except discord.HTTPException:
        logger.error(f"自発会話の送信に失敗しました: channel_id={channel.id}", exc_info=True)
    return sent > 0


async def _record_sent(
    channel: discord.TextChannel, ctx: ChannelContext, topic: OpenTopic, message: str
) -> None:
    """送信した自発会話を、コンテキスト・会話履歴・バッファ・judge に記録する

    二度と同じ話題に触れないよう、コンテキストへの記録と保存を最初に行う。
    """
    from memory.judge import get_judge

    sent_at = datetime.now(timezone.utc)
    ctx.record_proactive(topic.id, sent_at)
    await asyncio.to_thread(get_channel_context_store().save_context, ctx)
    await get_or_reset_conversation(str(channel.id)).add_proactive_turn(message)
    me = channel.guild.me
    get_channel_buffer().add_message(
        ChannelMessage(
            message_id=0,
            channel_id=channel.id,
            guild_id=channel.guild.id,
            author_id=me.id,
            author_name=me.display_name,
            content=message,
            timestamp=sent_at,
            is_bot=True,
        )
    )
    get_judge().record_response(channel.id)
    logger.info(
        f"自発会話を送信しました: channel_id={channel.id}, topic_id={topic.id}, "
        f"kind={topic.kind}, 内容={truncate_text(message)}"
    )
