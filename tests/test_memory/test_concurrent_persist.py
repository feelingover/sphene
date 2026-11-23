"""並行保存で古いスナップショットが後勝ちしないことのテスト（issue #135）"""

# mypy: ignore-errors

import threading
import time
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from memory.fact_store import Fact, FactStore
from memory.user_profile import UserProfileStore
from utils.keyed_lock import KeyedLock

CHANNEL_ID = 100
GUILD_ID = 7
USER_ID = 1
_WAIT = 2.0


def _make_fact(fact_id: str, content: str, channel_id: int = CHANNEL_ID) -> Fact:
    return Fact(
        fact_id=fact_id,
        channel_id=channel_id,
        content=content,
        keywords=[content],
        source_user_ids=[12345],
        created_at=datetime.now(timezone.utc),
    )


class _BlockingSaver:
    """最初の書き込みだけを止め、完了順に書き込み内容を記録する偽の保存関数"""

    def __init__(self, capture):
        self._capture = capture
        self.first_entered = threading.Event()
        self.release_first = threading.Event()
        self.completed: list = []
        self.calls = 0
        self._guard = threading.Lock()

    def __call__(self, *args) -> bool:
        content = self._capture(*args)
        with self._guard:
            self.calls += 1
            is_first = self.calls == 1
        if is_first:
            self.first_entered.set()
            assert self.release_first.wait(_WAIT)
        with self._guard:
            self.completed.append(content)
        return True


def _start(target, *args) -> threading.Thread:
    thread = threading.Thread(target=target, args=args, daemon=True)
    thread.start()
    return thread


@pytest.fixture
def fact_store():
    with patch("memory.fact_store.config.STORAGE_TYPE", "memory"):
        yield FactStore()


class TestFactStoreConcurrentPersist:
    """FactStore の同一チャンネル並行保存"""

    def _run_race(self, store: FactStore, second_persist) -> _BlockingSaver:
        saver = _BlockingSaver(lambda cid, facts: (cid, [f.fact_id for f in facts]))
        store.add_fact(_make_fact("old", "古いファクト"))
        with patch.object(store, "_save_channel", side_effect=saver):
            first = _start(store.persist_channel, CHANNEL_ID)
            assert saver.first_entered.wait(_WAIT)

            # 1回目の書き込み中に新しいファクトを追加して、もう一度保存する
            store.add_fact(_make_fact("new", "新しいファクト"))
            second = _start(second_persist)
            time.sleep(0.1)
            # 同じチャンネルの保存は直列化され、2回目は1回目の完了を待つ
            assert saver.calls == 1

            saver.release_first.set()
            first.join(_WAIT)
            second.join(_WAIT)
        return saver

    def test_persist_channel_newer_snapshot_wins(self, fact_store):
        """persist_channel 同士の競合で、新しいスナップショットが最後に書き込まれる"""
        saver = self._run_race(fact_store, lambda: fact_store.persist_channel(CHANNEL_ID))

        assert saver.completed[-1] == (CHANNEL_ID, ["old", "new"])
        assert CHANNEL_ID not in fact_store._dirty

    def test_persist_all_newer_snapshot_wins(self, fact_store):
        """persist_channel と persist_all の競合でも、新しいスナップショットが最後に書き込まれる"""
        saver = self._run_race(fact_store, fact_store.persist_all)

        assert saver.completed[-1] == (CHANNEL_ID, ["old", "new"])
        assert CHANNEL_ID not in fact_store._dirty

    def test_persist_all_skips_channel_saved_while_waiting(self, fact_store):
        """待機中に別スレッドが保存を済ませたチャンネルは persist_all で再書き込みしない"""
        fact_store.add_fact(_make_fact("f1", "ファクト"))
        fact_store.persist_channel(CHANNEL_ID)

        with patch.object(fact_store, "_save_channel", return_value=True) as mock_save:
            result = fact_store._persist_channel_serialized(CHANNEL_ID, only_if_dirty=True)

        assert result is None
        mock_save.assert_not_called()

    def test_failed_save_keeps_dirty(self, fact_store):
        """書き込みに失敗したチャンネルは dirty に戻る"""
        fact_store.add_fact(_make_fact("f1", "ファクト"))

        with patch.object(fact_store, "_save_channel", return_value=False):
            fact_store.persist_all()

        assert CHANNEL_ID in fact_store._dirty

    def test_unloaded_channel_is_not_saved(self, fact_store):
        """未ロードのチャンネルは書き込まず dirty に残す"""
        fact_store.add_fact(_make_fact("f1", "ファクト"))
        fact_store._loaded_channels.discard(CHANNEL_ID)

        with patch.object(fact_store, "_save_channel", return_value=True) as mock_save:
            fact_store.persist_channel(CHANNEL_ID)
            fact_store.persist_all()

        mock_save.assert_not_called()
        assert CHANNEL_ID in fact_store._dirty

    def test_different_channels_do_not_block_each_other(self, fact_store):
        """別チャンネルの保存はロックを共有せず並行に進む"""
        saver = _BlockingSaver(lambda cid, facts: cid)
        fact_store.add_fact(_make_fact("a", "チャンネルA", channel_id=1))
        fact_store.add_fact(_make_fact("b", "チャンネルB", channel_id=2))

        with patch.object(fact_store, "_save_channel", side_effect=saver):
            first = _start(fact_store.persist_channel, 1)
            assert saver.first_entered.wait(_WAIT)
            fact_store.persist_channel(2)  # チャンネル1の書き込み中でも完了する
            assert saver.completed == [2]

            saver.release_first.set()
            first.join(_WAIT)

        assert saver.completed == [2, 1]


class TestUserProfileConcurrentPersist:
    """UserProfileStore の同一プロファイル並行保存"""

    @pytest.fixture(autouse=True)
    def mock_config(self):
        with patch("memory.user_profile.config") as mock_cfg, \
             patch("memory.user_profile.os.path.exists", return_value=False):
            mock_cfg.STORAGE_TYPE = "local"
            mock_cfg.FAMILIARITY_THRESHOLD_ACQUAINTANCE = 6
            mock_cfg.FAMILIARITY_THRESHOLD_REGULAR = 31
            mock_cfg.FAMILIARITY_THRESHOLD_CLOSE = 101
            mock_cfg.CHANNELS_ACTIVE_LIMIT = 20
            yield mock_cfg

    def test_persist_all_newer_snapshot_wins(self):
        """並行した persist_all で、新しい内容が最後に書き込まれる"""
        store = UserProfileStore()
        saver = _BlockingSaver(lambda profile: profile.to_dict()["interaction_count"])
        store.record_message(GUILD_ID, USER_ID, 100, "User")

        with patch.object(store, "_save_profile", side_effect=saver):
            first = _start(store.persist_all)
            assert saver.first_entered.wait(_WAIT)

            store.record_message(GUILD_ID, USER_ID, 100, "User")
            second = _start(store.persist_all)
            time.sleep(0.1)
            assert saver.calls == 1

            saver.release_first.set()
            first.join(_WAIT)
            second.join(_WAIT)

        assert saver.completed == [1, 2]
        assert (GUILD_ID, USER_ID) not in store._dirty

    def test_failed_save_keeps_dirty(self):
        """書き込みに失敗したプロファイルは dirty に戻る"""
        store = UserProfileStore()
        store.record_message(GUILD_ID, USER_ID, 100, "User")

        with patch.object(store, "_save_profile", return_value=False):
            store.persist_all()

        assert (GUILD_ID, USER_ID) in store._dirty

    def test_dirty_key_without_cached_profile_is_dropped(self):
        """キャッシュにないキーは保存せず dirty から外す"""
        store = UserProfileStore()
        store._dirty.add((GUILD_ID, 999))

        with patch.object(store, "_save_profile", return_value=True) as mock_save:
            store.persist_all()

        mock_save.assert_not_called()
        assert not store._dirty


class TestKeyedLock:
    """KeyedLock の基本動作"""

    def test_same_key_returns_same_lock(self):
        locks: KeyedLock[int] = KeyedLock()
        assert locks.get(1) is locks.get(1)

    def test_different_keys_return_different_locks(self):
        locks: KeyedLock[int] = KeyedLock()
        assert locks.get(1) is not locks.get(2)
