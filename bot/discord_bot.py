import asyncio
import signal
import sys

import discord
from discord.ext import commands, tasks

import config
from ai.conversation import cleanup_expired_conversations, load_system_prompt
from bot.commands import setup_commands
from bot.events import setup_events
from log_utils.logger import logger
from utils.background_tasks import track_background_task
from xivapi.client import close_http_client


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
                f"システムプロンプト読み込み失敗のため起動を中止します: {str(e)}",
                exc_info=True,
            )
            sys.exit(1)

        # Botの初期化
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.reactions = True  # リアクションの検知に必要
        intents.messages = True  # 過去メッセージへのアクセス権を追加

        # LLM出力や翻訳結果経由で @everyone / ロールメンションが発火しないよう制限する
        allowed_mentions = discord.AllowedMentions(
            everyone=False, roles=False, users=True, replied_user=True
        )
        self.bot = commands.Bot(
            command_prefix="!",
            intents=intents,
            max_messages=10000,
            allowed_mentions=allowed_mentions,
        )

        # 終了処理の状態（SIGTERM の多重受信・永続化の二重実行を防ぐ）
        self._shutdown_requested = False
        self._memory_persisted = False

        # コマンドとイベントのセットアップ
        self._setup()

    def _setup(self) -> None:
        """コマンドとイベントのセットアップ"""
        # コマンドのセットアップ
        command_group = setup_commands(self.bot)

        # イベントのセットアップ
        setup_events(self.bot, command_group)

        # ログイン時（イベントループ起動後）にシグナルハンドラを登録する。
        # setup_events が設定したフック（スラッシュコマンドの登録・同期）を
        # 上書きせず、その前に SIGTERM ハンドラの登録を挟む
        self._events_setup_hook = self.bot.setup_hook
        self.bot.setup_hook = self._setup_hook  # type: ignore[method-assign]

        # クリーンアップタスクの開始を準備
        @self.bot.listen("on_ready")
        async def start_cleanup_task() -> None:
            if not self._cleanup_task.is_running():
                self._cleanup_task.start()
                logger.info("クリーンアップタスクを開始しました")
            self._start_proactive_task()

    def _start_proactive_task(self) -> None:
        """自発会話のタイマーループを開始する（PROACTIVE_ENABLED=false なら何もしない）"""
        if not config.PROACTIVE_ENABLED or self._proactive_task.is_running():
            return
        self._proactive_task.change_interval(minutes=config.PROACTIVE_CHECK_INTERVAL_MINUTES)
        self._proactive_task.start()
        logger.info(
            f"自発会話のタイマーループを開始しました: "
            f"間隔={config.PROACTIVE_CHECK_INTERVAL_MINUTES}分"
        )

    @tasks.loop(minutes=10)
    async def _proactive_task(self) -> None:
        """担当チャンネルで自発会話の条件を判定し、満たせば送信する（間隔は開始時に設定）"""
        from memory.proactive import run_proactive_check

        await run_proactive_check(self.bot)

    @tasks.loop(minutes=15)
    async def _cleanup_task(self) -> None:
        """期限切れの会話を定期的にクリーンアップし、記憶系の定期処理を行う"""
        _cleanup_conversations()
        _cleanup_channel_buffer()

        if not config.LIVING_MEMORY_ENABLED:
            return

        # ユーザープロファイルの永続化
        await _persist_user_profiles()
        # 時間ベースの要約チェック
        _check_time_based_summaries()
        # 沈黙ベースの反省会チェック + ファクトストアの永続化
        await _run_reflection_and_persist_facts()
        # 記憶ストアのキャッシュ上限超過分を追い出す（永続化・クリーンアップの後に行う）
        await _prune_memory_caches()

    async def _setup_hook(self) -> None:
        """discord.py の setup_hook: SIGTERM ハンドラを登録し、元のフックを実行する

        コマンド同期が失敗しても SIGTERM で永続化できるよう、ハンドラ登録を先に行う。
        """
        self._install_sigterm_handler(asyncio.get_running_loop())
        await self._events_setup_hook()

    def _install_sigterm_handler(self, loop: asyncio.AbstractEventLoop) -> None:
        """SIGTERM で graceful shutdown するためのハンドラを登録する

        Python 既定の SIGTERM は即時終了で後始末が一切走らないため、
        イベントループのシグナルハンドラで受けて終了処理タスクに変換する。
        """
        try:
            loop.add_signal_handler(signal.SIGTERM, self._request_shutdown)
        except (NotImplementedError, RuntimeError, ValueError):
            # Windows やメインスレッド外のループでは登録できない
            logger.warning("SIGTERMハンドラを登録できませんでした", exc_info=True)

    def _request_shutdown(self) -> None:
        """SIGTERM 受信時に終了処理タスクを起動する（2回目以降は無視）"""
        if self._shutdown_requested:
            logger.info("SIGTERMを再受信しましたが、終了処理が進行中のため無視します")
            return
        self._shutdown_requested = True
        logger.info("SIGTERMを受信しました。終了処理を開始します")
        track_background_task(
            asyncio.create_task(self._graceful_shutdown(), name="graceful_shutdown")
        )

    async def _graceful_shutdown(self) -> None:
        """記憶を永続化してから Discord との接続を閉じる

        ``asyncio.run`` は終了時に既定 executor のスレッド終了を最大300秒待つため、
        LLM 呼び出し（``asyncio.to_thread``）が実行中だと ``run`` の ``finally`` に
        着く前に猶予期間（k8s 既定30秒）を超えて SIGKILL されうる。そのため
        ループ内で先に永続化する。``to_thread`` を使わないのは、既定 executor が
        実行中の LLM 呼び出しで埋まっていると永続化がその後ろに並んでしまうため。
        """
        if self._proactive_task.is_running():
            self._proactive_task.cancel()
        self._persist_memory_once()
        await self.bot.close()

    def _persist_memory_once(self) -> None:
        """終了時の永続化を1回だけ行う（SIGTERM 経路と finally の二重実行を防ぐ）"""
        if self._memory_persisted:
            return
        self._memory_persisted = True
        _persist_memory_on_shutdown()

    def run(self) -> None:
        """ボットを起動する"""
        logger.info("Discordボットの起動を開始")
        # discord.py 独自のログハンドラは登録せず、アプリのルートロガー設定
        # （LOG_FORMAT / LOG_LEVEL）に一本化する。二重出力を防ぐため
        try:
            self.bot.run(config.DISCORD_TOKEN, log_handler=None)
        finally:
            # ループ終了でシグナルハンドラは外れ SIG_DFL に戻るため、
            # フォールバックの永続化中に SIGTERM で即死しないよう無視する
            _ignore_sigterm()
            # SIGTERM 以外の終了経路（SIGINT・例外など）向けのフォールバック
            self._persist_memory_once()
            close_http_client()


def _cleanup_conversations() -> None:
    """期限切れの会話履歴を削除する（失敗してもログのみで継続する）"""
    try:
        count = cleanup_expired_conversations()
        if count > 0:
            logger.info(f"バックグラウンドクリーンアップ完了: {count}件の会話を削除しました")
    except Exception as e:
        logger.error(f"クリーンアップタスクでエラーが発生しました: {str(e)}", exc_info=True)


def _cleanup_channel_buffer() -> None:
    """チャンネルバッファの期限切れメッセージを削除する"""
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


async def _persist_user_profiles() -> None:
    """ユーザープロファイルを永続化する"""
    try:
        from memory.user_profile import get_user_profile_store

        await asyncio.to_thread(get_user_profile_store().persist_all)
        logger.debug("ユーザープロファイルを永続化しました")
    except Exception as e:
        logger.error(f"ユーザープロファイル永続化エラー: {str(e)}", exc_info=True)


def _check_time_based_summaries() -> None:
    """時間経過で要約が必要になったチャンネルの要約を起動する"""
    try:
        from memory.channel_context import get_channel_context_store
        from memory.short_term import get_channel_buffer
        from memory.summarizer import get_summarizer

        store = get_channel_context_store()
        buffer = get_channel_buffer()
        summarizer = get_summarizer()
        for channel_id, ctx in store.get_all_contexts().items():
            if ctx.should_summarize_by_time():
                recent = buffer.get_recent_messages(channel_id, limit=20)
                summarizer.maybe_summarize(channel_id, recent)
    except Exception as e:
        logger.error(
            f"時間ベース要約チェックでエラー: {str(e)}",
            exc_info=True,
        )


async def _run_reflection_and_persist_facts() -> None:
    """沈黙ベースの反省会チェックを行い、ファクトストアを永続化・忘却クリーンアップする"""
    try:
        from memory.fact_store import get_fact_store

        _trigger_lull_reflections()

        await asyncio.to_thread(get_fact_store().persist_all)
        logger.debug("ファクトストアを永続化しました")

        removed = await asyncio.to_thread(
            get_fact_store().cleanup_low_relevance_facts
        )
        if removed:
            total = sum(removed.values())
            logger.info(f"ファクト忘却クリーンアップ完了: 合計{total}件削除 {removed}")
    except Exception as e:
        logger.error(
            f"反省会チェック/ファクトストア永続化でエラー: {str(e)}", exc_info=True
        )


def _trigger_lull_reflections() -> None:
    """一定時間沈黙しているチャンネルについて反省会（ファクト抽出）を起動する

    Raises:
        Exception: バッファ・反省会エンジンの取得や呼び出しで発生した例外。
            呼び出し元の ``_run_reflection_and_persist_facts`` でログに残す。
    """
    from datetime import datetime, timezone

    from memory.reflection import get_reflection_engine
    from memory.short_term import get_channel_buffer

    buffer = get_channel_buffer()
    engine = get_reflection_engine()
    for channel_id in buffer.get_active_channel_ids():
        last_time = buffer.get_last_message_time(channel_id)
        if last_time is None:
            continue
        silence_minutes = (
            datetime.now(timezone.utc) - last_time
        ).total_seconds() / 60
        if silence_minutes >= config.REFLECTION_LULL_MINUTES:
            pending = buffer.get_messages_since_reflection(channel_id)
            engine.maybe_reflect(channel_id, pending)


async def _prune_memory_caches() -> None:
    """記憶ストアのメモリキャッシュから、上限を超えた古いエントリを追い出す

    未保存・保存中のエントリは各ストアが追い出し対象から外す。
    1つのストアの失敗で他のストアの追い出しを止めない。
    """
    from memory.channel_context import get_channel_context_store
    from memory.fact_store import get_fact_store
    from memory.user_profile import get_user_profile_store

    targets = [
        ("ユーザープロファイル", lambda: get_user_profile_store().prune()),
        ("ファクトストア", lambda: get_fact_store().prune()),
        ("チャンネルコンテキスト", lambda: get_channel_context_store().prune()),
    ]
    for label, prune in targets:
        try:
            evicted = await asyncio.to_thread(prune)
            if evicted:
                logger.info(f"キャッシュ追い出し: {label} {evicted}件")
        except Exception as e:
            logger.error(f"キャッシュ追い出しでエラー: {label}, error={str(e)}", exc_info=True)


def _ignore_sigterm() -> None:
    """プロセス終了直前の SIGTERM を無視する（メインスレッド外では何もしない）"""
    try:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    except ValueError:
        logger.debug("メインスレッド外のため SIGTERM を無視に設定できませんでした")


def _persist_memory_on_shutdown() -> None:
    """終了時に未保存の記憶（プロファイル・ファクト・チャンネルコンテキスト）を永続化する

    定期タスク（15分ごと）の間に溜まった dirty な状態を再起動で失わないために呼ぶ。
    1つのストアの失敗で他のストアの保存を止めない。個々の書き込み失敗は
    各ストアがログに残す。
    """
    if not config.LIVING_MEMORY_ENABLED:
        return

    from memory.channel_context import get_channel_context_store
    from memory.fact_store import get_fact_store
    from memory.user_profile import get_user_profile_store

    targets = [
        ("ユーザープロファイル", lambda: get_user_profile_store().persist_all()),
        ("ファクトストア", lambda: get_fact_store().persist_all()),
        ("チャンネルコンテキスト", lambda: get_channel_context_store().persist_all()),
    ]
    for label, persist in targets:
        try:
            persist()
            logger.info(f"終了時の永続化処理を実行しました: {label}")
        except Exception as e:
            logger.error(f"終了時の永続化に失敗しました: {label}, error={str(e)}", exc_info=True)
