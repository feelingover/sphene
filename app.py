import logging
from collections import defaultdict
from pathlib import Path
from typing import DefaultDict

import discord
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

intents = discord.Intents.all()
client = discord.Client(intents=intents)


@client.event
async def on_ready() -> None:
    if client.user:
        logger.info(
            f"Discordボット起動完了: {client.user.name}#{client.user.discriminator}"
        )
    else:
        logger.error("Discordボットのユーザー情報を取得できませんでした")
    print("ready to go.")


async def handle_channel_list_command(message: discord.Message) -> bool:
    """チャンネル一覧コマンドを処理する

    Args:
        message: Discordメッセージオブジェクト

    Returns:
        bool: コマンドが処理された場合はTrue
    """
    # メッセージ内容と管理者権限のチェック
    if message.content != "!sphene channels":
        return False

    # Memberタイプであることの確認と管理者権限チェック
    if (
        not isinstance(message.author, discord.Member)
        or not message.author.guild_permissions.administrator
    ):
        return False

    channel_info = "👑 **Sphene使用可能チャンネル一覧**:\n"

    # チャンネルリストの作成
    for channel_id in config.ALLOWED_CHANNEL_IDS:
        channel = client.get_channel(channel_id)
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
    await message.channel.send(channel_info)
    return True


@client.event
async def on_message(message: discord.Message) -> None:
    try:
        if message.author == client.user or message.author.bot:
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
            # 管理者コマンドのチェック
            if await handle_channel_list_command(message):
                return
            return

        # メンションされたときだけ応答
        if client.user in message.mentions and message.content is not None:
            # 型チェック後にスライシングする
            content: str = message.content  # 型を明示的に指定
            question = content[4:] if len(content) > 4 else ""
            user_id = str(message.author.id)

            # プレビュー用の安全な文字列を生成
            preview = question[:30] + "..." if len(question) > 30 else question
            logger.info(
                f"メンション検出: ユーザーID {user_id}, チャンネルID {message.channel.id}, メッセージ: {preview}"
            )

            # ユーザーの会話インスタンスを取得
            api = user_conversations[user_id]
            api.input_message(question)
            answer = api.input_list[-1]["content"]

            # 長くなりすぎた会話履歴をリセット（10往復を超えたら）
            if len(api.input_list) > 21:  # system(1) + 10往復(20) = 21
                logger.info(
                    f"ユーザーID {user_id} の会話履歴をリセット (メッセージ数: {len(api.input_list)})"
                )
                await message.channel.send(
                    "ごめん！会話が長くなってきたからリセットするね！🔄"
                )
                user_conversations[user_id] = Sphene(
                    system_setting=load_system_prompt()
                )
                api = user_conversations[user_id]
                api.input_message(question)
                answer = api.input_list[-1]["content"]

            logger.info(f"応答送信: ユーザーID {user_id}, 応答: {answer[:30]}...")
            await message.channel.send(answer)

    except Exception as e:
        logger.error(f"エラー発生: {str(e)}", exc_info=True)
        await message.channel.send(f"ごめん！エラーが発生しちゃった...😢: {str(e)}")


logger.info("Discordボットの起動を開始")
client.run(config.DISCORD_TOKEN)
