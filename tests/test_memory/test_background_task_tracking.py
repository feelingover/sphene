"""要約・反省会のバックグラウンドタスク保持と ChannelContextStore.persist_all のテスト（issue #132）"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from memory.channel_context import ChannelContext, ChannelContextStore
from memory.reflection import ReflectionEngine
from memory.short_term import ChannelMessage
from memory.summarizer import Summarizer


def _make_message() -> ChannelMessage:
    return ChannelMessage(
        message_id=1,
        channel_id=100,
        author_id=1,
        author_name="TestUser",
        content="テスト",
        timestamp=datetime.now(timezone.utc),
        is_bot=False,
        guild_id=1,
    )


class TestTaskTracking:
    """要約・反省会タスクが track_background_task に渡されること"""

    @pytest.mark.asyncio
    async def test_summarizer_tracks_task(self) -> None:
        """要約タスクが参照保持され、タスク名が付くこと"""
        ctx = MagicMock()
        ctx.should_summarize.return_value = True
        ctx.message_count_since_update = 20
        store = MagicMock()
        store.get_context.return_value = ctx
        summarizer = Summarizer()

        with patch("memory.summarizer.get_channel_context_store", return_value=store), patch.object(
            summarizer, "_run_summarize", new=MagicMock(return_value=_noop())
        ), patch("memory.summarizer.track_background_task") as mock_track:
            summarizer.maybe_summarize(100, [_make_message()])
            task = mock_track.call_args.args[0]
            await task

        mock_track.assert_called_once()
        assert task.get_name() == "summarize_100"

    @pytest.mark.asyncio
    async def test_reflection_tracks_task(self) -> None:
        """反省会タスクが参照保持され、タスク名が付くこと"""
        engine = ReflectionEngine()
        messages = [_make_message() for _ in range(15)]

        with patch("config.REFLECTION_MIN_MESSAGES", 10), patch.object(
            engine, "_run_reflect", new=MagicMock(return_value=_noop())
        ), patch("memory.reflection.track_background_task") as mock_track:
            engine.maybe_reflect(100, messages)
            task = mock_track.call_args.args[0]
            await task

        mock_track.assert_called_once()
        assert task.get_name() == "reflect_100"


async def _noop() -> None:
    return None


class TestChannelContextPersistAll:
    """ChannelContextStore.persist_all のテスト"""

    def test_saves_all_cached_contexts(self) -> None:
        """キャッシュ済みの全コンテキストを保存すること"""
        store = ChannelContextStore()
        ctx1 = ChannelContext(channel_id=1, message_count_since_update=3)
        ctx2 = ChannelContext(channel_id=2)
        store._contexts = {1: ctx1, 2: ctx2}

        with patch.object(store, "save_context") as mock_save:
            store.persist_all()

        saved = {call.args[0].channel_id for call in mock_save.call_args_list}
        assert saved == {1, 2}

    def test_continues_after_failure(self) -> None:
        """1チャンネルの保存失敗で他チャンネルの保存を止めず、ログに残すこと"""
        store = ChannelContextStore()
        store._contexts = {
            1: ChannelContext(channel_id=1),
            2: ChannelContext(channel_id=2),
        }

        with patch.object(
            store, "save_context", side_effect=[RuntimeError("boom"), None]
        ) as mock_save, patch("memory.channel_context.logger") as mock_logger:
            store.persist_all()

        assert mock_save.call_count == 2
        mock_logger.error.assert_called_once()
        assert mock_logger.error.call_args.kwargs["exc_info"] is True

    def test_empty_store_is_noop(self) -> None:
        """キャッシュが空なら何も保存しないこと"""
        store = ChannelContextStore()
        with patch.object(store, "save_context") as mock_save:
            store.persist_all()
        mock_save.assert_not_called()
