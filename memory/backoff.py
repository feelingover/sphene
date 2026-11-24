"""LLM呼び出し失敗時の指数バックオフ

反省会・要約などのバックグラウンドLLM処理が失敗し続けたときに、
メッセージ受信のたびに再実行されてAPIを叩き続けるのを防ぐ。
イベントループ (単一スレッド) から呼び出す前提のため、ロックは持たない。

再試行可能になってから max_seconds 以上経っても再試行されなかったキーの記録は
``record_failure`` のついでに捨てる（キーが増え続けてメモリを使い続けないようにするため）。
捨てたキーの次の失敗は1回目として数え直す。長い間再試行されなかった失敗は
一時的な障害だった可能性が高いため、待機時間を base_seconds からやり直してよい。
"""

import time
from collections.abc import Callable, Hashable
from dataclasses import dataclass

import config


@dataclass
class _FailureState:
    count: int
    retry_at: float


class FailureBackoff:
    """キーごとの連続失敗回数と、次に再試行してよい時刻を管理する

    n 回連続で失敗した後の待機時間は base_seconds * 2^(n-1) (上限 max_seconds)。

    Args:
        base_seconds: 1回目の失敗後の待機秒数
        max_seconds: 待機秒数の上限
        clock: 現在時刻を返す関数（テスト用に差し替え可能）
    """

    def __init__(
        self,
        base_seconds: float,
        max_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_seconds = base_seconds
        self.max_seconds = max_seconds
        self._clock = clock
        self._states: dict[Hashable, _FailureState] = {}
        self._last_prune = clock()

    def is_blocked(self, key: Hashable) -> bool:
        """バックオフ期間中で、まだ再試行すべきでないかを判定する"""
        state = self._states.get(key)
        return state is not None and self._clock() < state.retry_at

    def record_failure(self, key: Hashable) -> int:
        """失敗を記録してバックオフを延長する

        Returns:
            連続失敗回数
        """
        self._maybe_prune()
        state = self._states.get(key)
        count = state.count + 1 if state else 1
        delay = min(self.base_seconds * 2 ** (count - 1), self.max_seconds)
        self._states[key] = _FailureState(count=count, retry_at=self._clock() + delay)
        return count

    def prune(self) -> int:
        """再試行可能になってから max_seconds 以上経ったキーの記録を捨てる

        捨てたキーは失敗記録なし（failure_count == 0）として扱われる。

        Returns:
            捨てたキー数
        """
        now = self._clock()
        self._last_prune = now
        stale = [
            key for key, state in self._states.items()
            if now >= state.retry_at + self.max_seconds
        ]
        for key in stale:
            del self._states[key]
        return len(stale)

    def _maybe_prune(self) -> None:
        """前回の掃除から max_seconds 以上経っていれば prune する（全件走査の頻度を抑える）"""
        if self._clock() - self._last_prune >= self.max_seconds:
            self.prune()

    def reset(self, key: Hashable) -> None:
        """成功時に失敗記録を消す"""
        self._states.pop(key, None)

    def failure_count(self, key: Hashable) -> int:
        state = self._states.get(key)
        return state.count if state else 0


def new_storage_load_backoff() -> FailureBackoff:
    """記憶ストアの読み込み失敗用のバックオフを作る

    ロックを持たないため、呼び出し側のストアのロック内で操作すること。
    """
    return FailureBackoff(
        config.STORAGE_LOAD_BACKOFF_BASE_SECONDS, config.STORAGE_LOAD_BACKOFF_MAX_SECONDS
    )
