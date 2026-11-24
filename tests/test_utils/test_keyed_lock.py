"""utils/keyed_lock.py のテスト"""

import threading

from utils.keyed_lock import KeyedLock


class TestHold:
    def test_holds_current_lock(self):
        locks: KeyedLock[str] = KeyedLock()
        with locks.hold("a"):
            assert locks.get("a").locked()
        assert not locks.get("a").locked()

    def test_reacquires_when_lock_discarded_while_waiting(self):
        """待っている間に discard されたら、新しく払い出されたロックを取り直す"""
        locks: KeyedLock[str] = KeyedLock()
        old = locks.get("a")
        old.acquire()
        held: list[threading.Lock] = []
        entered = threading.Event()

        def _worker() -> None:
            with locks.hold("a"):
                held.append(locks.get("a"))
                entered.set()

        thread = threading.Thread(target=_worker)
        thread.start()
        assert not entered.wait(0.1)  # old を待っている
        locks.discard("a")  # 保持者が破棄してから解放する（追い出しと同じ順序）
        old.release()
        thread.join(timeout=2)

        assert entered.is_set()
        assert held and held[0] is not old
        assert held[0] is locks.get("a")
