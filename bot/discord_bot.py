import discord
from discord.ext import commands

import config
from bot.commands import setup_commands
from bot.events import setup_events
from log_utils.logger import logger


class SpheneBot:
    """Discordボットのメインクラス"""

    def __init__(self) -> None:
        """ボットの初期化"""
        # Botの初期化
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        self.bot = commands.Bot(command_prefix="!", intents=intents)

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
