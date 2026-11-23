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
    """ChannelContextStore.persist_all / dirty 管理のテスト"""

    def test_saves_only_dirty_contexts(self) -> None:
        """dirty なコンテキストだけを保存すること"""
        store = ChannelContextStore()
        dirty_ctx = ChannelContext(channel_id=1)
        dirty_ctx.increment_message_count()
        clean_ctx = ChannelContext(channel_id=2)
        store._contexts = {1: dirty_ctx, 2: clean_ctx}

        with patch.object(store, "save_context", return_value=True) as mock_save:
            failed = store.persist_all()

        assert failed == 0
        assert [c.args[0].channel_id for c in mock_save.call_args_list] == [1]

    def test_increment_marks_dirty(self) -> None:
        """メッセージカウンタの更新で dirty になること"""
        ctx = ChannelContext(channel_id=1)
        assert ctx.dirty is False
        ctx.increment_message_count()
        assert ctx.dirty is True

    def test_continues_after_failure_and_counts(self) -> None:
        """1チャンネルの失敗で他を止めず、失敗数を返してログに残すこと"""
        store = ChannelContextStore()
        ctx1, ctx2, ctx3 = (ChannelContext(channel_id=i, dirty=True) for i in (1, 2, 3))
        store._contexts = {1: ctx1, 2: ctx2, 3: ctx3}

        with patch.object(
            store, "save_context", side_effect=[RuntimeError("boom"), False, True]
        ) as mock_save, patch("memory.channel_context.logger") as mock_logger:
            failed = store.persist_all()

        assert mock_save.call_count == 3
        assert failed == 2
        mock_logger.error.assert_called_once()
        assert mock_logger.error.call_args.kwargs["exc_info"] is True
        mock_logger.warning.assert_called_once()

    def test_empty_store_is_noop(self) -> None:
        """キャッシュが空なら何も保存しないこと"""
        store = ChannelContextStore()
        with patch.object(store, "save_context") as mock_save:
            assert store.persist_all() == 0
        mock_save.assert_not_called()


class TestSaveContextResult:
    """save_context の戻り値と dirty フラグのテスト"""

    @pytest.mark.parametrize("storage_type", ["local", "firestore"])
    def test_success_clears_dirty(self, storage_type: str) -> None:
        """保存成功で True を返し dirty を落とすこと"""
        store = ChannelContextStore()
        ctx = ChannelContext(channel_id=1, dirty=True)
        with patch("memory.channel_context.config.STORAGE_TYPE", storage_type), patch.object(
            store, "_save_to_local", return_value=True
        ), patch.object(store, "_save_to_firestore", return_value=True):
            assert store.save_context(ctx) is True
        assert ctx.dirty is False

    def test_firestore_failure_returns_false_and_keeps_dirty(self) -> None:
        """Firestore への書き込みが失敗したら False を返し dirty のままにすること"""
        store = ChannelContextStore()
        ctx = ChannelContext(channel_id=1, dirty=True)
        mock_db = MagicMock()
        mock_db.collection.return_value.document.return_value.set.side_effect = RuntimeError("down")
        with patch("memory.channel_context.config.STORAGE_TYPE", "firestore"), patch(
            "utils.firestore_client.get_firestore_client", return_value=mock_db
        ):
            assert store.save_context(ctx) is False
        assert ctx.dirty is True

    def test_local_failure_returns_false_and_keeps_dirty(self) -> None:
        """ローカル書き込みが失敗したら False を返し dirty のままにすること"""
        store = ChannelContextStore()
        ctx = ChannelContext(channel_id=1, dirty=True)
        with patch("memory.channel_context.config.STORAGE_TYPE", "local"), patch(
            "utils.file_utils.atomic_write_json", side_effect=OSError("disk full")
        ):
            assert store.save_context(ctx) is False
        assert ctx.dirty is True

    def test_load_failed_context_is_not_saved(self) -> None:
        """読み込み失敗の一時コンテキストは保存せず False を返すこと"""
        store = ChannelContextStore()
        ctx = ChannelContext(channel_id=1, load_failed=True, dirty=True)
        with patch.object(store, "_save_to_local") as mock_local:
            assert store.save_context(ctx) is False
        mock_local.assert_not_called()
