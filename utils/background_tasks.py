"""バックグラウンドタスクの参照保持

``asyncio.create_task`` の戻り値はイベントループから弱参照でしか保持されないため、
参照を捨てると実行途中のタスクが GC されて黙って消えることがある。
ここで強参照を保持し、完了時に外すとともに、タスク内の例外をログに残す。
"""

import asyncio

from log_utils.logger import logger

_background_tasks: set[asyncio.Task] = set()


def track_background_task(task: asyncio.Task) -> asyncio.Task:
    """バックグラウンドタスクを完了まで強参照で保持する

    Args:
        task: ``asyncio.create_task`` などで生成したタスク

    Returns:
        渡したタスク（呼び出し側でそのまま使えるように返す）
    """
    _background_tasks.add(task)
    task.add_done_callback(_on_task_done)
    return task


def get_background_task_count() -> int:
    """保持中のバックグラウンドタスク数を返す"""
    return len(_background_tasks)


def _on_task_done(task: asyncio.Task) -> None:
    """完了したタスクを集合から外し、未処理の例外があればログに残す"""
    _background_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(
            f"バックグラウンドタスクで例外が発生しました: name={task.get_name()}",
            exc_info=exc,
        )
