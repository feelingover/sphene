"""キー単位のロック

同じキー（チャンネルIDやプロファイルキー）に対する処理だけを直列化し、
別キーの処理は並行に走らせたい場合に使う。
"""

import threading
from collections.abc import Hashable
from typing import Generic, TypeVar

K = TypeVar("K", bound=Hashable)


class KeyedLock(Generic[K]):
    """キーごとに ``threading.Lock`` を払い出す

    ロックはキーごとに一度だけ生成し、以後は同じオブジェクトを返す。
    ロックの寿命はこのオブジェクトと同じ（キー数はチャンネル・ユーザー数程度を想定）。
    """

    def __init__(self) -> None:
        self._locks: dict[K, threading.Lock] = {}
        self._guard = threading.Lock()

    def get(self, key: K) -> threading.Lock:
        """キーに対応するロックを返す（未生成なら生成する）

        Args:
            key: ロック対象のキー

        Returns:
            キーに対応するロック
        """
        with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
            return lock
