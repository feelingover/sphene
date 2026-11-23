"""終了時の記憶永続化と SIGTERM ハンドリングのテスト（issue #132）"""

import asyncio
import signal
import threading
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.discord_bot import SpheneBot, _persist_memory_on_shutdown


def _patch_stores(profile: MagicMock, facts: MagicMock, contexts: MagicMock):  # type: ignore[no-untyped-def]
    return (
        patch("memory.user_profile.get_user_profile_store", return_value=profile),
        patch("memory.fact_store.get_fact_store", return_value=facts),
        patch("memory.channel_context.get_channel_context_store", return_value=contexts),
    )


@pytest.fixture
def sphene_bot() -> Iterator[SpheneBot]:
    """discord.py の Bot をモックした SpheneBot（_setup は実行する）"""
    with patch("bot.discord_bot.commands.Bot") as mock_bot_cls, patch(
        "bot.discord_bot.load_system_prompt"
    ), patch("bot.discord_bot.setup_commands"), patch("bot.discord_bot.setup_events"):
        mock_bot_cls.return_value.close = AsyncMock()
        yield SpheneBot()


class TestPersistMemoryOnShutdown:
    """_persist_memory_on_shutdown のテスト"""

    def test_persists_all_stores(self) -> None:
        """プロファイル・ファクト・チャンネルコンテキストの全ストアを永続化すること"""
        profile, facts, contexts = MagicMock(), MagicMock(), MagicMock()
        p1, p2, p3 = _patch_stores(profile, facts, contexts)
        with patch("bot.discord_bot.config.LIVING_MEMORY_ENABLED", True), p1, p2, p3:
            _persist_memory_on_shutdown()

        profile.persist_all.assert_called_once()
        facts.persist_all.assert_called_once()
        contexts.persist_all.assert_called_once()

    def test_continues_when_one_store_fails(self) -> None:
        """1つのストアが失敗しても残りのストアを永続化し、エラーをログに残すこと"""
        profile, facts, contexts = MagicMock(), MagicMock(), MagicMock()
        profile.persist_all.side_effect = RuntimeError("boom")
        p1, p2, p3 = _patch_stores(profile, facts, contexts)
        with patch("bot.discord_bot.config.LIVING_MEMORY_ENABLED", True), p1, p2, p3, patch(
            "bot.discord_bot.logger"
        ) as mock_logger:
            _persist_memory_on_shutdown()

        facts.persist_all.assert_called_once()
        contexts.persist_all.assert_called_once()
        mock_logger.error.assert_called_once()
        assert mock_logger.error.call_args.kwargs["exc_info"] is True

    def test_skips_when_living_memory_disabled(self) -> None:
        """LIVING_MEMORY_ENABLED=False のときは何もしないこと"""
        profile, facts, contexts = MagicMock(), MagicMock(), MagicMock()
        p1, p2, p3 = _patch_stores(profile, facts, contexts)
        with patch("bot.discord_bot.config.LIVING_MEMORY_ENABLED", False), p1, p2, p3:
            _persist_memory_on_shutdown()

        profile.persist_all.assert_not_called()
        facts.persist_all.assert_not_called()
        contexts.persist_all.assert_not_called()


class TestRunShutdown:
    """SpheneBot.run の終了処理（フォールバック経路）のテスト"""

    def test_persists_and_closes_even_when_run_raises(self, sphene_bot: SpheneBot) -> None:
        """bot.run が例外で抜けても永続化と HTTP クライアントのクローズを行うこと"""
        sphene_bot.bot.run.side_effect = RuntimeError("crash")  # type: ignore[attr-defined]
        with patch("bot.discord_bot._persist_memory_on_shutdown") as mock_persist, patch(
            "bot.discord_bot.close_http_client"
        ) as mock_close:
            with pytest.raises(RuntimeError):
                sphene_bot.run()

        mock_persist.assert_called_once()
        mock_close.assert_called_once()

    def test_persist_runs_before_close_http_client(self, sphene_bot: SpheneBot) -> None:
        """永続化が HTTP クライアントのクローズより先に行われること"""
        order: list[str] = []
        with patch(
            "bot.discord_bot._persist_memory_on_shutdown",
            side_effect=lambda: order.append("persist"),
        ), patch(
            "bot.discord_bot.close_http_client",
            side_effect=lambda: order.append("close"),
        ):
            sphene_bot.run()

        assert order == ["persist", "close"]

    def test_finally_skips_when_already_persisted(self, sphene_bot: SpheneBot) -> None:
        """SIGTERM 経路で永続化済みなら finally で二重に永続化しないこと"""
        sphene_bot._memory_persisted = True
        with patch("bot.discord_bot._persist_memory_on_shutdown") as mock_persist, patch(
            "bot.discord_bot.close_http_client"
        ):
            sphene_bot.run()
        mock_persist.assert_not_called()


class TestSigtermHandler:
    """SIGTERM ハンドラ（イベントループ上）のテスト"""

    def test_setup_hook_is_registered(self, sphene_bot: SpheneBot) -> None:
        """discord.py の setup_hook に SpheneBot._setup_hook が設定されること"""
        assert sphene_bot.bot.setup_hook == sphene_bot._setup_hook

    @pytest.mark.asyncio
    async def test_setup_hook_installs_loop_signal_handler(self, sphene_bot: SpheneBot) -> None:
        """setup_hook でイベントループに SIGTERM ハンドラを登録すること"""
        loop = asyncio.get_running_loop()
        with patch.object(loop, "add_signal_handler") as mock_add:
            await sphene_bot._setup_hook()
        mock_add.assert_called_once_with(signal.SIGTERM, sphene_bot._request_shutdown)

    def test_install_failure_does_not_raise(self, sphene_bot: SpheneBot) -> None:
        """シグナルハンドラを登録できない環境でも例外を伝播しないこと"""
        loop = MagicMock()
        loop.add_signal_handler.side_effect = NotImplementedError
        with patch("bot.discord_bot.logger") as mock_logger:
            sphene_bot._install_sigterm_handler(loop)
        mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_request_shutdown_persists_then_closes(self, sphene_bot: SpheneBot) -> None:
        """SIGTERM で永続化してから Discord との接続を閉じること"""
        order: list[str] = []
        sphene_bot.bot.close = AsyncMock(side_effect=lambda: order.append("close"))  # type: ignore[method-assign]
        with patch(
            "bot.discord_bot._persist_memory_on_shutdown",
            side_effect=lambda: order.append("persist"),
        ):
            sphene_bot._request_shutdown()
            await asyncio.sleep(0)
            await asyncio.sleep(0)

        assert order == ["persist", "close"]
        assert sphene_bot._memory_persisted is True

    @pytest.mark.asyncio
    async def test_second_sigterm_is_ignored(self, sphene_bot: SpheneBot) -> None:
        """2回目の SIGTERM では終了処理を重ねて起動しないこと"""
        with patch("bot.discord_bot._persist_memory_on_shutdown") as mock_persist:
            sphene_bot._request_shutdown()
            sphene_bot._request_shutdown()
            await asyncio.sleep(0)
            await asyncio.sleep(0)

        mock_persist.assert_called_once()
        sphene_bot.bot.close.assert_awaited_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_persist_does_not_wait_for_busy_executor(self, sphene_bot: SpheneBot) -> None:
        """実行中の to_thread（LLM 呼び出し）の完了を待たずに永続化すること

        asyncio.run は既定 executor のスレッド終了を待つため、永続化はそれより前に
        ループ内で済ませる必要がある（issue #132 レビュー指摘）。
        """
        release = threading.Event()
        started = threading.Event()

        def slow_llm_call() -> None:
            started.set()
            release.wait(timeout=5)

        in_flight = asyncio.create_task(asyncio.to_thread(slow_llm_call))
        await asyncio.to_thread(started.wait, 5)
        try:
            with patch("bot.discord_bot._persist_memory_on_shutdown") as mock_persist:
                await asyncio.wait_for(sphene_bot._graceful_shutdown(), timeout=1)
            mock_persist.assert_called_once()
            sphene_bot.bot.close.assert_awaited_once()  # type: ignore[attr-defined]
            assert not in_flight.done()
        finally:
            release.set()
            await in_flight
