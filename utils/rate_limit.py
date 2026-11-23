"""スライディングウィンドウ方式のレート制限

イベントループ (単一スレッド) から呼び出す前提のため、ロックは持たない。
"""

import time
from collections import deque
from collections.abc import Callable, Hashable


class SlidingWindowRateLimiter:
    """キーごとに「直近 window_seconds 秒で max_events 回まで」を判定する

    Args:
        max_events: ウィンドウ内で許可するイベント数。0以下の場合は制限しない
        window_seconds: ウィンドウの長さ（秒）
        clock: 現在時刻を返す関数（テスト用に差し替え可能）
    """

    def __init__(
        self,
        max_events: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._clock = clock
        self._events: dict[Hashable, deque[float]] = {}
        self._last_sweep = clock()

    @property
    def enabled(self) -> bool:
        return self.max_events > 0

    def is_allowed(self, key: Hashable) -> bool:
        """キーが上限に達していないかを判定する（記録はしない）"""
        if not self.enabled:
            return True
        now = self._clock()
        self._sweep(now)
        events = self._events.get(key)
        if events is None:
            return True
        self._prune(events, now)
        return len(events) < self.max_events

    def record(self, key: Hashable) -> None:
        """キーのイベントを1件記録する"""
        if not self.enabled:
            return
        self._events.setdefault(key, deque()).append(self._clock())

    def __len__(self) -> int:
        return len(self._events)

    def _prune(self, events: deque[float], now: float) -> None:
        while events and now - events[0] >= self.window_seconds:
            events.popleft()

    def _sweep(self, now: float) -> None:
        """ウィンドウ1つ分ごとに、全イベントが期限切れになったキーを削除する"""
        if now - self._last_sweep < self.window_seconds:
            return
        self._last_sweep = now
        for key in list(self._events):
            events = self._events[key]
            self._prune(events, now)
            if not events:
                del self._events[key]
