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
    user_id = str(message.author.id)

    # 期限切れなら会話をリセット
    if user_conversations[user_id].is_expired():
        logger.info(f"ユーザーID {user_id} の会話が期限切れのためリセット")
        # 新しい Sphene インスタンスを作成してリセット
        user_conversations[user_id] = Sphene(system_setting=load_system_prompt())

    # ユーザーの会話インスタンスを取得
    api = user_conversations[user_id]
    # 画像付きかどうかでログ出力を変える
    if images and len(images) > 0:
        logger.info(
            f"画像付きメッセージを処理: ユーザーID {user_id}, 画像数 {len(images)}"
        )
        answer = api.input_message(question, images)
    else:
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
            await process_conversation(message, question, is_reply, images)

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


def get_message_type(message: discord.Message) -> str:
    """メッセージの種類（通常/リプライ/スレッド）を判定する

    Args:
        message: Discordメッセージオブジェクト

    Returns:
        str: メッセージタイプ（"normal", "reply", "thread"）
    """
    if message.reference:  # リプライメッセージ
        return "reply"
    elif hasattr(message, "thread") and message.thread:  # スレッド内メッセージ
        return "thread"
    else:
        return "normal"


async def send_translation_response(
    message: discord.Message, translated_text: str, language_flag: str
) -> None:
    """メッセージタイプに応じた適切な方法で翻訳結果を送信する

    Args:
        message: 元のDiscordメッセージ
        translated_text: 翻訳されたテキスト、またはエラーメッセージ
        language_flag: 言語を示す絵文字 (🇺🇸 または 🇯🇵)
    """
    message_type = get_message_type(message)

    if message_type == "thread" and message.thread:
        # スレッド内のメッセージの場合は、そのスレッド内に返信
        await message.thread.send(
            f"{language_flag} {translated_text}", reference=message
        )
    else:
        # 通常メッセージやリプライの場合は今までどおり
        await message.channel.send(
            f"{language_flag} {translated_text}", reference=message
        )


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

    if target_language == "japanese":
        translate_func = translate_to_japanese
        language_flag = "🇯🇵"
        error_message = "翻訳中にエラーが発生しました 😢"
    else:  # デフォルトは英語
        translate_func = translate_to_english
        language_flag = "🇺🇸"
        error_message = "翻訳中にエラーが発生しました 😢"

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


async def handle_reaction(
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
                f"リアクション処理中にエラーが発生しました 😢: {str(e)}"
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
        await handle_message(bot, message)

    @bot.event
    async def on_reaction_add(reaction: discord.Reaction, user: discord.User) -> None:
        """リアクション追加時に呼ばれるイベント"""
        await handle_reaction(bot, reaction, user)

    @bot.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        """アプリケーションコマンドのエラーハンドラ"""
        await handle_command_error(interaction, error)
