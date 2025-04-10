from typing import Tuple

import discord
from discord import app_commands

import config
from ai.conversation import user_conversations
from log_utils.logger import logger
from utils.text_utils import truncate_text


async def is_bot_mentioned(
    bot: discord.Client, message: discord.Message
) -> Tuple[bool, str]:
    """メッセージがボットに対するものかどうかを判断し、質問内容を抽出する

    Args:
        bot: Discordクライアント
        message: Discordメッセージオブジェクト

    Returns:
        Tuple[bool, str]: (ボットに対するメッセージかどうか, 質問内容)
    """
    if message.content is None:
        return False, ""

    content: str = message.content
    user_id = str(message.author.id)

    # メンションされた場合
    if bot.user and bot.user in message.mentions:
        # bot.userがNoneではないことを確認済みなので、安全にidにアクセス可能
        bot_id = bot.user.id
        question = content.replace(f"<@{bot_id}>", "").strip()
        preview = truncate_text(question)
        logger.info(
            f"メンション検出: ユーザーID {user_id}, チャンネルID {message.channel.id}, メッセージ: {preview}"
        )
        return True, question

    # 設定された名前で呼ばれた場合
    if config.BOT_NAME in content:
        question = content  # メッセージ全体を質問として扱う
        preview = truncate_text(question)
        logger.info(
            f"名前で呼ばれました: ユーザーID {user_id}, チャンネルID {message.channel.id}, メッセージ: {preview}"
        )
        return True, question

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
            logger.info(
                f"リプライ検出: ユーザーID {user_id}, チャンネルID {message.channel.id}, メッセージ: {preview}"
            )
            return True, question

    return False, ""


async def process_conversation(message: discord.Message, question: str) -> None:
    """ユーザーとの会話を処理する

    Args:
        message: Discordメッセージオブジェクト
        question: 質問内容
    """
    user_id = str(message.author.id)

    # 期限切れなら会話をリセット
    if user_conversations[user_id].is_expired():
        logger.info(f"ユーザーID {user_id} の会話が期限切れのためリセット")
        user_conversations[user_id] = user_conversations.default_factory()

    # ユーザーの会話インスタンスを取得
    api = user_conversations[user_id]
    answer = api.input_message(question)

    if answer:
        logger.info(f"応答送信: ユーザーID {user_id}, 応答: {truncate_text(answer)}")
        await message.channel.send(answer)
    else:
        await message.channel.send(
            "ごめん！応答の生成中にエラーが発生しちゃった...😢 もう一度試してみてね！"
        )


async def handle_message(bot: discord.Client, message: discord.Message) -> None:
    """メッセージ受信イベントの処理

    Args:
        bot: Discordクライアント
        message: Discordメッセージオブジェクト
    """
    try:
        # 自分自身やボットのメッセージは無視
        if message.author == bot.user or message.author.bot:
            return

        if message.content is None:
            return

        # チャンネル制限のチェック
        if (
            config.ALLOWED_CHANNEL_IDS  # リストが空でない場合
            and message.channel.id
            not in config.ALLOWED_CHANNEL_IDS  # IDが許可リストにない
        ):
            return

        # ボットが呼ばれたかどうかをチェック
        is_mentioned, question = await is_bot_mentioned(bot, message)
        if is_mentioned:
            await process_conversation(message, question)

    except Exception as e:
        logger.error(f"エラー発生: {str(e)}", exc_info=True)
        await message.channel.send(f"ごめん！エラーが発生しちゃった...😢: {str(e)}")


def setup_events(bot: discord.Client, command_group: app_commands.Group) -> None:
    """イベントハンドラのセットアップ

    Args:
        bot: Discordクライアント
        command_group: コマンドグループ
    """
    from bot.commands import handle_command_error

    @bot.event
    async def on_ready() -> None:
        """ボットの準備完了時に呼ばれるイベント"""
        await bot.add_cog(discord.ext.commands.Cog(name="Management"))
        # コマンドグループを追加
        bot.tree.add_command(command_group)
        await bot.tree.sync()

        if bot.user:
            logger.info(
                f"Discordボット起動完了: {bot.user.name}#{bot.user.discriminator}"
            )
        else:
            logger.error("Discordボットのユーザー情報を取得できませんでした")

    @bot.event
    async def on_message(message: discord.Message) -> None:
        """メッセージ受信時に呼ばれるイベント"""
        await handle_message(bot, message)

    @bot.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        """アプリケーションコマンドのエラーハンドラ"""
        await handle_command_error(interaction, error)
