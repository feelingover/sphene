import logging
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import DefaultDict, List, Optional, Tuple

import discord
from discord import app_commands
from discord.ext import commands
from openai import OpenAI
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionAssistantMessageParam,
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)

import config

# ロギングの設定
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("sphene")

# OpenAIクライアントの初期化
aiclient = OpenAI(api_key=config.OPENAI_API_KEY)

# 定数の定義
MAX_CONVERSATION_AGE_MINUTES = 30
MAX_CONVERSATION_TURNS = 10  # 往復数の上限
PREVIEW_LENGTH = 30  # プレビュー表示時の文字数上限


def truncate_text(text: str, max_length: int = PREVIEW_LENGTH) -> str:
    """テキストを指定された長さに切り詰めて表示用のプレビューを作成する

    Args:
        text: 元のテキスト
        max_length: 最大長さ

    Returns:
        str: 切り詰められたテキスト（長い場合は...付き）
    """
    if not text:
        return ""
    return text[:max_length] + "..." if len(text) > max_length else text


def load_system_prompt() -> str:
    """システムプロンプトをファイルから読み込む

    Returns:
        str: システムプロンプトの内容
    """
    prompt_path = Path(__file__).parent / "prompts" / "system.txt"
    logger.info(f"システムプロンプトを読み込み: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8").strip()


class Sphene:
    """AIチャットボットの会話管理クラス"""

    def __init__(self, system_setting: str) -> None:
        """Spheneインスタンスを初期化

        Args:
            system_setting: システムプロンプト
        """
        self.system: ChatCompletionSystemMessageParam = {
            "role": "system",
            "content": system_setting,
        }
        self.input_list: List[ChatCompletionMessageParam] = [self.system]
        self.logs: List[ChatCompletion] = []
        # 会話の有効期限を設定（30分）
        self.last_interaction: Optional[datetime] = datetime.now()
        logger.info("Spheneインスタンスを初期化")

    def is_expired(self) -> bool:
        """会話が期限切れかどうかを判定

        Returns:
            bool: Trueの場合は期限切れ
        """
        if self.last_interaction is None:
            return False

        expiry_time = self.last_interaction + timedelta(
            minutes=MAX_CONVERSATION_AGE_MINUTES
        )
        return datetime.now() > expiry_time

    def update_interaction_time(self) -> None:
        """最終会話時間を更新"""
        self.last_interaction = datetime.now()

    def trim_conversation_history(self) -> None:
        """長くなった会話履歴を整理する"""
        # システムメッセージ + 往復N回分だけ保持
        max_messages = 1 + (MAX_CONVERSATION_TURNS * 2)

        if len(self.input_list) > max_messages:
            # システムメッセージを保持
            system_message = self.input_list[0]
            # 直近のメッセージだけを残す
            self.input_list = [system_message] + self.input_list[-(max_messages - 1) :]
            logger.info(
                f"会話履歴を整理しました（残りメッセージ数: {len(self.input_list)}）"
            )

    def input_message(self, input_text: Optional[str]) -> Optional[str]:
        """ユーザーからのメッセージを処理し、AIからの応答を返す

        Args:
            input_text: ユーザーからの入力テキスト

        Returns:
            Optional[str]: AIからの応答、エラー時はNone
        """
        if not isinstance(input_text, str) or not input_text.strip():
            logger.warning("受信したメッセージが無効です")
            return None

        self.update_interaction_time()

        # 型ガード後の変数を定義してからスライシング
        input_str: str = input_text
        preview = truncate_text(input_str)
        logger.info(f"ユーザーメッセージを受信: {preview}")

        # ユーザーメッセージを追加
        user_message: ChatCompletionUserMessageParam = {
            "role": "user",
            "content": input_text,
        }
        self.input_list.append(user_message)

        try:
            # OpenAI APIにリクエストを送信
            logger.info("OpenAI APIリクエスト送信")
            result = aiclient.chat.completions.create(
                model="gpt-4o-mini", messages=self.input_list
            )
            self.logs.append(result)

            # 応答を処理
            response_content = result.choices[0].message.content
            if response_content:
                logger.info(
                    f"OpenAI APIレスポンス受信: {truncate_text(response_content)}"
                )
            else:
                logger.warning("OpenAI APIからの応答が空です")
                return None

            # 応答をメッセージリストに追加
            assistant_message: ChatCompletionAssistantMessageParam = {
                "role": "assistant",
                "content": response_content,
            }
            self.input_list.append(assistant_message)

            # 会話履歴の管理
            self.trim_conversation_history()

            return response_content

        except Exception as e:
            logger.error(f"APIリクエスト中にエラーが発生: {str(e)}", exc_info=True)
            return None


# ユーザーごとの会話インスタンスを保持する辞書
user_conversations: DefaultDict[str, Sphene] = defaultdict(
    lambda: Sphene(system_setting=load_system_prompt())
)


class SpheneBot:
    """Discordボットのメインクラス"""

    def __init__(self) -> None:
        """ボットの初期化"""
        # Botの初期化
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        self.bot = commands.Bot(command_prefix="!", intents=intents)
        self.setup_events()
        self.setup_commands()

    def setup_events(self) -> None:
        """イベントハンドラの設定"""

        @self.bot.event
        async def on_ready() -> None:
            await self.bot.add_cog(commands.Cog(name="Management"))
            # コマンドグループを追加
            self.bot.tree.add_command(self.command_group)  # type: ignore
            await self.bot.tree.sync()

            if self.bot.user:
                logger.info(
                    f"Discordボット起動完了: {self.bot.user.name}#{self.bot.user.discriminator}"
                )
            else:
                logger.error("Discordボットのユーザー情報を取得できませんでした")

        @self.bot.event
        async def on_message(message: discord.Message) -> None:
            await self.handle_message(message)

        @self.bot.tree.error
        async def on_app_command_error(
            interaction: discord.Interaction, error: app_commands.AppCommandError
        ) -> None:
            await self.handle_command_error(interaction, error)

    def setup_commands(self) -> None:
        """スラッシュコマンドのセットアップ"""
        # コマンドグループ
        self.command_group = app_commands.Group(
            name=config.COMMAND_GROUP_NAME,
            description=f"{config.BOT_NAME}ボットのコマンド",
        )

        # チャンネル一覧コマンド
        @self.command_group.command(
            name="channels",
            description=f"{config.BOT_NAME}が使用可能なチャンネル一覧を表示します",
        )
        @app_commands.checks.has_permissions(administrator=True)
        async def list_channels(interaction: discord.Interaction) -> None:
            await self.cmd_list_channels(interaction)

        # リセットコマンド
        @self.command_group.command(
            name="reset", description="あなたとの会話履歴をリセットします"
        )
        async def reset_conversation(interaction: discord.Interaction) -> None:
            await self.cmd_reset_conversation(interaction)

    async def cmd_list_channels(self, interaction: discord.Interaction) -> None:
        """チャンネル一覧コマンドを処理する"""
        channel_info = f"👑 **{config.BOT_NAME}使用可能チャンネル一覧**:\n"

        # チャンネルリストの作成
        for channel_id in config.ALLOWED_CHANNEL_IDS:
            channel = self.bot.get_channel(channel_id)
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
        channel_info += "\n制限の設定方法: 環境変数`ALLOWED_CHANNEL_IDS`に使用可能なチャンネルIDをカンマ区切りで設定してね！"

        # メッセージ送信
        await interaction.response.send_message(channel_info)

    async def cmd_reset_conversation(self, interaction: discord.Interaction) -> None:
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

    async def is_bot_mentioned(self, message: discord.Message) -> Tuple[bool, str]:
        """メッセージがボットに対するものかどうかを判断し、質問内容を抽出する

        Args:
            message: Discordメッセージオブジェクト

        Returns:
            Tuple[bool, str]: (ボットに対するメッセージかどうか, 質問内容)
        """
        if message.content is None:
            return False, ""

        content: str = message.content
        user_id = str(message.author.id)

        # メンションされた場合
        if self.bot.user and self.bot.user in message.mentions:
            # bot.userがNoneではないことを確認済みなので、安全にidにアクセス可能
            bot_id = self.bot.user.id
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
                and self.bot.user is not None
                and message.reference.resolved.author.id == self.bot.user.id
            ):
                question = content  # リプライのメッセージ内容をそのまま質問として扱う
                preview = truncate_text(question)
                logger.info(
                    f"リプライ検出: ユーザーID {user_id}, チャンネルID {message.channel.id}, メッセージ: {preview}"
                )
                return True, question

        return False, ""

    async def process_conversation(
        self, message: discord.Message, question: str
    ) -> None:
        """ユーザーとの会話を処理する

        Args:
            message: Discordメッセージオブジェクト
            question: 質問内容
        """
        user_id = str(message.author.id)

        # 期限切れなら会話をリセット
        if user_conversations[user_id].is_expired():
            logger.info(f"ユーザーID {user_id} の会話が期限切れのためリセット")
            user_conversations[user_id] = Sphene(system_setting=load_system_prompt())

        # ユーザーの会話インスタンスを取得
        api = user_conversations[user_id]
        answer = api.input_message(question)

        if answer:
            logger.info(
                f"応答送信: ユーザーID {user_id}, 応答: {truncate_text(answer)}"
            )
            await message.channel.send(answer)
        else:
            await message.channel.send(
                "ごめん！応答の生成中にエラーが発生しちゃった...😢 もう一度試してみてね！"
            )

    async def handle_message(self, message: discord.Message) -> None:
        """メッセージ受信イベントの処理"""
        try:
            # 自分自身やボットのメッセージは無視
            if message.author == self.bot.user or message.author.bot:
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
            is_mentioned, question = await self.is_bot_mentioned(message)
            if is_mentioned:
                await self.process_conversation(message, question)

        except Exception as e:
            logger.error(f"エラー発生: {str(e)}", exc_info=True)
            await message.channel.send(f"ごめん！エラーが発生しちゃった...😢: {str(e)}")

    async def handle_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
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

    def run(self) -> None:
        """ボットを起動する"""
        logger.info("Discordボットの起動を開始")
        self.bot.run(config.DISCORD_TOKEN)


# メイン処理
if __name__ == "__main__":
    bot = SpheneBot()
    bot.run()
