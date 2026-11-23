"""utils/background_tasks.py のテスト（issue #132）"""

import asyncio
import gc
from unittest.mock import patch

import pytest

from utils import background_tasks
from utils.background_tasks import get_background_task_count, track_background_task


@pytest.fixture(autouse=True)
def _clear_tasks():  # type: ignore[no-untyped-def]
    background_tasks._background_tasks.clear()
    yield
    background_tasks._background_tasks.clear()


class TestTrackBackgroundTask:
    """track_background_task のテスト"""

    @pytest.mark.asyncio
    async def test_holds_reference_until_done(self) -> None:
        """完了までタスクを保持し、完了後に集合から外すこと"""
        event = asyncio.Event()

        async def worker() -> None:
            await event.wait()

        task = track_background_task(asyncio.create_task(worker()))
        assert get_background_task_count() == 1
        assert task in background_tasks._background_tasks

        event.set()
        await task
        await asyncio.sleep(0)  # done callback の実行を待つ
        assert get_background_task_count() == 0

    @pytest.mark.asyncio
    async def test_returns_same_task(self) -> None:
        """渡したタスクをそのまま返すこと"""

        async def worker() -> int:
            return 42

        task = asyncio.create_task(worker())
        assert track_background_task(task) is task
        assert await task == 42

    @pytest.mark.asyncio
    async def test_task_survives_gc_without_caller_reference(self) -> None:
        """呼び出し側が参照を捨てても GC されず最後まで実行されること"""
        done = asyncio.Event()

        async def worker() -> None:
            await asyncio.sleep(0)
            gc.collect()
            await asyncio.sleep(0)
            done.set()

        track_background_task(asyncio.create_task(worker()))
        gc.collect()
        await asyncio.wait_for(done.wait(), timeout=1)

    @pytest.mark.asyncio
    async def test_logs_exception_with_exc_info(self) -> None:
        """タスク内の例外をタスク名・例外情報つきでログに残すこと"""
        error = RuntimeError("boom")

        async def worker() -> None:
            raise error

        with patch("utils.background_tasks.logger") as mock_logger:
            task = track_background_task(asyncio.create_task(worker(), name="failing"))
            with pytest.raises(RuntimeError):
                await task
            await asyncio.sleep(0)

        mock_logger.error.assert_called_once()
        args, kwargs = mock_logger.error.call_args
        assert "failing" in args[0]
        assert kwargs["exc_info"] is error
        assert get_background_task_count() == 0

    @pytest.mark.asyncio
    async def test_cancelled_task_is_not_logged(self) -> None:
        """キャンセルされたタスクはエラーログを出さずに外すこと"""

        async def worker() -> None:
            await asyncio.sleep(10)

        with patch("utils.background_tasks.logger") as mock_logger:
            task = track_background_task(asyncio.create_task(worker()))
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await asyncio.sleep(0)

        mock_logger.error.assert_not_called()
        assert get_background_task_count() == 0

    @pytest.mark.asyncio
    async def test_successful_task_is_not_logged(self) -> None:
        """正常終了したタスクはエラーログを出さないこと"""

        async def worker() -> None:
            return None

        with patch("utils.background_tasks.logger") as mock_logger:
            await track_background_task(asyncio.create_task(worker()))
            await asyncio.sleep(0)

        mock_logger.error.assert_not_called()
