import asyncio
import contextlib
import random
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from memory.fact_store import Fact
    from memory.judge import JudgeResult
    from memory.short_term import ChannelMessage, ChannelMessageBuffer

import discord
from discord import app_commands
from discord.ext import commands  # commands をインポート

import config

# Sphene と load_system_prompt をインポート
from ai.conversation import (
    Sphene,
    generate_short_ack,
    load_system_prompt,
    channel_conversations,
)
from log_utils.logger import logger
from utils.background_tasks import track_background_task
from utils.channel_config import ChannelConfigManager
from utils.rate_limit import SlidingWindowRateLimiter
from utils.text_utils import split_message, truncate_text

# リアクション用の絵文字リスト
_REACTION_EMOJIS = ["👀", "😊", "👍", "🤔", "✨", "💡"]

# レート制限超過時に付けるリアクション
_RATE_LIMITED_EMOJI = "⏳"

# メンション等による会話のレート制限（ユーザー単位はギルドごと、チャンネル単位は全員合計）
_user_mention_limiter = SlidingWindowRateLimiter(
    config.MENTION_RATE_LIMIT_PER_USER, config.MENTION_RATE_LIMIT_WINDOW_SECONDS
)
_channel_mention_limiter = SlidingWindowRateLimiter(
    config.MENTION_RATE_LIMIT_PER_CHANNEL, config.MENTION_RATE_LIMIT_WINDOW_SECONDS
)

# 国旗リアクション翻訳のレート制限（ユーザー単位はギルドごと、チャンネル単位は全員合計）
_user_translation_limiter = SlidingWindowRateLimiter(
    config.TRANSLATION_RATE_LIMIT_PER_USER, config.TRANSLATION_RATE_LIMIT_WINDOW_SECONDS
)
_channel_translation_limiter = SlidingWindowRateLimiter(
    config.TRANSLATION_RATE_LIMIT_PER_CHANNEL, config.TRANSLATION_RATE_LIMIT_WINDOW_SECONDS
)

# リアクション処理のエラー通知はチャンネルごとにクールダウン期間内1回まで
_reaction_error_notify_limiter = SlidingWindowRateLimiter(
    1, config.REACTION_ERROR_NOTIFY_COOLDOWN_SECONDS
)

# レート制限超過の ⏳ リアクションは、同じメッセージにはウィンドウ内で1回だけ送る（API の連打を防ぐ）
_rate_limited_reaction_limiter = SlidingWindowRateLimiter(
    1,
    max(config.MENTION_RATE_LIMIT_WINDOW_SECONDS, config.TRANSLATION_RATE_LIMIT_WINDOW_SECONDS),
)

# 翻訳済み・翻訳中の (メッセージID, 翻訳先言語) → 記録時刻 (monotonic)
_translated_messages: dict[tuple[int, str], float] = {}

# bot の型ヒントを commands.Bot に変更
def _bot_role_mention_ids(bot: commands.Bot, message: discord.Message) -> list[int]:
    """メッセージ内でメンションされた、このボットの管理ロールのIDを返す

    Discord の入力補完で ``@ボット名`` を選ぶと、ボット本人ではなく
    ボット連携時に自動作成される管理ロール宛てのメンションになることがある。

    Args:
        bot: Discordクライアント
        message: Discordメッセージオブジェクト

    Returns:
        このボットの管理ロールのIDリスト（該当なしなら空）
    """
    if bot.user is None:
        return []
    bot_id = bot.user.id
    return [
        role.id
        for role in message.role_mentions
        if role.tags is not None and role.tags.bot_id == bot_id
    ]


def _strip_bot_mentions(content: str, bot_id: int, role_ids: list[int]) -> str:
    """本文からボット本人・ボット管理ロールへのメンション記法を取り除く

    Args:
        content: メッセージ本文
        bot_id: ボットのユーザーID
        role_ids: ボットの管理ロールID

    Returns:
        メンションを除いた本文
    """
    patterns = [rf"<@!?{bot_id}>"] + [rf"<@&{role_id}>" for role_id in role_ids]
    return re.sub("|".join(patterns), "", content).strip()


async def is_bot_mentioned(
    bot: commands.Bot, message: discord.Message
) -> tuple[bool, str, bool]:
    """メッセージがボットに対するものかどうかを判断し、質問内容を抽出する

    Args:
        bot: Discordクライアント
        message: Discordメッセージオブジェクト

    Returns:
        Tuple[bool, str, bool]: (ボットに対するメッセージかどうか, 質問内容, リプライかどうか)
    """
    if message.content is None:
        return False, "", False

    content: str = message.content
    user_id = str(message.author.id)

    # メンションされた場合（ボット本人 or ボットの管理ロール宛て）
    bot_role_ids = _bot_role_mention_ids(bot, message)
    if bot.user and (bot.user in message.mentions or bot_role_ids):
        question = _strip_bot_mentions(content, bot.user.id, bot_role_ids)
        preview = truncate_text(question)
        logger.debug(
            f"メンション検出: ユーザーID {user_id}, チャンネルID {message.channel.id}, メッセージ: {preview}"
        )
        return True, question, True

    # 設定された名前で呼ばれた場合
    if config.BOT_NAME in content:
        question = content  # メッセージ全体を質問として扱う
        preview = truncate_text(question)
        logger.debug(
            f"名前で呼ばれました: ユーザーID {user_id}, チャンネルID {message.channel.id}, メッセージ: {preview}"
        )
        return True, question, False

    # ボットの発言へのリプライの場合
    if message.reference and message.reference.resolved:
        # リプライ先のメッセージがボット自身のものか確認
        if (
            hasattr(message.reference.resolved, "author")
            and message.reference.resolved.author is not None
            and bot.user is not None
            and message.reference.resolved.author.id == bot.user.id
        ):
            question = content  # リプライのメッセージ内容をそのまま質問として扱う
            preview = truncate_text(question)
            logger.debug(
                f"リプライ検出: ユーザーID {user_id}, チャンネルID {message.channel.id}, メッセージ: {preview}"
            )
            return True, question, True

    return False, "", False


async def _collect_ai_context(
    message: discord.Message,
) -> tuple[str, str, list[str], str, str]:
    """AIへの入力コンテキスト情報を収集する

    Args:
        message: Discordメッセージオブジェクト

    Returns:
        tuple: (channel_context, channel_summary, topic_keywords, user_profile_str, relevant_facts_str)
    """
    from memory.short_term import get_channel_buffer

    channel_summary = ""
    topic_keywords: list[str] = []
    user_profile_str = ""
    relevant_facts_str = ""

    buffer = get_channel_buffer()
    channel_context = buffer.get_context_string(message.channel.id, limit=10)

    if config.LIVING_MEMORY_ENABLED:
        from memory.channel_context import get_channel_context_store

        ctx = get_channel_context_store().get_context(message.channel.id)
        channel_summary = ctx.format_for_injection()
        topic_keywords = ctx.topic_keywords

        user_profile_str = await _collect_user_profile_context(message)
        relevant_facts_str = await _collect_relevant_facts(message)

    return channel_context, channel_summary, topic_keywords, user_profile_str, relevant_facts_str


async def _collect_user_profile_context(message: discord.Message) -> str:
    """発言者のユーザープロファイルをプロンプト注入用の文字列に整形する

    Args:
        message: Discordメッセージオブジェクト

    Returns:
        str: 親密度・コンテキスト・ペルソナ情報を空行区切りで連結した文字列
    """
    from memory.user_profile import get_user_profile_store

    guild_id = message.guild.id if message.guild else 0
    profile = await asyncio.to_thread(
        get_user_profile_store().get_profile,
        guild_id,
        message.author.id,
        message.author.display_name,
    )
    return "\n\n".join(filter(None, [
        profile.format_for_familiarity(),
        profile.format_for_context(),
        profile.format_for_persona(),
    ]))


async def _collect_relevant_facts(message: discord.Message) -> str:
    """メッセージに関連するファクトを検索し、箇条書き文字列にする

    Args:
        message: Discordメッセージオブジェクト

    Returns:
        str: 関連ファクトの箇条書き（ヒットなしの場合は空文字列）
    """
    from ai.client import generate_embedding
    from memory.fact_store import extract_keywords, get_fact_store

    keywords = extract_keywords(message.content or "")
    query_embedding = None
    if config.VECTOR_SEARCH_ENABLED and message.content:
        query_embedding = await asyncio.to_thread(generate_embedding, message.content)
    # 初回は永続化先からの読み込みが発生し、類似度計算も重いためスレッドで実行する
    facts = await asyncio.to_thread(
        get_fact_store().search,
        channel_id=message.channel.id,
        keywords=keywords,
        user_ids=[message.author.id],
        limit=3,
        query_embedding=query_embedding,
    )
    logger.debug(
        f"関連ファクト検索: channel_id={message.channel.id}, "
        f"keywords={keywords}, vector={'あり' if query_embedding else 'なし'}, hits={len(facts)}"
    )
    if not facts:
        return ""
    # 見出しは build_context_section 側で付与する
    return "\n".join(f"- {f.content}" for f in facts)


def _get_or_reset_conversation(channel_id: str) -> "Sphene":
    """チャンネルの会話インスタンスを取得し、期限切れなら新規作成する

    Args:
        channel_id: チャンネルID（文字列）

    Returns:
        Sphene: 会話インスタンス
    """
    if channel_conversations[channel_id].is_expired():
        logger.info(f"チャンネルID {channel_id} の会話が期限切れのためリセット")
        channel_conversations[channel_id] = Sphene(system_setting=load_system_prompt())
    return channel_conversations[channel_id]


@contextlib.asynccontextmanager
async def _typing_indicator(channel: discord.abc.Messageable) -> AsyncIterator[None]:
    """応答生成中に「入力中...」インジケーターを表示する。

    discord.py の typing() は約10秒ごとに自動で再送されるため、長時間の生成中も表示が続く。
    インジケーターの表示に失敗しても応答処理は継続する。

    Args:
        channel: インジケーターを表示するチャンネル
    """
    typing_cm = channel.typing()
    try:
        await typing_cm.__aenter__()
    except Exception as e:
        logger.warning(f"入力中インジケーターの表示に失敗: {e}", exc_info=True)
        yield
        return
    try:
        yield
    finally:
        await typing_cm.__aexit__(None, None, None)


def _reply_reference(message: discord.Message) -> discord.MessageReference:
    """返信用の MessageReference を生成する

    応答生成中に元メッセージが削除されても送信が失敗しないよう、
    ``fail_if_not_exists=False`` を指定する（その場合は通常投稿になる）。

    Args:
        message: 返信先のDiscordメッセージ

    Returns:
        discord.MessageReference: 返信先の参照
    """
    return message.to_reference(fail_if_not_exists=False)


async def _send_chunks(
    message: discord.Message,
    chunks: list[str],
    is_reply: bool = False,
) -> None:
    """チャンク分割されたメッセージを送信する

    Args:
        message: 元のDiscordメッセージ
        chunks: 送信するテキストチャンクのリスト
        is_reply: True の場合、最初のチャンクをリプライとして送信する
    """
    channel_id = str(message.channel.id)
    for i, chunk in enumerate(chunks):
        if is_reply and i == 0:
            logger.info(
                f"リプライとして応答送信(chunk {i+1}/{len(chunks)}): チャンネルID {channel_id}, 応答: {truncate_text(chunk)}"
            )
            await message.channel.send(chunk, reference=_reply_reference(message))
        else:
            label = "リプライ" if is_reply else "通常"
            logger.info(
                f"{label}応答送信(chunk {i+1}/{len(chunks)}): チャンネルID {channel_id}, 応答: {truncate_text(chunk)}"
            )
            await message.channel.send(chunk)


def _post_response_update(
    message: discord.Message,
    answer: str,
    topic_keywords: list[str],
    bot_user: discord.Member | discord.ClientUser | None,
) -> None:
    """応答送信後のプロファイル更新とバッファへの追加を行う

    Args:
        message: 元のDiscordメッセージ
        answer: 送信した応答テキスト
        topic_keywords: 話題キーワードリスト
        bot_user: ボットのユーザー/メンバーオブジェクト（None の場合バッファ追加をスキップ）
    """
    from memory.short_term import ChannelMessage, get_channel_buffer

    if config.LIVING_MEMORY_ENABLED and topic_keywords:
        from memory.user_profile import get_user_profile_store

        guild_id = message.guild.id if message.guild else 0
        get_user_profile_store().update_last_topic(
            guild_id, message.author.id, topic_keywords
        )

    if bot_user is not None:
        get_channel_buffer().add_message(
            ChannelMessage(
                message_id=0,
                channel_id=message.channel.id,
                guild_id=message.guild.id if message.guild else None,
                author_id=bot_user.id,
                author_name=bot_user.display_name,
                content=answer,
                timestamp=datetime.now(timezone.utc),
                is_bot=True,
            )
        )


async def process_conversation(
    message: discord.Message,
    question: str,
    is_reply: bool = False,
    images: list[str] | None = None,
) -> None:
    """ユーザーとの会話を処理する

    Args:
        message: Discordメッセージオブジェクト
        question: 質問内容
        is_reply: リプライによるメッセージかどうか
        images: 添付された画像のURLリスト
    """
    channel_id = str(message.channel.id)
    author_name = message.author.display_name

    channel_context, channel_summary, topic_keywords, user_profile_str, relevant_facts_str = (
        await _collect_ai_context(message)
    )
    api = _get_or_reset_conversation(channel_id)

    # 会話履歴とコンテキストを使用して応答生成（Lock で直列化）
    async with _typing_indicator(message.channel):
        answer = await api.async_input_message(
            input_text=question,
            author_name=author_name,
            image_urls=images,
            channel_context=channel_context,
            channel_summary=channel_summary,
            user_profile=user_profile_str,
            relevant_facts=relevant_facts_str,
        )

    chunks = split_message(answer) if answer else []
    if answer and chunks:
        await _send_chunks(message, chunks, is_reply=is_reply)
        bot_user = message.guild.me if message.guild else None
        _post_response_update(message, answer, topic_keywords, bot_user)
    else:
        error_msg = "ごめん！応答の生成中にエラーが発生しちゃった...😢 もう一度試してみてね！"
        if is_reply:
            await message.channel.send(error_msg, reference=_reply_reference(message))
        else:
            await message.channel.send(error_msg)


async def _try_autonomous_response(
    bot: commands.Bot,
    message: discord.Message,
    images: list[str],
) -> None:
    """自律応答の判定と実行

    RuleBasedJudgeでスコアリングし、必要に応じてLLM Judgeで二次判定を行う。

    Args:
        bot: Discordクライアント
        message: Discordメッセージオブジェクト
        images: 添付画像URLリスト
    """
    from memory.judge import get_judge
    from memory.short_term import get_channel_buffer

    buffer = get_channel_buffer()
    judge = get_judge()

    recent_messages = buffer.get_recent_messages(message.channel.id, limit=20)

    # ルールベース判定
    result = judge.evaluate(
        message=_to_channel_message(message),
        recent_messages=recent_messages,
    )

    # リアクション先行実行（返信とは独立。LLM生成を待たない）
    if result.should_react:
        _schedule_reaction(message, result.reaction_emojis)

    if result.score >= config.JUDGE_LLM_THRESHOLD_HIGH:
        # 高スコア: 即応答（react_only でリアクション済みなら _dispatch_response が重複を防ぐ）
        await _dispatch_rule_based_response(bot, message, images, result, "高スコア")
        return

    if result.score <= config.JUDGE_LLM_THRESHOLD_LOW:
        # 低スコア: リアクション済みの場合あり、返信はスキップ
        return

    # 中間スコア: LLM Judgeで二次判定
    if config.VANGUARD_ENABLED:
        context = buffer.get_context_string(message.channel.id, limit=15)
        await _respond_by_llm_judge(bot, message, images, result, context)
    elif result.should_respond:
        # LLM Judge無効の場合はルールベースの判定に従う
        await _dispatch_rule_based_response(bot, message, images, result, "ルールベース")


async def _dispatch_rule_based_response(
    bot: commands.Bot,
    message: discord.Message,
    images: list[str],
    result: "JudgeResult",
    label: str,
) -> None:
    """ルールベース判定の結果に従って自律応答を実行する

    Args:
        bot: Discordクライアント
        message: Discordメッセージオブジェクト
        images: 添付画像URLリスト
        result: ルールベース判定の結果
        label: ログに出す判定経路（"高スコア" / "ルールベース"）
    """
    logger.info(
        f"自律応答決定({label}): チャンネル={message.channel.id}, "
        f"スコア={result.score}, 理由={result.reason}"
    )
    await _dispatch_response(
        bot, message, images, result.response_type,
        already_reacted=result.should_react,
    )


def _to_channel_message(message: discord.Message) -> "ChannelMessage":
    """DiscordメッセージをJudge入力用のChannelMessageに変換する

    Args:
        message: Discordメッセージオブジェクト

    Returns:
        ChannelMessage: 判定用のメッセージ
    """
    from memory.short_term import ChannelMessage

    return ChannelMessage(
        message_id=message.id,
        channel_id=message.channel.id,
        guild_id=message.guild.id if message.guild else None,
        author_id=message.author.id,
        author_name=message.author.display_name,
        content=message.content or "",
        timestamp=message.created_at,
    )


def _schedule_reaction(message: discord.Message, emojis: list[str]) -> None:
    """自律リアクションをバックグラウンドタスクとして送信する（応答生成を待たない）

    Args:
        message: リアクション対象のメッセージ
        emojis: 付与する絵文字リスト
    """
    track_background_task(asyncio.create_task(
        _send_reaction(message, emojis, record=False),
        name="reaction_task",
    ))


async def _respond_by_llm_judge(
    bot: commands.Bot,
    message: discord.Message,
    images: list[str],
    result: "JudgeResult",
    context: str,
) -> None:
    """中間スコアのメッセージをLLM Judgeで二次判定し、必要なら応答する

    Args:
        bot: Discordクライアント
        message: Discordメッセージオブジェクト
        images: 添付画像URLリスト
        result: ルールベース判定の結果
        context: LLM Judgeに渡す直近のチャンネル文脈
    """
    from memory.llm_judge import get_llm_judge

    llm_judge = get_llm_judge()
    should_respond, llm_response_type, llm_should_react, llm_emojis = (
        await llm_judge.evaluate(
            message_content=message.content or "",
            recent_context=context,
            bot_name=config.BOT_NAME,
        )
    )
    # LLMがリアクションを追加すべきと判定し、ルールベースでは未実行の場合
    if llm_should_react and not result.should_react:
        _schedule_reaction(message, llm_emojis)
    if should_respond and llm_response_type != "none":
        logger.info(
            f"自律応答決定(LLM Judge): チャンネル={message.channel.id}, "
            f"スコア={result.score}, タイプ={llm_response_type}"
        )
        already_reacted = result.should_react or llm_should_react
        await _dispatch_response(
            bot, message, images, llm_response_type,
            already_reacted=already_reacted,
        )


async def _dispatch_response(
    bot: commands.Bot,
    message: discord.Message,
    images: list[str],
    response_type: str,
    already_reacted: bool = False,
) -> None:
    """応答タイプに応じて適切な応答を実行する

    Args:
        bot: Discordクライアント
        message: トリガーとなったDiscordメッセージ
        images: 添付画像URLリスト
        response_type: "full_response" | "short_ack" | "react_only"
        already_reacted: True の場合、リアクション済みとしてフォールバック処理を抑制する
    """
    if response_type == "react_only":
        if already_reacted:
            # 先行リアクション済み。重ねて付けず、応答としてクールダウンだけ記録する
            from memory.judge import get_judge

            get_judge().record_response(message.channel.id)
        else:
            await _send_reaction(message)
    elif response_type == "short_ack":
        await _process_short_ack(bot, message, already_reacted=already_reacted)
    else:
        await _process_autonomous_response(bot, message, images)


async def _send_reaction(
    message: discord.Message,
    emojis: list[str] | None = None,
    record: bool = True,
) -> None:
    """絵文字リアクションを追加する

    Args:
        message: リアクションを追加するDiscordメッセージ
        emojis: 使用する絵文字リスト。Noneまたは空の場合はランダム選択（最大2個まで使用）
        record: Trueの場合、クールダウンを記録する
    """
    from memory.judge import get_judge

    try:
        selected = emojis[:2] if emojis else [random.choice(_REACTION_EMOJIS)]
        for emoji in selected:
            await message.add_reaction(emoji)
        logger.info(
            f"リアクション応答: チャンネル={message.channel.id}, 絵文字={selected}"
        )
        if record:
            get_judge().record_response(message.channel.id)
    except Exception as e:
        logger.error(f"リアクション追加エラー: {e}", exc_info=True)


async def _process_short_ack(
    bot: commands.Bot,
    message: discord.Message,
    already_reacted: bool = False,
) -> None:
    """短い相槌を生成して送信する

    Args:
        bot: Discordクライアント
        message: トリガーとなったDiscordメッセージ
        already_reacted: True の場合、相槌生成失敗時のリアクションフォールバックをスキップする
    """
    from memory.judge import get_judge
    from memory.short_term import ChannelMessage, get_channel_buffer

    buffer = get_channel_buffer()
    context = buffer.get_context_string(message.channel.id, limit=10)
    if not context:
        logger.debug("相槌: コンテキストが空のためスキップ (channel=%s)", message.channel.id)
        return

    async with _typing_indicator(message.channel):
        answer = await asyncio.to_thread(
            generate_short_ack,
            channel_context=context,
            trigger_message=message.content or "",
        )

    if not answer or not answer.strip():
        await _handle_short_ack_failure(message, already_reacted)
        return

    try:
        await message.channel.send(answer)
        logger.info(
            f"相槌応答: チャンネル={message.channel.id}, "
            f"応答={truncate_text(answer)}"
        )
        get_judge().record_response(message.channel.id)

        # ボット自身の応答もバッファに追加
        if bot.user:
            buffer.add_message(
                ChannelMessage(
                    message_id=0,
                    channel_id=message.channel.id,
                    guild_id=message.guild.id if message.guild else None,
                    author_id=bot.user.id,
                    author_name=bot.user.display_name,
                    content=answer,
                    timestamp=datetime.now(timezone.utc),
                    is_bot=True,
                )
            )
    except Exception as e:
        logger.error("相槌送信エラー: %s", e, exc_info=True)


async def _handle_short_ack_failure(
    message: discord.Message, already_reacted: bool
) -> None:
    """相槌生成に失敗したときのフォールバック処理

    リアクション済みならクールダウンのみ記録し、未リアクションならリアクションを送る。

    Args:
        message: トリガーとなったDiscordメッセージ
        already_reacted: 既にリアクション済みかどうか
    """
    from memory.judge import get_judge

    if already_reacted:
        # リアクション済みの場合はフォールバックリアクションを省略し、クールダウンのみ記録
        logger.debug(
            "相槌生成に失敗（リアクション済みのためフォールバックをスキップ）(channel=%s)",
            message.channel.id,
        )
        get_judge().record_response(message.channel.id)
    else:
        logger.warning(
            "相槌生成に失敗、リアクションにフォールバック (channel=%s)", message.channel.id
        )
        await _send_reaction(message)


async def _process_autonomous_response(
    bot: commands.Bot,
    message: discord.Message,
    images: list[str],
) -> None:
    """自律応答を生成して送信する

    Args:
        bot: Discordクライアント
        message: トリガーとなったDiscordメッセージ
        images: 添付画像URLリスト
    """
    from memory.judge import get_judge

    channel_id_str = str(message.channel.id)

    channel_context, channel_summary, topic_keywords, user_profile_str, relevant_facts_str = (
        await _collect_ai_context(message)
    )

    if not channel_context:
        logger.debug("コンテキストが空のため自律応答をスキップ")
        return

    api = _get_or_reset_conversation(channel_id_str)

    # 会話履歴を使用した応答生成（Lock で直列化）
    async with _typing_indicator(message.channel):
        answer = await api.async_input_message(
            input_text=message.content or "",
            author_name=message.author.display_name,
            image_urls=images,
            channel_context=channel_context,
            channel_summary=channel_summary,
            user_profile=user_profile_str,
            relevant_facts=relevant_facts_str,
        )

    chunks = split_message(answer) if answer else []
    if answer and chunks:
        await _send_chunks(message, chunks, is_reply=False)
        logger.info(
            f"自律応答送信: チャンネル={message.channel.id}, "
            f"応答={truncate_text(answer)}"
        )
        get_judge().record_response(message.channel.id)
        _post_response_update(message, answer, topic_keywords, bot.user)
    else:
        logger.debug("自律応答の生成に失敗、またはNoneが返りました")


# チャンネル設定マネージャーのシングルトンインスタンスを取得
config_manager = ChannelConfigManager.get_instance()


def _prefetch_memory(message: discord.Message) -> None:
    """記憶ストアのキャッシュを温める（ワーカースレッドで実行する）

    チャンネルコンテキスト・ユーザープロファイル・ファクトは初回アクセス時に
    永続化先（Firestore等）から同期的に読み込まれる。イベントループを止めないよう、
    以降の同期呼び出しがキャッシュに当たる状態をここで作っておく。

    Args:
        message: Discordメッセージオブジェクト
    """
    from memory.channel_context import get_channel_context_store
    from memory.fact_store import get_fact_store
    from memory.user_profile import get_user_profile_store

    guild_id = message.guild.id if message.guild else 0
    get_channel_context_store().get_context(message.channel.id)
    get_user_profile_store().get_profile(
        guild_id, message.author.id, message.author.display_name
    )
    get_fact_store().ensure_loaded(message.channel.id)


async def _handle_message(bot: commands.Bot, message: discord.Message) -> None:
    """メッセージ受信イベントの処理

    Args:
        bot: Discordクライアント
        message: Discordメッセージオブジェクト
    """
    # ボットが話しかけられた場合のみ、失敗をチャンネルに通知する
    addressed = False
    try:
        # 自分自身やボットのメッセージ・空メッセージは無視
        if _is_ignorable_message(bot, message):
            return

        # ギルドIDを取得
        if message.guild is None:
            # DMなどギルドがない場合は処理しない
            logger.info("ギルドなしのメッセージは処理しません")
            return

        guild_id = message.guild.id
        if not await _can_speak_in_channel(message, guild_id):
            return  # 処理を中断

        await _record_memory(message, guild_id)

        images = _extract_image_urls(message)

        # ボットが呼ばれたかどうかをチェック
        is_mentioned, question, is_reply = await is_bot_mentioned(bot, message)
        if is_mentioned:
            if not await _acquire_mention_quota(message, guild_id):
                return
            addressed = True
            await _respond_to_mention(message, guild_id, question, is_reply, images)
            return

        # 自律応答: メンションされていない場合の判定
        if config.VANGUARD_ENABLED:
            await _try_autonomous_response(bot, message, images)

    except Exception as e:
        logger.error(f"メッセージ処理中にエラー発生: {str(e)}", exc_info=True)
        if addressed:
            await _notify_processing_error(message)


def _is_ignorable_message(bot: commands.Bot, message: discord.Message) -> bool:
    """処理対象外のメッセージ（自分・他ボットの発言、内容も添付もない）かを判定する

    Args:
        bot: Discordクライアント
        message: Discordメッセージオブジェクト

    Returns:
        bool: 処理対象外ならTrue
    """
    if message.author == bot.user or message.author.bot:
        return True
    return message.content is None and len(message.attachments) == 0


async def _can_speak_in_channel(message: discord.Message, guild_id: int) -> bool:
    """チャンネル設定に基づいてボットが発言可能かを判定する

    Args:
        message: Discordメッセージオブジェクト
        guild_id: ギルドID

    Returns:
        bool: 発言可能ならTrue
    """
    # ギルド固有の設定を取得（初回は永続化先から読み込むためスレッドで実行）
    channel_config = await asyncio.to_thread(config_manager.get_config, guild_id)

    channel_id = message.channel.id
    can_speak = channel_config.can_bot_speak(channel_id)

    # デバッグ用の詳細なログ出力
    logger.debug(
        f"チャンネル評価: ギルドID={guild_id}, チャンネルID={channel_id}, "
        f"発言可能={can_speak}, モード={channel_config.get_mode_display_name()}"
    )

    if not can_speak:
        logger.info(
            f"チャンネルでの発言をスキップ: ギルドID={guild_id}, モード={channel_config.get_mode_display_name()}, "
            f"ユーザーID={message.author.id}, チャンネルID={message.channel.id}"
        )
    return can_speak


def _extract_image_urls(message: discord.Message) -> list[str]:
    """メッセージの添付ファイルから画像のURLを抽出する

    Args:
        message: Discordメッセージオブジェクト

    Returns:
        list[str]: 画像添付のURLリスト
    """
    images = []
    for attachment in message.attachments:
        if attachment.content_type and attachment.content_type.startswith("image/"):
            logger.debug(
                f"画像検出: {attachment.url}, タイプ: {attachment.content_type}"
            )
            images.append(attachment.url)
    return images


async def _respond_to_mention(
    message: discord.Message,
    guild_id: int,
    question: str,
    is_reply: bool,
    images: list[str],
) -> None:
    """メンション（呼びかけ）に応答し、プロファイル・エンゲージメントを記録する

    Args:
        message: Discordメッセージオブジェクト
        guild_id: ギルドID
        question: メンションを除いた質問文
        is_reply: ボットへのリプライかどうか
        images: 添付画像URLリスト
    """
    # ユーザープロファイル: ボットメンション記録
    if config.LIVING_MEMORY_ENABLED:
        from memory.user_profile import get_user_profile_store

        get_user_profile_store().record_bot_mention(guild_id, message.author.id)

    await process_conversation(message, question, is_reply, images)
    # エンゲージメント記録（自律応答のスコアブーストに使用）
    if config.VANGUARD_ENABLED:
        from memory.judge import get_judge

        get_judge().record_response(message.channel.id)


async def _acquire_mention_quota(message: discord.Message, guild_id: int) -> bool:
    """メンション等による会話のレート制限枠を確保する

    ユーザー単位・チャンネル単位の両方に空きがある場合のみ枠を消費する。
    超過時は応答せず、⏳ リアクションで混雑を伝える。

    Args:
        message: Discordメッセージ
        guild_id: ギルドID

    Returns:
        会話処理を続けてよい場合True
    """
    user_key = (guild_id, message.author.id)
    channel_key = message.channel.id
    if _user_mention_limiter.is_allowed(user_key) and _channel_mention_limiter.is_allowed(
        channel_key
    ):
        _user_mention_limiter.record(user_key)
        _channel_mention_limiter.record(channel_key)
        return True

    logger.warning(
        f"メンションのレート制限超過のため応答をスキップ: ギルドID={guild_id}, "
        f"チャンネルID={channel_key}, ユーザーID={message.author.id}"
    )
    if _claim_rate_limited_reaction(message.id):
        try:
            await message.add_reaction(_RATE_LIMITED_EMOJI)
        except discord.HTTPException:
            logger.warning("レート制限リアクションの追加に失敗しました", exc_info=True)
    return False


def _claim_rate_limited_reaction(message_id: int) -> bool:
    """メッセージに ⏳ リアクションを送ってよいかを判定し、送る場合は記録する

    同じメッセージへの送信はウィンドウ内で1回にまとめる（2回目以降は API を呼ばない）。

    Args:
        message_id: ⏳ を付けるメッセージのID

    Returns:
        まだ送っていない場合True
    """
    if not _rate_limited_reaction_limiter.is_allowed(message_id):
        logger.debug(f"⏳ リアクション送信済みのためスキップ: メッセージID={message_id}")
        return False
    _rate_limited_reaction_limiter.record(message_id)
    return True


async def _notify_processing_error(message: discord.Message) -> None:
    """メッセージ処理の失敗をチャンネルに通知する（送信失敗はログのみ）

    Args:
        message: 処理に失敗したDiscordメッセージ
    """
    try:
        await message.channel.send("ごめん！メッセージ処理中にエラーが発生しちゃった...😢")
    except discord.HTTPException:
        logger.warning("エラー通知の送信に失敗しました", exc_info=True)


async def _record_memory(message: discord.Message, guild_id: int) -> None:
    """メッセージを短期記憶・記憶ストアに記録する

    記憶の記録は応答の前提ではないため、失敗してもログだけ残して応答処理は続ける。

    Args:
        message: Discordメッセージオブジェクト
        guild_id: ギルドID
    """
    try:
        from memory.short_term import ChannelMessage, get_channel_buffer

        buffer = get_channel_buffer()
        buffer.add_message(
            ChannelMessage(
                message_id=message.id,
                channel_id=message.channel.id,
                guild_id=guild_id,
                author_id=message.author.id,
                author_name=message.author.display_name,
                content=message.content or "",
                timestamp=message.created_at,
            )
        )
        if config.LIVING_MEMORY_ENABLED:
            # 記憶ストアの初回読み込み（Firestore等の同期I/O）をイベントループ外で済ませる
            await asyncio.to_thread(_prefetch_memory, message)
            _record_living_memory(message, guild_id, buffer)
    except Exception:
        logger.error("記憶の記録中にエラーが発生しました", exc_info=True)


def _record_living_memory(
    message: discord.Message, guild_id: int, buffer: "ChannelMessageBuffer"
) -> None:
    """チャンネルコンテキスト・ユーザープロファイルを更新し、要約・反省会をトリガーする

    Args:
        message: Discordメッセージオブジェクト
        guild_id: ギルドID
        buffer: チャンネルバッファ
    """
    from memory.channel_context import get_channel_context_store
    from memory.reflection import get_reflection_engine
    from memory.summarizer import get_summarizer
    from memory.user_profile import get_user_profile_store

    channel_id = message.channel.id
    get_channel_context_store().get_context(channel_id).increment_message_count()
    get_summarizer().maybe_summarize(
        channel_id, buffer.get_recent_messages(channel_id, limit=20)
    )
    get_user_profile_store().record_message(
        guild_id, message.author.id, channel_id, message.author.display_name
    )
    if (
        buffer.count_messages_since_reflection(channel_id)
        >= config.REFLECTION_MAX_BUFFER_MESSAGES
    ):
        get_reflection_engine().maybe_reflect(
            channel_id, buffer.get_messages_since_reflection(channel_id)
        )


async def _handle_setup_hook(
    bot: commands.Bot, command_group: app_commands.Group
) -> None:
    """ログイン直後に1度だけ呼ばれる初期化処理

    on_ready は再接続のたびに発火するため、コマンド登録と同期はここで1回だけ行う。

    Args:
        bot: Discordクライアント
        command_group: コマンドグループ
    """
    bot.tree.add_command(command_group)
    await bot.tree.sync()
    logger.info("スラッシュコマンドを登録・同期しました")


async def _handle_on_ready(
    bot: commands.Bot, command_group: app_commands.Group
) -> None:
    """ボットの準備完了時の処理（再接続のたびに呼ばれる）

    Args:
        bot: Discordクライアント
        command_group: コマンドグループ
    """
    if bot.user:
        logger.info(f"Discordボット起動完了: {bot.user.name}#{bot.user.discriminator}")
    else:
        logger.error("Discordボットのユーザー情報を取得できませんでした")

    # 各ギルドのチャンネル設定を初期化
    logger.info("ギルドごとのチャンネル設定を初期化")
    for guild in bot.guilds:
        logger.info(f"ギルド {guild.name} (ID: {guild.id}) の設定をチェック")
        try:
            await asyncio.to_thread(config_manager.get_config, guild.id)
        except Exception as e:
            logger.error(
                f"ギルドID {guild.id} の設定初期化中にエラー: {str(e)}", exc_info=True
            )


async def _handle_on_guild_join(guild: discord.Guild) -> None:
    """ギルド参加時の処理

    Args:
        guild: 参加したDiscordギルド
    """
    logger.info(f"新しいギルド {guild.name} (ID: {guild.id}) に参加しました")
    try:
        await asyncio.to_thread(config_manager.create_guild_config, guild.id)
        logger.info(f"ギルドID {guild.id} の設定ファイルを作成しました")
    except Exception as e:
        logger.error(
            f"ギルドID {guild.id} の設定ファイル作成中にエラー: {str(e)}", exc_info=True
        )


async def _handle_on_guild_remove(guild: discord.Guild) -> None:
    """ギルド脱退時の処理

    Args:
        guild: 脱退したDiscordギルド
    """
    logger.info(f"ギルド {guild.name} (ID: {guild.id}) から脱退しました")
    try:
        success = await asyncio.to_thread(config_manager.delete_guild_config, guild.id)
        if success:
            logger.info(f"ギルドID {guild.id} の設定ファイルを削除しました")
        else:
            logger.warning(f"ギルドID {guild.id} の設定ファイル削除に失敗しました")
    except Exception as e:
        logger.error(
            f"ギルドID {guild.id} の設定ファイル削除中にエラー: {str(e)}", exc_info=True
        )


def get_message_type(message: discord.Message) -> str:
    """メッセージの種類（通常/リプライ/スレッド）を判定する

    Args:
        message: Discordメッセージオブジェクト

    Returns:
        str: メッセージタイプ（"normal", "reply", "thread"）
    """
    if message.reference:  # リプライメッセージ
        return "reply"
    elif isinstance(message.channel, discord.Thread):  # スレッド内メッセージ
        return "thread"
    else:
        return "normal"


async def send_translation_response(
    message: discord.Message, translated_text: str, language_flag: str
) -> None:
    """メッセージタイプに応じた適切な方法で翻訳結果を送信する

    スレッド内メッセージの場合は message.channel が Thread オブジェクトそのものなので、
    常に message.channel.send() で正しい送信先に届く。

    Args:
        message: 元のDiscordメッセージ
        translated_text: 翻訳されたテキスト、またはエラーメッセージ
        language_flag: 言語を示す絵文字 (🇺🇸 または 🇯🇵)
    """
    full_text = f"{language_flag} {translated_text}"
    chunks = split_message(full_text)

    for i, chunk in enumerate(chunks):
        if i == 0:
            await message.channel.send(chunk, reference=_reply_reference(message))
        else:
            await message.channel.send(chunk)


def _claim_translation(key: tuple[int, str]) -> bool:
    """(メッセージID, 言語) の翻訳権を取得する

    TRANSLATION_DEDUP_SECONDS 以内に翻訳済み・翻訳中のキーは取得できない。
    イベントループ上でのみ呼ぶため、判定と記録の間に他の処理は割り込まない。

    Returns:
        翻訳を実行してよい場合True
    """
    now = time.monotonic()
    expired = [
        k for k, t in _translated_messages.items() if now - t >= config.TRANSLATION_DEDUP_SECONDS
    ]
    for k in expired:
        del _translated_messages[k]
    if key in _translated_messages:
        return False
    _translated_messages[key] = now
    return True


async def translate_and_reply(
    message: discord.Message, target_language: str = "english"
) -> None:
    """メッセージを指定した言語に翻訳してリプライする

    Args:
        message: 翻訳対象のDiscordメッセージ
        target_language: 翻訳先言語 ("english" または "japanese")
    """
    # メッセージ内容がなければ処理しない
    if not message.content:
        logger.debug("翻訳対象メッセージの内容が空のため処理をスキップ")
        return

    # デバッグ用のログ追加：翻訳対象メッセージの詳細情報
    logger.debug(
        f"翻訳対象メッセージ詳細: ID={message.id}, 作成日時={message.created_at}, "
        f"チャネルID={message.channel.id}, 著者ID={message.author.id}"
    )

    content = message.content
    user_id = str(message.author.id)
    message_type = get_message_type(message)

    logger.info(
        f"{target_language}翻訳リクエスト: タイプ={message_type}, ユーザーID={user_id}, "
        f"メッセージ: {truncate_text(content)}"
    )

    dedup_key = (message.id, target_language)
    if not _claim_translation(dedup_key):
        logger.info(
            f"翻訳済み・翻訳中のためスキップ: メッセージID={message.id}, 言語={target_language}"
        )
        return

    translate_func, language_flag = _select_translator(target_language)
    translated_text = await _run_translation(message, content, translate_func, dedup_key)

    if translated_text:
        # 適切な方法で翻訳結果を送信
        await send_translation_response(message, translated_text, language_flag)
        logger.info(f"翻訳結果を送信: {truncate_text(translated_text)}")
    else:
        # エラー時も同様に対応
        error_message = "翻訳中にエラーが発生しました 😢"
        await send_translation_response(message, error_message, language_flag)
        logger.warning(
            f"翻訳エラー: タイプ={message_type}, ユーザーID={user_id}, メッセージ: {truncate_text(content)}"
        )


def _select_translator(
    target_language: str,
) -> tuple[Callable[[str], Awaitable[str | None]], str]:
    """翻訳先言語に応じた翻訳関数と国旗絵文字を選ぶ

    Args:
        target_language: 翻訳先言語 ("japanese" 以外は英語として扱う)

    Returns:
        tuple: (翻訳関数, 国旗絵文字)
    """
    from utils.text_utils import translate_to_english, translate_to_japanese

    if target_language == "japanese":
        return translate_to_japanese, "🇯🇵"
    # デフォルトは英語
    return translate_to_english, "🇺🇸"


async def _run_translation(
    message: discord.Message,
    content: str,
    translate_func: Callable[[str], Awaitable[str | None]],
    dedup_key: tuple[int, str],
) -> str | None:
    """入力中インジケーターを表示しながら翻訳を実行する

    失敗・中断時は再リアクションで再試行できるよう重複抑止の記録を外す。

    Args:
        message: 翻訳対象のDiscordメッセージ（入力中インジケーターの表示先）
        content: 翻訳するテキスト
        translate_func: 翻訳関数
        dedup_key: 重複抑止キー (メッセージID, 翻訳先言語)

    Returns:
        str | None: 翻訳結果（失敗時はNoneまたは空文字列）
    """
    try:
        async with _typing_indicator(message.channel):
            translated_text = await translate_func(content)
    except BaseException:
        _translated_messages.pop(dedup_key, None)
        raise
    if not translated_text:
        # 失敗時は再リアクションで再試行できるよう記録を外す
        _translated_messages.pop(dedup_key, None)
    return translated_text


# 国旗リアクション絵文字 → 翻訳先言語
_TRANSLATION_FLAGS: dict[str, str] = {
    "🇺🇸": "english",
    "flag_us": "english",
    "🇯🇵": "japanese",
    "flag_jp": "japanese",
}


def _is_translation_claimed(key: tuple[int, str]) -> bool:
    """(メッセージID, 言語) が重複抑止期間内に翻訳済み・翻訳中かを判定する（記録はしない）

    Args:
        key: (メッセージID, 翻訳先言語)

    Returns:
        翻訳済み・翻訳中の場合True
    """
    claimed_at = _translated_messages.get(key)
    if claimed_at is None:
        return False
    return time.monotonic() - claimed_at < config.TRANSLATION_DEDUP_SECONDS


def _acquire_translation_quota(guild_id: int, user_id: int, channel_id: int) -> bool:
    """翻訳のレート制限枠を確保する

    ユーザー単位（ギルドごと）・チャンネル単位の両方に空きがある場合のみ枠を消費する。

    Args:
        guild_id: ギルドID
        user_id: リアクションを付けたユーザーのID
        channel_id: チャンネルID

    Returns:
        翻訳を続けてよい場合True
    """
    user_key = (guild_id, user_id)
    if not (
        _user_translation_limiter.is_allowed(user_key)
        and _channel_translation_limiter.is_allowed(channel_id)
    ):
        logger.warning(
            f"翻訳のレート制限超過のためスキップ: ギルドID={guild_id}, "
            f"チャンネルID={channel_id}, ユーザーID={user_id}"
        )
        return False
    _user_translation_limiter.record(user_key)
    _channel_translation_limiter.record(channel_id)
    return True


def _resolve_channel(
    bot: commands.Bot, payload: discord.RawReactionActionEvent
) -> discord.abc.Messageable:
    """リアクションが付いたチャンネルを返す（キャッシュに無ければ PartialMessageable）

    Args:
        bot: Discordクライアント
        payload: リアクション追加イベント

    Returns:
        送信・メッセージ取得に使えるチャンネル
    """
    channel = bot.get_channel(payload.channel_id)
    if isinstance(channel, discord.abc.Messageable):
        return channel
    return bot.get_partial_messageable(payload.channel_id, guild_id=payload.guild_id)


async def _fetch_reacted_message(
    bot: commands.Bot, payload: discord.RawReactionActionEvent
) -> discord.Message | None:
    """リアクションが付いたメッセージを取得する

    メッセージキャッシュにあればそれを使い、無ければ API から取得する。

    Args:
        bot: Discordクライアント
        payload: リアクション追加イベント

    Returns:
        取得できたメッセージ。削除済み・権限不足などで取得できない場合None
    """
    cached = discord.utils.get(bot.cached_messages, id=payload.message_id)
    if cached is not None:
        return cached
    try:
        return await _resolve_channel(bot, payload).fetch_message(payload.message_id)
    except discord.HTTPException:
        logger.warning(
            f"翻訳対象メッセージの取得に失敗: メッセージID={payload.message_id}, "
            f"チャンネルID={payload.channel_id}",
            exc_info=True,
        )
        return None


async def _add_rate_limited_reaction(
    bot: commands.Bot, payload: discord.RawReactionActionEvent
) -> None:
    """レート制限超過を ⏳ リアクションで伝える（失敗はログのみ）

    同じメッセージへの ⏳ はウィンドウ内で1回だけ送る。

    Args:
        bot: Discordクライアント
        payload: レート制限を超えたリアクション追加イベント
    """
    if not _claim_rate_limited_reaction(payload.message_id):
        return
    channel = bot.get_partial_messageable(payload.channel_id, guild_id=payload.guild_id)
    try:
        await channel.get_partial_message(payload.message_id).add_reaction(_RATE_LIMITED_EMOJI)
    except discord.HTTPException:
        logger.warning("レート制限リアクションの追加に失敗しました", exc_info=True)


async def _notify_reaction_error(
    bot: commands.Bot, payload: discord.RawReactionActionEvent
) -> None:
    """リアクション処理の失敗をチャンネルに通知する

    連投を防ぐため、チャンネルごとに REACTION_ERROR_NOTIFY_COOLDOWN_SECONDS に1回までとする。
    送信失敗はログに残す。

    Args:
        bot: Discordクライアント
        payload: 処理に失敗したリアクション追加イベント
    """
    if not _reaction_error_notify_limiter.is_allowed(payload.channel_id):
        logger.debug(f"エラー通知を抑止: チャンネルID={payload.channel_id}")
        return
    _reaction_error_notify_limiter.record(payload.channel_id)
    try:
        await _resolve_channel(bot, payload).send("リアクション処理中にエラーが発生しました 😢")
    except discord.HTTPException:
        logger.warning("リアクションのエラー通知の送信に失敗しました", exc_info=True)


async def _translation_allowed_in_channel(guild_id: int, channel_id: int) -> bool:
    """チャンネルで発言可能かつ翻訳機能が有効かを判定する

    Args:
        guild_id: ギルドID
        channel_id: リアクションが付いたチャンネルのID

    Returns:
        翻訳してよい場合True
    """
    channel_config = await asyncio.to_thread(config_manager.get_config, guild_id)
    if not channel_config.can_bot_speak(channel_id):
        logger.debug(
            f"リアクション処理スキップ: ギルドID={guild_id}, チャンネルID={channel_id}, 発言不可"
        )
        return False
    if not channel_config.get_translation_enabled():
        logger.debug(
            f"翻訳機能が無効のためスキップ: ギルドID={guild_id}, チャンネルID={channel_id}"
        )
        return False
    return True


async def _process_translation_reaction(
    bot: commands.Bot, payload: discord.RawReactionActionEvent, guild_id: int, target_language: str
) -> None:
    """国旗リアクションに応じて翻訳する（チャンネル設定・重複・レート制限を確認してから）

    Args:
        bot: Discordクライアント
        payload: リアクション追加イベント
        guild_id: ギルドID
        target_language: 翻訳先言語
    """
    if not await _translation_allowed_in_channel(guild_id, payload.channel_id):
        return
    # 翻訳済みなら枠を消費せず、メッセージ取得もしない（最終的な重複判定は translate_and_reply）
    if _is_translation_claimed((payload.message_id, target_language)):
        logger.info(
            f"翻訳済み・翻訳中のためスキップ: メッセージID={payload.message_id}, 言語={target_language}"
        )
        return
    # 枠はメッセージ取得や translate_and_reply の空チェックより前に消費する（意図した挙動）。
    # 削除済み・画像だけのメッセージでも枠が減るが、その代わり fetch_message の連打も枠で抑えられる。
    if not _acquire_translation_quota(guild_id, payload.user_id, payload.channel_id):
        await _add_rate_limited_reaction(bot, payload)
        return

    message = await _fetch_reacted_message(bot, payload)
    if message is None:
        return
    logger.info(
        f"国旗リアクション検出: 言語={target_language}, ユーザーID={payload.user_id}, "
        f"メッセージID={message.id}"
    )
    await translate_and_reply(message, target_language)


async def _handle_raw_reaction(
    bot: commands.Bot, payload: discord.RawReactionActionEvent
) -> None:
    """リアクション追加時の処理

    メッセージキャッシュに無い（Bot 再起動前など）メッセージにも反応できるよう、
    raw イベントで受けて必要に応じてメッセージを取得する。

    Args:
        bot: Discordクライアント
        payload: リアクション追加イベント
    """
    logger.debug(
        f"リアクション検出: 絵文字={payload.emoji}, メッセージID={payload.message_id}, "
        f"ユーザーID={payload.user_id}"
    )
    # DM・ボット（自分自身を含む）のリアクションは無視
    if payload.guild_id is None:
        return
    if (payload.member is not None and payload.member.bot) or (
        bot.user is not None and payload.user_id == bot.user.id
    ):
        return
    target_language = _TRANSLATION_FLAGS.get(str(payload.emoji))
    if target_language is None:
        return

    try:
        await _process_translation_reaction(bot, payload, payload.guild_id, target_language)
    except Exception as e:
        logger.error(f"リアクション処理エラー: {str(e)}", exc_info=True)
        await _notify_reaction_error(bot, payload)


def setup_events(bot: commands.Bot, command_group: app_commands.Group) -> None:
    """イベントハンドラのセットアップ

    Args:
        bot: Discordクライアント
        command_group: コマンドグループ
    """
    from bot.commands import handle_command_error

    async def setup_hook() -> None:
        """ログイン直後に1度だけ呼ばれるフック"""
        await _handle_setup_hook(bot, command_group)

    bot.setup_hook = setup_hook  # type: ignore[method-assign]

    @bot.event
    async def on_ready() -> None:
        """ボットの準備完了時に呼ばれるイベント"""
        await _handle_on_ready(bot, command_group)

    @bot.event
    async def on_guild_join(guild: discord.Guild) -> None:
        """ギルド参加時に呼ばれるイベント"""
        await _handle_on_guild_join(guild)

    @bot.event
    async def on_guild_remove(guild: discord.Guild) -> None:
        """ギルド脱退時に呼ばれるイベント"""
        await _handle_on_guild_remove(guild)

    @bot.event
    async def on_message(message: discord.Message) -> None:
        """メッセージ受信時に呼ばれるイベント"""
        await _handle_message(bot, message)

    @bot.event
    async def on_raw_reaction_add(payload: discord.RawReactionActionEvent) -> None:
        """リアクション追加時に呼ばれるイベント（キャッシュ外のメッセージも含む）"""
        await _handle_raw_reaction(bot, payload)

    @bot.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        """アプリケーションコマンドのエラーハンドラ"""
        await handle_command_error(interaction, error)
