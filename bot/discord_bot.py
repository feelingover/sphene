import sys

import discord
from discord.ext import commands

import config
from ai.conversation import load_system_prompt
from bot.commands import setup_commands
from bot.events import setup_events
from log_utils.logger import logger


class SpheneBot:
    """Discordボットのメインクラス"""

    def __init__(self) -> None:
        """ボットの初期化"""
        # 起動前にプロンプトファイルの読み込みを実行
        try:
            logger.info("起動時のシステムプロンプト読み込みを開始")
            load_system_prompt(fail_on_error=True)
            logger.info("システムプロンプトの読み込みに成功しました")
        except Exception as e:
            logger.critical(
                f"システムプロンプト読み込み失敗のため起動を中止します: {str(e)}"
            )
            sys.exit(1)

        # Botの初期化
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.reactions = True  # リアクションの検知に必要
        intents.messages = True  # 過去メッセージへのアクセス権を追加

        self.bot = commands.Bot(command_prefix="!", intents=intents, max_messages=10000)

        # コマンドとイベントのセットアップ
        self._setup()

    def _setup(self) -> None:
        """コマンドとイベントのセットアップ"""
        # コマンドのセットアップ
        command_group = setup_commands(self.bot)

        # イベントのセットアップ
        setup_events(self.bot, command_group)

    def run(self) -> None:
        """ボットを起動する"""
        logger.info("Discordボットの起動を開始")
        self.bot.run(config.DISCORD_TOKEN)
