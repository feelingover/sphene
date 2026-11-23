"""プロファイルの読み取りが書き換えと並行しても一貫した状態を読むことのテスト（issue #153）"""

# mypy: ignore-errors

import threading
import time
from unittest.mock import patch

import pytest

from memory.user_profile import UserProfileStore

GUILD_ID = 7
USER_ID = 1
KEY = (GUILD_ID, USER_ID)
_WAIT = 2.0


def _start(target, *args) -> tuple[threading.Thread, list]:
    result: list = []
    thread = threading.Thread(
        target=lambda: result.append(target(*args)), daemon=True
    )
    thread.start()
    return thread, result


class TestProfileReadConsistency:
    """UserProfileStore: 読み取りと書き換えの並行"""

    @pytest.fixture(autouse=True)
    def mock_config(self):
        with patch("memory.user_profile.config") as mock_cfg, \
             patch("memory.user_profile.os.path.exists", return_value=False):
            mock_cfg.STORAGE_TYPE = "local"
            mock_cfg.FAMILIARITY_THRESHOLD_ACQUAINTANCE = 6
            mock_cfg.FAMILIARITY_THRESHOLD_REGULAR = 31
            mock_cfg.FAMILIARITY_THRESHOLD_CLOSE = 101
            mock_cfg.CHANNELS_ACTIVE_LIMIT = 20
            mock_cfg.USER_PROFILE_TAGS_LIMIT = 10
            mock_cfg.USER_PROFILE_FACTS_LIMIT = 10
            yield mock_cfg

    def _store(self) -> UserProfileStore:
        store = UserProfileStore()
        store.record_message(GUILD_ID, USER_ID, 100, "User")
        store.update_from_reflection(
            GUILD_ID, USER_ID,
            {"tags": ["旧タグ"], "notable_facts": ["旧事実"], "personality_notes": "旧メモ"},
        )
        return store

    @pytest.mark.parametrize(
        "read",
        [
            lambda s: s.get_profile(GUILD_ID, USER_ID, "User"),
            lambda s: s.get_cached_profile(GUILD_ID, USER_ID),
        ],
    )
    def test_read_waits_for_store_lock(self, read):
        """読み取りは書き換え（self._lock）が終わるまで待つ"""
        store = self._store()
        with store._lock:
            worker, result = _start(read, store)
            time.sleep(0.1)
            assert worker.is_alive()
            assert result == []
            # ロック保持中の書き換え（途中状態）を再現する
            store._profiles[KEY].tags = ["新タグ"]
            store._profiles[KEY].notable_facts = ["新事実"]
        worker.join(_WAIT)
        assert not worker.is_alive()

        persona = result[0].format_for_persona()
        assert "新タグ" in persona and "新事実" in persona
        assert "旧タグ" not in persona

    def test_snapshot_is_unaffected_by_later_mutation(self):
        """取得後に書き換えが入っても、取得したプロファイルの内容は変わらない"""
        store = self._store()
        profile = store.get_profile(GUILD_ID, USER_ID, "User")
        before = profile.format_for_injection()

        store.record_message(GUILD_ID, USER_ID, 200, "Renamed")
        store.update_last_topic(GUILD_ID, USER_ID, ["新しい話題"])
        store.update_from_reflection(
            GUILD_ID, USER_ID,
            {"tags": ["新タグ"], "notable_facts": ["新事実"], "personality_notes": "新メモ"},
        )
        store.update_nickname(GUILD_ID, USER_ID, "あだ名")

        assert profile.format_for_injection() == before
        assert profile.tags == ["旧タグ"]
        latest = store.get_profile(GUILD_ID, USER_ID, "User").format_for_injection()
        assert "新タグ" in latest and "あだ名" in latest

    def test_concurrent_reflection_never_mixes_old_and_new(self):
        """並行する書き換え中に読んでも、新旧の値が混ざらない"""
        store = self._store()
        stop = threading.Event()

        def _writer() -> None:
            flip = False
            while not stop.is_set():
                label = "A" if flip else "B"
                with store._lock:
                    profile = store._profiles[KEY]
                    profile.tags = [f"タグ{label}"]
                    time.sleep(0.0005)
                    profile.notable_facts = [f"事実{label}"]
                flip = not flip

        writer = threading.Thread(target=_writer, daemon=True)
        writer.start()
        try:
            for _ in range(200):
                profile = store.get_cached_profile(GUILD_ID, USER_ID)
                assert profile.tags[0][-1] == profile.notable_facts[0][-1]
        finally:
            stop.set()
            writer.join(_WAIT)

    def test_get_cached_profile_returns_none_for_missing(self):
        """キャッシュにないプロファイルは None を返す"""
        assert UserProfileStore().get_cached_profile(GUILD_ID, USER_ID) is None

    def test_temporary_profile_on_load_failure_is_not_cached(self):
        """読み込み失敗時の一時プロファイルを返してもキャッシュはしない"""
        from memory.errors import StorageLoadError

        store = UserProfileStore()
        with patch.object(store, "_load_profile", side_effect=StorageLoadError("down")):
            profile = store.get_profile(GUILD_ID, USER_ID, "User")
        assert profile.user_id == USER_ID
        assert store.get_cached_profile(GUILD_ID, USER_ID) is None
