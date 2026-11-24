"""キー単位のロック

同じキー（チャンネルIDやプロファイルキー）に対する処理だけを直列化し、
別キーの処理は並行に走らせたい場合に使う。
"""

import threading
from collections.abc import Hashable, Iterator
from contextlib import contextmanager
from typing import Generic, TypeVar

K = TypeVar("K", bound=Hashable)


class KeyedLock(Generic[K]):
    """キーごとに ``threading.Lock`` を払い出す

    ロックはキーごとに一度だけ生成し、以後は同じオブジェクトを返す。
    ロックは ``discard`` で明示的に消すまで保持する（キャッシュの追い出しと一緒に消す）。
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

    @contextmanager
    def hold(self, key: K) -> Iterator[None]:
        """キーのロックを取得して保持する（取得待ちの間に破棄されたロックは取り直す）

        ``get`` で受け取ったロックを待っている間に ``discard`` されると、そのロックを
        取っても新しく払い出されたロックとは直列化されない。取得後に現在のロックと
        同じかを確かめ、違えば取り直す。

        Args:
            key: ロック対象のキー

        Yields:
            None（ブロックの間ロックを保持する）
        """
        while True:
            lock = self.get(key)
            lock.acquire()
            with self._guard:
                current = self._locks.get(key)
            if current is lock:
                break
            lock.release()
        try:
            yield
        finally:
            lock.release()

    def discard(self, key: K) -> None:
        """キーのロックを破棄する（次回の ``get`` で新しいロックが生成される）

        使用中のロックを消すと同じキーに別のロックが払い出されて直列化が崩れるため、
        呼び出し側がそのキーのロックを保持している間に呼ぶこと。

        Args:
            key: 破棄するロックのキー
        """
        with self._guard:
            self._locks.pop(key, None)

    def __len__(self) -> int:
        with self._guard:
            return len(self._locks)
