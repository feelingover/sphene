"""終了時の記憶永続化と SIGTERM ハンドリングのテスト（issue #132）"""

import signal
from unittest.mock import MagicMock, patch

import pytest

from bot.discord_bot import (
    SpheneBot,
    _install_sigterm_handler,
    _persist_memory_on_shutdown,
    _raise_keyboard_interrupt,
)


def _patch_stores(profile: MagicMock, facts: MagicMock, contexts: MagicMock):  # type: ignore[no-untyped-def]
    return (
        patch("memory.user_profile.get_user_profile_store", return_value=profile),
        patch("memory.fact_store.get_fact_store", return_value=facts),
        patch("memory.channel_context.get_channel_context_store", return_value=contexts),
    )


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
    """SpheneBot.run の終了処理のテスト"""

    def test_persists_and_closes_even_when_run_raises(self) -> None:
        """bot.run が例外で抜けても永続化と HTTP クライアントのクローズを行うこと"""
        with patch("bot.discord_bot.commands.Bot") as mock_bot_cls, patch.object(
            SpheneBot, "_setup"
        ), patch("bot.discord_bot.load_system_prompt"), patch(
            "bot.discord_bot._install_sigterm_handler"
        ) as mock_install, patch(
            "bot.discord_bot._persist_memory_on_shutdown"
        ) as mock_persist, patch("bot.discord_bot.close_http_client") as mock_close:
            mock_bot_cls.return_value.run.side_effect = RuntimeError("crash")
            bot = SpheneBot()
            with pytest.raises(RuntimeError):
                bot.run()

        mock_install.assert_called_once()
        mock_persist.assert_called_once()
        mock_close.assert_called_once()

    def test_persist_runs_before_close_http_client(self) -> None:
        """永続化が HTTP クライアントのクローズより先に行われること"""
        order: list[str] = []
        with patch("bot.discord_bot.commands.Bot"), patch.object(
            SpheneBot, "_setup"
        ), patch("bot.discord_bot.load_system_prompt"), patch(
            "bot.discord_bot._install_sigterm_handler"
        ), patch(
            "bot.discord_bot._persist_memory_on_shutdown",
            side_effect=lambda: order.append("persist"),
        ), patch(
            "bot.discord_bot.close_http_client",
            side_effect=lambda: order.append("close"),
        ):
            SpheneBot().run()

        assert order == ["persist", "close"]


class TestSigtermHandler:
    """SIGTERM ハンドラのテスト"""

    def test_installs_handler_for_sigterm(self) -> None:
        """SIGTERM に KeyboardInterrupt 変換ハンドラを登録すること"""
        with patch("bot.discord_bot.signal.signal") as mock_signal:
            _install_sigterm_handler()
        mock_signal.assert_called_once_with(signal.SIGTERM, _raise_keyboard_interrupt)

    def test_handler_raises_keyboard_interrupt(self) -> None:
        """ハンドラが KeyboardInterrupt を送出すること（discord.py の終了経路に乗せる）"""
        with pytest.raises(KeyboardInterrupt):
            _raise_keyboard_interrupt(signal.SIGTERM, None)

    def test_install_outside_main_thread_does_not_raise(self) -> None:
        """メインスレッド外で登録に失敗しても例外を伝播しないこと"""
        with patch(
            "bot.discord_bot.signal.signal", side_effect=ValueError("not main thread")
        ), patch("bot.discord_bot.logger") as mock_logger:
            _install_sigterm_handler()
        mock_logger.warning.assert_called_once()
