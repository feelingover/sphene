import logging
from collections import defaultdict
from pathlib import Path
from typing import DefaultDict

import discord
from discord import app_commands
from discord.ext import commands
from openai import OpenAI

import config

# ロギングの設定
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("sphene")

aiclient = OpenAI(api_key=config.OPENAI_API_KEY)


def load_system_prompt() -> str:
    prompt_path = Path(__file__).parent / "prompts" / "system.txt"
    logger.info(f"システムプロンプトを読み込み: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8").strip()


class Sphene:
    def __init__(self, system_setting: str) -> None:
        self.system: dict = {"role": "system", "content": system_setting}
        self.input_list: list = [self.system]
        self.logs: list = []
        # 会話の有効期限を設定（30分）
        self.last_interaction = None
        logger.info("Spheneインスタンスを初期化")

    def input_message(self, input_text: str | None) -> None:
        if not isinstance(input_text, str):
            logger.warning("受信したメッセージが文字列ではありません")
            return

        # 型ガード後の変数を定義してからスライシング
        input_str: str = input_text
        preview = input_str[:30] + "..." if len(input_str) > 30 else input_str
        logger.info(f"ユーザーメッセージを受信: {preview}")
        self.input_list.append({"role": "user", "content": input_text})

        logger.info("OpenAI APIリクエスト送信")
        result = aiclient.chat.completions.create(
            model="gpt-4o-mini", messages=self.input_list
        )
        self.logs.append(result)

        response_content = result.choices[0].message.content
        if response_content:
            logger.info(f"OpenAI APIレスポンス受信: {response_content[:30]}...")
        else:
            logger.warning("OpenAI APIからの応答が空です")

        self.input_list.append({"role": "assistant", "content": response_content})


# ユーザーごとの会話インスタンスを保持する辞書
user_conversations: DefaultDict[str, Sphene] = defaultdict(
    lambda: Sphene(system_setting=load_system_prompt())
)

# Botの初期化
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


# コマンドグループ
command_group = app_commands.Group(
    name=config.COMMAND_GROUP_NAME, description=f"{config.BOT_NAME}ボットのコマンド"
)


@command_group.command(name="nickname", description="ボットのニックネームを変更します")
@app_commands.checks.has_permissions(administrator=True)
async def change_nickname(interaction: discord.Interaction) -> None:
    """ニックネーム変更コマンドを処理する"""
    # ギルド情報を取得
    if not interaction.guild:
        await interaction.response.send_message(
            "😵 サーバー情報の取得に失敗したよ！DMではこの機能使えないよ〜",
            ephemeral=True,
        )
        return

    # このギルドでのbotのメンバー情報を取得
    bot_member = interaction.guild.get_member(bot.user.id) if bot.user else None
    if not bot_member:
        await interaction.response.send_message(
            "😵 ボットのメンバー情報の取得に失敗しちゃった...", ephemeral=True
        )
        return

    try:
        # BOT_NAMEに設定したニックネームに変更
        await bot_member.edit(nick=config.BOT_NAME)
        await interaction.response.send_message(
            f"✨ ニックネームを「{config.BOT_NAME}」に変更したよ！"
        )
        logger.info(
            f"ニックネーム変更: サーバーID {interaction.guild.id}, 新しい名前: {config.BOT_NAME}"
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            "😭 権限が足りなくてニックネームを変更できなかったよ！BOTの権限を確認してね！",
            ephemeral=True,
        )
        logger.error(
            f"ニックネーム変更失敗: 権限不足, サーバーID {interaction.guild.id}"
        )
    except Exception as e:
        await interaction.response.send_message(
            f"😱 エラーが発生しちゃった: {str(e)}", ephemeral=True
        )
        logger.error(f"ニックネーム変更失敗: {str(e)}", exc_info=True)


@command_group.command(
    name="channels",
    description=f"{config.BOT_NAME}が使用可能なチャンネル一覧を表示します",
)
@app_commands.checks.has_permissions(administrator=True)
async def list_channels(interaction: discord.Interaction) -> None:
    """チャンネル一覧コマンドを処理する"""
    channel_info = f"👑 **{config.BOT_NAME}使用可能チャンネル一覧**:\n"

    # チャンネルリストの作成
    for channel_id in config.ALLOWED_CHANNEL_IDS:
        channel = bot.get_channel(channel_id)
        # チャンネルが存在し、名前属性があるかチェック
        if channel and hasattr(channel, "name"):
            channel_name = getattr(channel, "name")
        else:
            channel_name = f"不明なチャンネル (ID: {channel_id})"
        channel_info += f"• {channel_name} (ID: {channel_id})\n"

    # 許可チャンネルがない場合の表示
    if not config.ALLOWED_CHANNEL_IDS:
        channel_info += (
            "現在、全てのチャンネルで使用可能です（チャンネル制限なし）！🎉\n"
        )

    # 設定方法の説明を追加
    channel_info += "\n制限の設定方法: `.env`ファイルの`ALLOWED_CHANNEL_IDS`に使用可能なチャンネルIDをカンマ区切りで設定してね！"

    # メッセージ送信
    await interaction.response.send_message(channel_info)


@command_group.command(name="reset", description="あなたとの会話履歴をリセットします")
async def reset_conversation(interaction: discord.Interaction) -> None:
    """会話履歴リセットコマンドを処理する"""
    user_id = str(interaction.user.id)

    if user_id in user_conversations:
        user_conversations[user_id] = Sphene(system_setting=load_system_prompt())
        await interaction.response.send_message(
            "🔄 会話履歴をリセットしたよ！また一から話そうね！"
        )
        logger.info(f"ユーザーID {user_id} の会話履歴を手動リセット")
    else:
        await interaction.response.send_message(
            "🤔 まだ話したことがないみたいだね！これから仲良くしようね！"
        )


async def is_bot_mentioned(message: discord.Message) -> tuple[bool, str]:
    """メッセージがボットに対するものかどうかを判断し、質問内容を抽出する

    Args:
        message: Discordメッセージオブジェクト

    Returns:
        tuple[bool, str]: (ボットに対するメッセージかどうか, 質問内容)
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
        preview = question[:30] + "..." if len(question) > 30 else question
        logger.info(
            f"メンション検出: ユーザーID {user_id}, チャンネルID {message.channel.id}, メッセージ: {preview}"
        )
        return True, question

    # 設定された名前で呼ばれた場合
    if config.BOT_NAME in content:
        question = content  # メッセージ全体を質問として扱う
        preview = question[:30] + "..." if len(question) > 30 else question
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
            preview = question[:30] + "..." if len(question) > 30 else question
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

    # ユーザーの会話インスタンスを取得
    api = user_conversations[user_id]
    api.input_message(question)
    answer = api.input_list[-1]["content"]

    # 長くなりすぎた会話履歴をリセット（10往復を超えたら）
    if len(api.input_list) > 21:  # system(1) + 10往復(20) = 21
        logger.info(
            f"ユーザーID {user_id} の会話履歴をリセット (メッセージ数: {len(api.input_list)})"
        )
        await message.channel.send("ごめん！会話が長くなってきたからリセットするね！🔄")
        user_conversations[user_id] = Sphene(system_setting=load_system_prompt())
        api = user_conversations[user_id]
        api.input_message(question)
        answer = api.input_list[-1]["content"]

    logger.info(f"応答送信: ユーザーID {user_id}, 応答: {answer[:30]}...")
    await message.channel.send(answer)


@bot.event
async def on_ready() -> None:
    await bot.add_cog(commands.Cog(name="Management"))
    # コマンドグループを追加（戻り値を捨てる）
    bot.tree.add_command(command_group)  # type: ignore
    await bot.tree.sync()

    if bot.user:
        logger.info(f"Discordボット起動完了: {bot.user.name}#{bot.user.discriminator}")
    else:
        logger.error("Discordボットのユーザー情報を取得できませんでした")


@bot.event
async def on_message(message: discord.Message) -> None:
    try:
        # 自分自身やボットのメッセージは無視
        if message.author == bot.user or message.author.bot:
            return

        if message.content is None:
            return

        # チャンネル制限のチェック
        # ALLOWED_CHANNEL_IDSが空の場合は全チャンネルで応答する
        # 空でない場合は、許可されたチャンネルIDのみで応答する
        if (
            len(config.ALLOWED_CHANNEL_IDS) > 0  # リストが空でない場合
            and message.channel.id
            not in config.ALLOWED_CHANNEL_IDS  # IDが許可リストにない
        ):
            return

        # ボットが呼ばれたかどうかをチェック
        is_mentioned, question = await is_bot_mentioned(message)
        if is_mentioned:
            await process_conversation(message, question)

    except Exception as e:
        logger.error(f"エラー発生: {str(e)}", exc_info=True)
        await message.channel.send(f"ごめん！エラーが発生しちゃった...😢: {str(e)}")


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
) -> None:
    """スラッシュコマンドエラーハンドラ"""
    if isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message(
            "👮 このコマンドは管理者権限が必要だよ！", ephemeral=True
        )
        return

    logger.error(f"コマンドエラー発生: {str(error)}", exc_info=True)
    await interaction.response.send_message(
        f"😱 コマンド実行中にエラーが発生しちゃった: {str(error)}", ephemeral=True
    )


logger.info("Discordボットの起動を開始")
bot.run(config.DISCORD_TOKEN)
