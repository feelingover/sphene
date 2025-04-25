from typing import Tuple

import discord
from discord import app_commands
from discord.ext import commands  # commands をインポート

import config

# Sphene と load_system_prompt をインポート
from ai.conversation import Sphene, load_system_prompt, user_conversations
from log_utils.logger import logger
from utils.channel_config import ChannelConfigManager
from utils.text_utils import truncate_text


# bot の型ヒントを commands.Bot に変更
async def is_bot_mentioned(
    bot: commands.Bot, message: discord.Message
) -> Tuple[bool, str, bool]:
    """メッセージがボットに対するものかどうかを判断し、質問内容を抽出する

    Args:
        bot: Discordクライアント
        message: Discordメッセージオブジェクト

    Returns:
        Tuple[bool, str, bool]: (ボットに対するメッセージかどうか, 質問内容, リプライかどうか)
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


async def process_conversation(
    message: discord.Message, question: str, is_reply: bool = False
) -> None:
    """ユーザーとの会話を処理する

    Args:
        message: Discordメッセージオブジェクト
        question: 質問内容
        is_reply: リプライによるメッセージかどうか
    """
    user_id = str(message.author.id)

    # 期限切れなら会話をリセット
    if user_conversations[user_id].is_expired():
        logger.info(f"ユーザーID {user_id} の会話が期限切れのためリセット")
        # 新しい Sphene インスタンスを作成してリセット
        user_conversations[user_id] = Sphene(system_setting=load_system_prompt())

    # ユーザーの会話インスタンスを取得
    api = user_conversations[user_id]
    answer = api.input_message(question)

    if answer:
        if is_reply:
            logger.info(
                f"リプライとして応答送信: ユーザーID {user_id}, 応答: {truncate_text(answer)}"
            )
            await message.channel.send(answer, reference=message)
        else:
            logger.info(
                f"通常応答送信: ユーザーID {user_id}, 応答: {truncate_text(answer)}"
            )
            await message.channel.send(answer)
    else:
        if is_reply:
            await message.channel.send(
                "ごめん！応答の生成中にエラーが発生しちゃった...😢 もう一度試してみてね！",
                reference=message,
            )
        else:
            await message.channel.send(
                "ごめん！応答の生成中にエラーが発生しちゃった...😢 もう一度試してみてね！"
            )


# チャンネル設定マネージャーのシングルトンインスタンスを取得
config_manager = ChannelConfigManager.get_instance()


async def handle_message(bot: commands.Bot, message: discord.Message) -> None:
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
        behavior = channel_config.get_behavior()
        in_list = channel_config.is_channel_in_list(channel_id)
        can_speak = channel_config.can_bot_speak(channel_id)

        # デバッグ用の詳細なログ出力
        logger.debug(
            f"チャンネル評価: ギルドID={guild_id}, チャンネルID={channel_id}, "
            f"リスト含まれる={in_list}, "
            f"評価モード={behavior}({channel_config.get_mode_display_name()}), "
            f"発言可能={can_speak}"
        )

        if not can_speak:
            logger.info(
                f"チャンネルでの発言をスキップ: ギルドID={guild_id}, モード={channel_config.get_mode_display_name()}, "
                f"ユーザーID={message.author.id}, チャンネルID={message.channel.id}"
            )
            return  # 処理を中断

        # ボットが呼ばれたかどうかをチェック
        is_mentioned, question, is_reply = await is_bot_mentioned(bot, message)
        if is_mentioned:
            await process_conversation(message, question, is_reply)

    except Exception as e:
        logger.error(f"エラー発生: {str(e)}", exc_info=True)
        await message.channel.send(f"ごめん！エラーが発生しちゃった...😢: {str(e)}")


async def _handle_on_ready(
    bot: commands.Bot, command_group: app_commands.Group
) -> None:
    """ボットの準備完了時の処理

    Args:
        bot: Discordクライアント
        command_group: コマンドグループ
    """
    await bot.add_cog(discord.ext.commands.Cog(name="Management"))
    # コマンドグループを追加
    bot.tree.add_command(command_group)
    await bot.tree.sync()

    if bot.user:
        logger.info(f"Discordボット起動完了: {bot.user.name}#{bot.user.discriminator}")
    else:
        logger.error("Discordボットのユーザー情報を取得できませんでした")

    # 各ギルドの設定ファイルを初期化
    logger.info("ギルドごとのチャンネル設定ファイルを初期化")
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
        await handle_message(bot, message)

    @bot.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        """アプリケーションコマンドのエラーハンドラ"""
        await handle_command_error(interaction, error)
