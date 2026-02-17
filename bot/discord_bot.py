import sys

import discord
from discord.ext import commands, tasks

import config
from ai.conversation import cleanup_expired_conversations, load_system_prompt
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

        # クリーンアップタスクの開始を準備
        @self.bot.listen("on_ready")
        async def start_cleanup_task() -> None:
            if not self._cleanup_task.is_running():
                self._cleanup_task.start()
                logger.info("クリーンアップタスクを開始しました")

    @tasks.loop(minutes=15)
    async def _cleanup_task(self) -> None:
        """期限切れの会話を定期的にクリーンアップする"""
        try:
            count = cleanup_expired_conversations()
            if count > 0:
                logger.info(f"バックグラウンドクリーンアップ完了: {count}件の会話を削除しました")
        except Exception as e:
            logger.error(f"クリーンアップタスクでエラーが発生しました: {str(e)}", exc_info=True)

        # チャンネルバッファのクリーンアップ
        if config.MEMORY_ENABLED:
            try:
                from memory.short_term import get_channel_buffer

                expired = get_channel_buffer().cleanup_expired()
                if expired > 0:
                    logger.info(
                        f"チャンネルバッファクリーンアップ: {expired}件削除"
                    )
            except Exception as e:
                logger.error(
                    f"チャンネルバッファクリーンアップでエラー: {str(e)}",
                    exc_info=True,
                )

        # 時間ベースの要約チェック
        if config.CHANNEL_CONTEXT_ENABLED and config.MEMORY_ENABLED:
            try:
                from memory.channel_context import get_channel_context_store
                from memory.short_term import get_channel_buffer
                from memory.summarizer import get_summarizer

                store = get_channel_context_store()
                buffer = get_channel_buffer()
                summarizer = get_summarizer()
                for channel_id, ctx in store._contexts.items():
                    if ctx.should_summarize_by_time():
                        recent = buffer.get_recent_messages(channel_id, limit=20)
                        summarizer.maybe_summarize(channel_id, recent)
            except Exception as e:
                logger.error(
                    f"時間ベース要約チェックでエラー: {str(e)}",
                    exc_info=True,
                )

    def run(self) -> None:
        """ボットを起動する"""
        logger.info("Discordボットの起動を開始")
        self.bot.run(config.DISCORD_TOKEN)
