"""書き換えと保存時の書き出しが並行しても、保存内容が一貫していることのテスト（issue #147）"""

# mypy: ignore-errors

import threading
import time
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from memory.fact_store import Fact, FactStore
from memory.user_profile import UserProfileStore

CHANNEL_ID = 100
GUILD_ID = 7
USER_ID = 1
KEY = (GUILD_ID, USER_ID)
_WAIT = 2.0


class _BlockingSaver:
    """書き込みを止めて、渡されたオブジェクトをそのまま保持する偽の保存関数"""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.received: list = []

    def __call__(self, *args) -> bool:
        self.received.append(args)
        self.entered.set()
        assert self.release.wait(_WAIT)
        return True


def _start(target, *args) -> threading.Thread:
    thread = threading.Thread(target=target, args=args, daemon=True)
    thread.start()
    return thread


class TestUserProfileMutationDuringSave:
    """UserProfileStore: 書き出し中の書き換え"""

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

    def _mutate_all(self, store: UserProfileStore) -> None:
        store.record_message(GUILD_ID, USER_ID, 200, "Renamed")
        store.record_bot_mention(GUILD_ID, USER_ID)
        store.update_last_topic(GUILD_ID, USER_ID, ["新しい話題"])
        store.update_from_reflection(
            GUILD_ID, USER_ID, {"tags": ["新タグ"], "notable_facts": ["新事実"]}
        )
        store.update_nickname(GUILD_ID, USER_ID, "あだ名")

    def test_save_receives_snapshot_unaffected_by_mutation(self):
        """書き出し中に書き換えても、保存に渡したスナップショットは変わらない"""
        store = UserProfileStore()
        store.record_message(GUILD_ID, USER_ID, CHANNEL_ID, "User")
        saver = _BlockingSaver()

        with patch.object(store, "_save_profile", side_effect=saver):
            worker = _start(store.persist_all)
            assert saver.entered.wait(_WAIT)
            self._mutate_all(store)
            saved = saver.received[0][0].to_dict()
            saver.release.set()
            worker.join(_WAIT)
            assert not worker.is_alive()

        assert saved["interaction_count"] == 1
        assert saved["mentioned_bot_count"] == 0
        assert saved["display_name"] == "User"
        assert saved["channels_active"] == [CHANNEL_ID]
        assert saved["last_topic"] == []
        assert saved["tags"] == []
        assert saved["notable_facts"] == []
        assert saved["nickname"] is None

        live = store.get_cached_profile(GUILD_ID, USER_ID)
        assert live is not saver.received[0][0]
        assert live.interaction_count == 2
        assert live.channels_active == [CHANNEL_ID, 200]
        # 書き出し後の変更は次回の保存対象として残る
        assert KEY in store._dirty

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda s: s.record_message(GUILD_ID, USER_ID, 200, "User"),
            lambda s: s.record_bot_mention(GUILD_ID, USER_ID),
            lambda s: s.update_last_topic(GUILD_ID, USER_ID, ["話題"]),
            lambda s: s.update_from_reflection(GUILD_ID, USER_ID, {"tags": ["タグ"]}),
            lambda s: s.update_nickname(GUILD_ID, USER_ID, "あだ名"),
        ],
    )
    def test_mutation_waits_for_store_lock(self, mutate):
        """書き換えはスナップショット取得（self._lock）と排他になる"""
        store = UserProfileStore()
        store.record_message(GUILD_ID, USER_ID, CHANNEL_ID, "User")
        store._dirty.clear()
        before = store.get_cached_profile(GUILD_ID, USER_ID).to_dict()

        with store._lock:
            worker = _start(mutate, store)
            time.sleep(0.1)
            # ロック保持中は書き換えも dirty 化も起きない
            assert store._profiles[KEY].to_dict() == before
            assert KEY not in store._dirty
        worker.join(_WAIT)
        assert not worker.is_alive()

        assert store._profiles[KEY].to_dict() != before
        assert KEY in store._dirty

    def test_snapshot_lists_are_independent(self):
        """スナップショットのリストは元のプロファイルと共有しない"""
        store = UserProfileStore()
        store.record_message(GUILD_ID, USER_ID, CHANNEL_ID, "User")
        profile = store.get_cached_profile(GUILD_ID, USER_ID)
        profile.tags.append("a")
        snap = profile.snapshot()

        for name in ("channels_active", "last_topic", "tags", "notable_facts"):
            assert getattr(snap, name) == getattr(profile, name)
            assert getattr(snap, name) is not getattr(profile, name)

    def test_reflection_merges_and_trims(self, mock_config):
        """反省会の反映で重複を除いて追記し、上限で切り詰める"""
        mock_config.USER_PROFILE_TAGS_LIMIT = 3
        store = UserProfileStore()
        store.record_message(GUILD_ID, USER_ID, CHANNEL_ID, "User")
        store.update_from_reflection(GUILD_ID, USER_ID, {"tags": ["a", "b"]})
        store.update_from_reflection(
            GUILD_ID, USER_ID,
            {"tags": ["b", "c", "d"], "preferred_tone": "不明", "nickname": "あだ名"},
        )

        profile = store.get_cached_profile(GUILD_ID, USER_ID)
        assert profile.tags == ["b", "c", "d"]
        assert profile.preferred_tone is None
        assert profile.nickname == "あだ名"

    def test_reflection_for_uncached_profile_is_ignored(self):
        """キャッシュにないプロファイルへの反映は何もしない"""
        store = UserProfileStore()
        store.update_from_reflection(GUILD_ID, USER_ID, {"tags": ["a"], "nickname": "x"})
        store.update_nickname(GUILD_ID, USER_ID, "x")

        assert store.get_cached_profile(GUILD_ID, USER_ID) is None
        assert not store._dirty


def _make_fact(fact_id: str, content: str) -> Fact:
    return Fact(
        fact_id=fact_id,
        channel_id=CHANNEL_ID,
        content=content,
        keywords=[content],
        source_user_ids=[12345],
        created_at=datetime.now(timezone.utc),
    )


class TestFactStoreMutationDuringSave:
    """FactStore: 書き出し中の search による参照頻度の更新"""

    @pytest.fixture
    def store(self):
        with patch("memory.fact_store.config.STORAGE_TYPE", "memory"):
            yield FactStore()

    def test_search_during_save_does_not_change_snapshot(self, store):
        """書き出し中に search で access_count が増えても、保存内容は変わらない"""
        store.add_fact(_make_fact("f1", "クリスタル"))
        saver = _BlockingSaver()

        with patch.object(store, "_save_channel", side_effect=saver):
            worker = _start(store.persist_channel, CHANNEL_ID)
            assert saver.entered.wait(_WAIT)
            hits = store.search(CHANNEL_ID, ["クリスタル"])
            saved_facts = saver.received[0][1]
            saved = [f.to_dict() for f in saved_facts]
            saver.release.set()
            worker.join(_WAIT)
            assert not worker.is_alive()

        assert len(hits) == 1 and hits[0].access_count == 1
        assert saved[0]["access_count"] == 0
        assert saved[0]["last_accessed_at"] is None
        assert saved_facts[0] is not hits[0]
        # 書き出し後の参照頻度の更新は次回の保存対象として残る
        assert CHANNEL_ID in store._dirty

    def test_cleanup_scores_on_snapshot(self, store):
        """忘却クリーンアップは複製に対してスコアを計算し、元のファクトを正しく除去する"""
        store.add_fact(_make_fact("f1", "古いファクト"))
        original = store._facts[CHANNEL_ID][0]

        with patch("memory.fact_store.config.FACT_STORE_CLEANUP_THRESHOLD", 10.0), \
             patch.object(store, "_archive_facts") as mock_archive:
            removed = store.cleanup_low_relevance_facts()

        assert removed == {CHANNEL_ID: 1}
        archived = mock_archive.call_args[0][1][0][1]
        assert archived is not original and archived.fact_id == "f1"
        assert store._facts[CHANNEL_ID] == []
