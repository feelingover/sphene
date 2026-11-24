"""記憶ストアのキャッシュ追い出し（LRU）の共通部品

記憶ストアは永続化先（local / Firestore）のキャッシュとして動くため、
追い出したエントリは次回アクセス時に永続化先から透過的に読み直される。
未保存の変更があるエントリなど、追い出してはいけないものの判定は各ストアが行う。
"""

import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Generic, TypeVar

K = TypeVar("K", bound=Hashable)


class LruTracker(Generic[K]):
    """キャッシュのキーを最終アクセス順に保持する

    ロックを持たないため、呼び出し側のストアのロック内で操作すること。

    Args:
        clock: 現在時刻を返す関数（テスト用に差し替え可能）
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._last_access: OrderedDict[K, float] = OrderedDict()

    def __len__(self) -> int:
        return len(self._last_access)

    def __contains__(self, key: object) -> bool:
        return key in self._last_access

    def touch(self, key: K) -> None:
        """キーへのアクセスを記録し、最も新しい位置へ移す"""
        self._last_access[key] = self._clock()
        self._last_access.move_to_end(key)

    def forget(self, key: K) -> None:
        """キーの記録を消す（追い出し時に呼ぶ）"""
        self._last_access.pop(key, None)

    def is_idle(self, key: K, min_idle_seconds: float) -> bool:
        """キーが min_idle_seconds 以上アクセスされていないか（未記録なら False）"""
        accessed = self._last_access.get(key)
        return accessed is not None and self._clock() - accessed >= min_idle_seconds

    def eviction_candidates(
        self,
        max_entries: int,
        min_idle_seconds: float,
        is_protected: Callable[[K], bool],
    ) -> list[K]:
        """上限超過分の追い出し候補を、最終アクセスの古い順に返す

        最近アクセスされたキー（min_idle_seconds 未満）は、呼び出し側がまだ参照を
        保持して書き換え中の可能性があるため候補にしない。そのため上限は目安であり、
        直近にアクセスされたキーが多ければ一時的に上限を超えて保持する。

        Args:
            max_entries: 保持するキー数の上限
            min_idle_seconds: 追い出しに必要な最小の無アクセス秒数
            is_protected: True を返したキーは候補から除外する（未保存の変更がある等）

        Returns:
            追い出し候補のキー（最大で上限超過分の件数）
        """
        excess = len(self._last_access) - max(max_entries, 0)
        if excess <= 0:
            return []
        deadline = self._clock() - min_idle_seconds
        candidates: list[K] = []
        for key, accessed in self._last_access.items():
            if accessed > deadline or len(candidates) >= excess:
                break
            if not is_protected(key):
                candidates.append(key)
        return candidates
