import asyncio
import random
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from memory.fact_store import Fact

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
from utils.channel_config import ChannelConfigManager
from utils.text_utils import split_message, truncate_text

# リアクション用の絵文字リスト
_REACTION_EMOJIS = ["👀", "😊", "👍", "🤔", "✨", "💡"]


# bot の型ヒントを commands.Bot に変更
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

    # メンションされた場合
    if bot.user and bot.user in message.mentions:
        # bot.userがNoneではないことを確認済みなので、安全にidにアクセス可能
        bot_id = bot.user.id
        question = content.replace(f"<@{bot_id}>", "").strip()
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

    channel_context = ""
    channel_summary = ""
    topic_keywords: list[str] = []
    user_profile_str = ""
    relevant_facts_str = ""

    buffer = get_channel_buffer()
    channel_context = buffer.get_context_string(message.channel.id, limit=10)

    if config.CHANNEL_CONTEXT_ENABLED:
        from memory.channel_context import get_channel_context_store

        ctx = get_channel_context_store().get_context(message.channel.id)
        channel_summary = ctx.format_for_injection()
        topic_keywords = ctx.topic_keywords

    if config.USER_PROFILE_ENABLED:
        from memory.user_profile import get_user_profile_store

        profile = get_user_profile_store().get_profile(
            message.author.id, message.author.display_name
        )
        user_profile_str = profile.format_for_injection()

    if config.REFLECTION_ENABLED:
        from memory.fact_store import extract_keywords, get_fact_store

        keywords = extract_keywords(message.content or "")
        facts = get_fact_store().search(
            channel_id=message.channel.id,
            keywords=keywords,
            user_ids=[message.author.id],
            limit=3,
        )
        if facts:
            lines = ["【関連する過去の記憶】"] + [f"- {f.content}" for f in facts]
            relevant_facts_str = "\n".join(lines)

    return channel_context, channel_summary, topic_keywords, user_profile_str, relevant_facts_str


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
            await message.channel.send(chunk, reference=message)
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

    if config.USER_PROFILE_ENABLED and topic_keywords:
        from memory.user_profile import get_user_profile_store

        get_user_profile_store().update_last_topic(message.author.id, topic_keywords)

    if bot_user is not None:
        get_channel_buffer().add_message(
            ChannelMessage(
                message_id=0,
                channel_id=message.channel.id,
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
    answer = await api.async_input_message(
        input_text=question,
        author_name=author_name,
        image_urls=images,
        channel_context=channel_context,
        channel_summary=channel_summary,
        user_profile=user_profile_str,
        relevant_facts=relevant_facts_str,
    )

    if answer:
        await _send_chunks(message, split_message(answer), is_reply=is_reply)
        bot_user = message.guild.me if message.guild else None
        _post_response_update(message, answer, topic_keywords, bot_user)
    else:
        error_msg = "ごめん！応答の生成中にエラーが発生しちゃった...😢 もう一度試してみてね！"
        if is_reply:
            await message.channel.send(error_msg, reference=message)
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
    from memory.short_term import ChannelMessage, get_channel_buffer

    buffer = get_channel_buffer()
    judge = get_judge()

    # バッファからChannelMessageを作成
    channel_msg = ChannelMessage(
        message_id=message.id,
        channel_id=message.channel.id,
        author_id=message.author.id,
        author_name=message.author.display_name,
        content=message.content or "",
        timestamp=message.created_at,
    )

    recent_messages = buffer.get_recent_messages(message.channel.id, limit=20)

    # ルールベース判定
    result = judge.evaluate(
        message=channel_msg,
        recent_messages=recent_messages,
    )

    if result.score >= config.JUDGE_LLM_THRESHOLD_HIGH:
        # 高スコア: 即応答
        logger.info(
            f"自律応答決定(高スコア): チャンネル={message.channel.id}, "
            f"スコア={result.score}, 理由={result.reason}"
        )
        await _dispatch_response(bot, message, images, result.response_type)
        return

    if result.score <= config.JUDGE_LLM_THRESHOLD_LOW:
        # 低スコア: スキップ
        return

    # 中間スコア: LLM Judgeで二次判定
    if config.LLM_JUDGE_ENABLED:
        from memory.llm_judge import get_llm_judge

        context = buffer.get_context_string(message.channel.id, limit=15)
        llm_judge = get_llm_judge()
        should_respond, llm_response_type = await llm_judge.evaluate(
            message_content=message.content or "",
            recent_context=context,
            bot_name=config.BOT_NAME,
        )
        if should_respond and llm_response_type != "none":
            logger.info(
                f"自律応答決定(LLM Judge): チャンネル={message.channel.id}, "
                f"スコア={result.score}, タイプ={llm_response_type}"
            )
            await _dispatch_response(bot, message, images, llm_response_type)
    elif result.should_respond:
        # LLM Judge無効の場合はルールベースの判定に従う
        logger.info(
            f"自律応答決定(ルールベース): チャンネル={message.channel.id}, "
            f"スコア={result.score}, 理由={result.reason}"
        )
        await _dispatch_response(bot, message, images, result.response_type)


async def _dispatch_response(
    bot: commands.Bot,
    message: discord.Message,
    images: list[str],
    response_type: str,
) -> None:
    """応答タイプに応じて適切な応答を実行する

    Args:
        bot: Discordクライアント
        message: トリガーとなったDiscordメッセージ
        images: 添付画像URLリスト
        response_type: "full_response" | "short_ack" | "react_only"
    """
    if response_type == "react_only":
        await _send_reaction(message)
    elif response_type == "short_ack":
        await _process_short_ack(bot, message)
    else:
        await _process_autonomous_response(bot, message, images)


async def _send_reaction(message: discord.Message) -> None:
    """ランダムな絵文字リアクションを追加する"""
    from memory.judge import get_judge

    try:
        emoji = random.choice(_REACTION_EMOJIS)
        await message.add_reaction(emoji)
        logger.info(
            f"リアクション応答: チャンネル={message.channel.id}, 絵文字={emoji}"
        )
        get_judge().record_response(message.channel.id)
    except Exception as e:
        logger.error(f"リアクション追加エラー: {e}", exc_info=True)


async def _process_short_ack(
    bot: commands.Bot,
    message: discord.Message,
) -> None:
    """短い相槌を生成して送信する"""
    from memory.judge import get_judge
    from memory.short_term import ChannelMessage, get_channel_buffer

    buffer = get_channel_buffer()
    context = buffer.get_context_string(message.channel.id, limit=10)
    if not context:
        return

    answer = await asyncio.to_thread(
        generate_short_ack,
        channel_context=context,
        trigger_message=message.content or "",
    )

    if answer:
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
                    author_id=bot.user.id,
                    author_name=bot.user.display_name,
                    content=answer,
                    timestamp=datetime.now(timezone.utc),
                    is_bot=True,
                )
            )


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
    answer = await api.async_input_message(
        input_text=message.content or "",
        author_name=message.author.display_name,
        image_urls=images,
        channel_context=channel_context,
        channel_summary=channel_summary,
        user_profile=user_profile_str,
        relevant_facts=relevant_facts_str,
    )

    if answer:
        await _send_chunks(message, split_message(answer), is_reply=False)
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


async def _handle_message(bot: commands.Bot, message: discord.Message) -> None:
    """メッセージ受信イベントの処理

    Args:
        bot: Discordクライアント
        message: Discordメッセージオブジェクト
    """
    try:
        # 自分自身やボットのメッセージは無視
        if message.author == bot.user or message.author.bot:
            return

        if message.content is None and len(message.attachments) == 0:
            return

        # ギルドIDを取得
        if message.guild is None:
            # DMなどギルドがない場合は処理しない
            logger.info("ギルドなしのメッセージは処理しません")
            return

        guild_id = message.guild.id

        # ギルド固有の設定を取得
        channel_config = config_manager.get_config(guild_id)

        # チャンネル設定に基づいて発言可能かどうかをチェック
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
            return  # 処理を中断

        # 短期記憶: 全メッセージをチャンネルバッファに追加
        from memory.short_term import ChannelMessage, get_channel_buffer

        buffer = get_channel_buffer()

        # バッファ追加前に最終メッセージ時刻を取得（再活性化チェック用）
        pre_add_last_time = buffer.get_last_message_time(message.channel.id)

        buffer.add_message(
            ChannelMessage(
                message_id=message.id,
                channel_id=message.channel.id,
                author_id=message.author.id,
                author_name=message.author.display_name,
                content=message.content or "",
                timestamp=message.created_at,
            )
        )

        # チャンネルコンテキスト: メッセージカウント + 要約トリガー
        if config.CHANNEL_CONTEXT_ENABLED:
            from memory.channel_context import get_channel_context_store
            from memory.summarizer import get_summarizer

            ctx = get_channel_context_store().get_context(message.channel.id)
            ctx.increment_message_count()
            recent = buffer.get_recent_messages(message.channel.id, limit=20)
            get_summarizer().maybe_summarize(message.channel.id, recent)

        # ユーザープロファイル: メッセージ記録
        if config.USER_PROFILE_ENABLED:
            from memory.user_profile import get_user_profile_store

            get_user_profile_store().record_message(
                message.author.id, message.channel.id, message.author.display_name
            )

        # バッファ量ベースの反省会トリガー
        if config.REFLECTION_ENABLED:
            from memory.reflection import get_reflection_engine

            engine = get_reflection_engine()
            recent = buffer.get_recent_messages(message.channel.id, limit=100)
            if (
                buffer.count_messages_since_reflection(message.channel.id)
                >= config.REFLECTION_MAX_BUFFER_MESSAGES
            ):
                engine.maybe_reflect(message.channel.id, recent)

        # 画像添付の検出
        images = []
        for attachment in message.attachments:
            if attachment.content_type and attachment.content_type.startswith("image/"):
                logger.debug(
                    f"画像検出: {attachment.url}, タイプ: {attachment.content_type}"
                )
                images.append(attachment.url)

        # ボットが呼ばれたかどうかをチェック
        is_mentioned, question, is_reply = await is_bot_mentioned(bot, message)
        if is_mentioned:
            # ユーザープロファイル: ボットメンション記録
            if config.USER_PROFILE_ENABLED:
                from memory.user_profile import get_user_profile_store

                get_user_profile_store().record_bot_mention(message.author.id)

            await process_conversation(message, question, is_reply, images)
            # エンゲージメント記録（自律応答のスコアブーストに使用）
            if config.AUTONOMOUS_RESPONSE_ENABLED:
                from memory.judge import get_judge

                get_judge().record_response(message.channel.id)
            return

        # 自律応答: メンションされていない場合の判定
        if config.AUTONOMOUS_RESPONSE_ENABLED:
            await _try_autonomous_response(bot, message, images)

        # 自発的会話: 沈黙後の再活性化チェック
        if config.PROACTIVE_CONVERSATION_ENABLED and pre_add_last_time is not None:
            await _try_proactive_conversation(bot, message, pre_add_last_time)

    except Exception as e:
        logger.error(f"メッセージ処理中にエラー発生: {str(e)}", exc_info=True)
        await message.channel.send("ごめん！メッセージ処理中にエラーが発生しちゃった...😢")


async def _try_proactive_conversation(
    bot: commands.Bot,
    message: discord.Message,
    pre_add_last_time: datetime,
) -> None:
    """沈黙後の再活性化時、shareable ファクトで自発会話を試みる

    Args:
        bot: Discordクライアント
        message: トリガーとなったDiscordメッセージ
        pre_add_last_time: バッファ追加前の最終メッセージ時刻（UTC）
    """
    from memory.fact_store import get_fact_store
    from memory.judge import get_judge

    # 再活性化チェック（前のメッセージからの沈黙時間）
    msg_time = message.created_at
    if msg_time.tzinfo is None:
        msg_time = msg_time.replace(tzinfo=timezone.utc)
    silence_minutes = (msg_time - pre_add_last_time).total_seconds() / 60
    if silence_minutes < config.PROACTIVE_SILENCE_MINUTES:
        return

    # クールダウンチェック
    if get_judge().is_in_cooldown(message.channel.id):
        return

    # shareable ファクト取得
    facts = get_fact_store().get_shareable_facts(message.channel.id)
    if not facts:
        return

    # 最上位のファクトで自発会話メッセージを生成・送信
    fact = facts[0]
    await _dispatch_proactive_message(bot, message, fact)


async def _dispatch_proactive_message(
    bot: commands.Bot,
    message: discord.Message,
    fact: "Fact",
) -> None:
    """shareable ファクトをもとに自発会話メッセージを生成して送信する。

    Sphene の会話履歴を汚染しないよう generate_proactive_message を使う。

    Args:
        bot: Discordクライアント
        message: トリガーとなったDiscordメッセージ
        fact: 話題にするファクト
    """
    from ai.conversation import generate_proactive_message
    from memory.judge import get_judge
    from memory.short_term import get_channel_buffer

    channel_context = get_channel_buffer().get_context_string(message.channel.id, limit=10) or None

    answer = await asyncio.to_thread(
        generate_proactive_message,
        fact_content=fact.content,
        channel_context=channel_context,
    )

    if answer:
        await _send_chunks(message, split_message(answer), is_reply=False)
        logger.info(
            f"自発会話送信: チャンネル={message.channel.id}, "
            f"fact={fact.content[:50]}"
        )
        get_judge().record_response(message.channel.id)


async def _handle_on_ready(
    bot: commands.Bot, command_group: app_commands.Group
) -> None:
    """ボットの準備完了時の処理

    Args:
        bot: Discordクライアント
        command_group: コマンドグループ
    """
    # コマンドグループを追加
    bot.tree.add_command(command_group)
    await bot.tree.sync()

    if bot.user:
        logger.info(f"Discordボット起動完了: {bot.user.name}#{bot.user.discriminator}")
    else:
        logger.error("Discordボットのユーザー情報を取得できませんでした")

    # 各ギルドのチャンネル設定を初期化
    logger.info("ギルドごとのチャンネル設定を初期化")
    for guild in bot.guilds:
        logger.info(f"ギルド {guild.name} (ID: {guild.id}) の設定をチェック")
        try:
            config_manager.get_config(guild.id)
        except Exception as e:
            logger.error(f"ギルドID {guild.id} の設定初期化中にエラー: {str(e)}")


async def _handle_on_guild_join(guild: discord.Guild) -> None:
    """ギルド参加時の処理

    Args:
        guild: 参加したDiscordギルド
    """
    logger.info(f"新しいギルド {guild.name} (ID: {guild.id}) に参加しました")
    try:
        config_manager.create_guild_config(guild.id)
        logger.info(f"ギルドID {guild.id} の設定ファイルを作成しました")
    except Exception as e:
        logger.error(f"ギルドID {guild.id} の設定ファイル作成中にエラー: {str(e)}")


async def _handle_on_guild_remove(guild: discord.Guild) -> None:
    """ギルド脱退時の処理

    Args:
        guild: 脱退したDiscordギルド
    """
    logger.info(f"ギルド {guild.name} (ID: {guild.id}) から脱退しました")
    try:
        success = config_manager.delete_guild_config(guild.id)
        if success:
            logger.info(f"ギルドID {guild.id} の設定ファイルを削除しました")
        else:
            logger.warning(f"ギルドID {guild.id} の設定ファイル削除に失敗しました")
    except Exception as e:
        logger.error(f"ギルドID {guild.id} の設定ファイル削除中にエラー: {str(e)}")


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
            await message.channel.send(chunk, reference=message)
        else:
            await message.channel.send(chunk)


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

    # 言語に応じて翻訳関数とフラグを選択
    from utils.text_utils import translate_to_english, translate_to_japanese

    error_message = "翻訳中にエラーが発生しました 😢"
    if target_language == "japanese":
        translate_func = translate_to_japanese
        language_flag = "🇯🇵"
    else:  # デフォルトは英語
        translate_func = translate_to_english
        language_flag = "🇺🇸"

    # 翻訳実行
    translated_text = await translate_func(content)

    if translated_text:
        # 適切な方法で翻訳結果を送信
        await send_translation_response(message, translated_text, language_flag)
        logger.info(f"翻訳結果を送信: {truncate_text(translated_text)}")
    else:
        # エラー時も同様に対応
        await send_translation_response(message, error_message, language_flag)
        logger.warning(
            f"翻訳エラー: タイプ={message_type}, ユーザーID={user_id}, メッセージ: {truncate_text(content)}"
        )


async def _handle_reaction(
    bot: commands.Bot, reaction: discord.Reaction, user: discord.User
) -> None:
    """リアクション追加時の処理

    Args:
        bot: Discordクライアント
        reaction: 追加されたリアクション
        user: リアクションを追加したユーザー
    """
    try:
        # デバッグ用のログ追加：リアクション検出時の詳細情報
        logger.debug(
            f"リアクション検出: 絵文字={str(reaction.emoji)}, メッセージID={reaction.message.id}, "
            f"ユーザーID={user.id}, メッセージ作成日時={reaction.message.created_at}"
        )
        # ボット自身のリアクションは無視
        if user.bot:
            return

        # リアクション追加されたメッセージを取得
        message = reaction.message

        # メッセージがギルドに所属していない場合は処理しない
        if message.guild is None:
            return

        guild_id = message.guild.id

        # ギルド固有の設定を取得して発言可能かチェック
        channel_config = config_manager.get_config(guild_id)
        channel_id = message.channel.id
        can_speak = channel_config.can_bot_speak(channel_id)

        if not can_speak:
            logger.debug(
                f"リアクション処理スキップ: ギルドID={guild_id}, チャンネルID={channel_id}, 発言不可"
            )
            return

        # 翻訳機能が有効かチェック
        translation_enabled = channel_config.get_translation_enabled()
        if not translation_enabled:
            logger.debug(
                f"翻訳機能が無効のためスキップ: ギルドID={guild_id}, チャンネルID={channel_id}"
            )
            return

        # 絵文字によって処理を分岐
        emoji_str = str(reaction.emoji)

        # アメリカ国旗絵文字のチェック
        if emoji_str == "🇺🇸" or emoji_str == "flag_us":
            logger.info(
                f"アメリカ国旗リアクション検出: ユーザーID={user.id}, メッセージID={message.id}"
            )
            await translate_and_reply(message, "english")

        # 日本国旗絵文字のチェック
        elif emoji_str == "🇯🇵" or emoji_str == "flag_jp":
            logger.info(
                f"日本国旗リアクション検出: ユーザーID={user.id}, メッセージID={message.id}"
            )
            await translate_and_reply(message, "japanese")

    except Exception as e:
        logger.error(f"リアクション処理エラー: {str(e)}", exc_info=True)
        # エラーが発生した場合、可能であればチャンネルにメッセージを送信
        try:
            await reaction.message.channel.send(
                "リアクション処理中にエラーが発生しました 😢"
            )
        except Exception:
            pass


def setup_events(bot: commands.Bot, command_group: app_commands.Group) -> None:
    """イベントハンドラのセットアップ

    Args:
        bot: Discordクライアント
        command_group: コマンドグループ
    """
    from bot.commands import handle_command_error

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
    async def on_reaction_add(reaction: discord.Reaction, user: discord.User) -> None:
        """リアクション追加時に呼ばれるイベント"""
        await _handle_reaction(bot, reaction, user)

    @bot.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        """アプリケーションコマンドのエラーハンドラ"""
        await handle_command_error(interaction, error)
