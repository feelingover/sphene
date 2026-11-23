"""ファクトストア・ユーザープロファイルの差分永続化とドキュメントサイズ上限のテスト"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from memory.fact_store import (
    Fact,
    FactStore,
    _fit_facts_to_document,
    _to_archive_entries,
    _trim_archive_entries,
)
from memory.user_profile import UserProfileStore
from utils.firestore_client import estimate_document_size


def _fact(fact_id: str, channel_id: int = 100, days_ago: float = 0, dims: int = 0, content: str | None = None) -> Fact:
    return Fact(
        fact_id=fact_id,
        channel_id=channel_id,
        content=content or f"ファクト{fact_id}",
        keywords=[f"kw{fact_id}"],
        source_user_ids=[1],
        created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        embedding=[0.5] * dims if dims else None,
    )


def _loaded_store(*channel_ids: int) -> FactStore:
    store = FactStore()
    store._loaded_channels.update(channel_ids)
    return store


class TestFactStoreDirty:
    def test_persist_all_writes_only_dirty_channels(self):
        store = _loaded_store(1, 2)
        store.add_fact(_fact("a", channel_id=1))
        store._facts[2] = [_fact("b", channel_id=2)]  # 読み込み済み・未変更

        with patch.object(store, "_save_channel", return_value=True) as save:
            store.persist_all()

        assert [c.args[0] for c in save.call_args_list] == [1]
        assert store._dirty == set()

    def test_second_persist_all_without_changes_writes_nothing(self):
        store = _loaded_store(1)
        store.add_fact(_fact("a", channel_id=1))
        with patch.object(store, "_save_channel", return_value=True) as save:
            store.persist_all()
            store.persist_all()
        assert save.call_count == 1

    def test_failed_write_is_retried(self):
        store = _loaded_store(1)
        store.add_fact(_fact("a", channel_id=1))
        with patch.object(store, "_save_channel", side_effect=[False, True]) as save:
            store.persist_all()
            assert store._dirty == {1}
            store.persist_all()
        assert save.call_count == 2
        assert store._dirty == set()

    def test_duplicate_fact_does_not_mark_dirty(self):
        store = _loaded_store(1)
        store._facts[1] = [_fact("a", channel_id=1)]
        assert not store.add_fact(_fact("b", channel_id=1, content="ファクトa"))
        assert store._dirty == set()

    def test_search_hit_marks_dirty(self):
        store = _loaded_store(1)
        store._facts[1] = [_fact("a", channel_id=1)]
        assert store.search(1, ["kwa"])
        assert store._dirty == {1}

    def test_search_miss_does_not_mark_dirty(self):
        store = _loaded_store(1)
        store._facts[1] = [_fact("a", channel_id=1)]
        assert not store.search(1, ["none"])
        assert store._dirty == set()

    def test_persist_channel_clears_dirty(self):
        store = _loaded_store(1)
        store.add_fact(_fact("a", channel_id=1))
        with patch.object(store, "_save_channel", return_value=True):
            store.persist_channel(1)
        assert store._dirty == set()

    def test_persist_channel_failure_keeps_dirty(self):
        store = _loaded_store(1)
        store.add_fact(_fact("a", channel_id=1))
        with patch.object(store, "_save_channel", return_value=False):
            store.persist_channel(1)
        assert store._dirty == {1}

    @pytest.mark.parametrize("storage", ["local", "firestore"])
    def test_save_errors_return_false(self, storage):
        store = FactStore()
        with patch("config.STORAGE_TYPE", storage), \
             patch("utils.file_utils.atomic_write_json", side_effect=OSError("disk")), \
             patch("utils.firestore_client.get_firestore_client", side_effect=RuntimeError("down")):
            assert store._save_channel(1, [_fact("a")]) is False

    def test_unknown_storage_type_counts_as_saved(self):
        with patch("config.STORAGE_TYPE", "none"):
            assert FactStore()._save_channel(1, [_fact("a")]) is True


class TestFitFactsToDocument:
    def test_small_document_unchanged(self):
        facts = [_fact(str(i), dims=768) for i in range(10)]
        assert [e["fact_id"] for e in _fit_facts_to_document(1, facts)] == [str(i) for i in range(10)]

    def test_current_default_capacity_fits(self):
        """デフォルト上限 (100件 × 768次元) は除外されない（JSON長で見積もると誤って削る）"""
        facts = [_fact(str(i), dims=768) for i in range(100)]
        assert len(_fit_facts_to_document(1, facts)) == 100

    def test_oversized_document_drops_least_relevant(self):
        # 3072次元 × 50件 ≈ 1.2MB → 上限超過
        facts = [_fact(str(i), days_ago=i, dims=3072) for i in range(50)]

        entries = _fit_facts_to_document(1, facts)

        assert len(entries) < 50
        assert estimate_document_size({"channel_id": 1, "facts": entries}) <= 1_000_000
        kept = [int(e["fact_id"]) for e in entries]
        # 新しい（関連度の高い）ファクトから残り、元の順序は維持
        assert kept == list(range(len(kept)))

    def test_save_to_firestore_writes_trimmed_document(self):
        facts = [_fact(str(i), days_ago=i, dims=3072) for i in range(50)]
        mock_db = MagicMock()
        with patch("utils.firestore_client.get_firestore_client", return_value=mock_db):
            assert FactStore()._save_to_firestore(1, facts) is True
        data = mock_db.collection.return_value.document.return_value.set.call_args.args[0]
        assert estimate_document_size(data) <= 1_000_000


class TestArchiveEntries:
    def test_embedding_removed(self):
        entries = _to_archive_entries([_fact("a", dims=768)])
        assert "embedding" not in entries[0]
        assert entries[0]["content"] == "ファクトa"
        assert "archived_at" in entries[0]

    def test_trim_removes_legacy_embeddings_and_caps_count(self):
        legacy = [{"fact_id": str(i), "embedding": [0.1] * 768} for i in range(10)]
        with patch("config.FACT_ARCHIVE_MAX_ENTRIES", 3):
            trimmed = _trim_archive_entries(legacy, size_limited=False)
        assert [e["fact_id"] for e in trimmed] == ["7", "8", "9"]
        assert all("embedding" not in e for e in trimmed)

    def test_trim_by_size_drops_oldest(self):
        big = [{"fact_id": str(i), "content": "あ" * 10_000} for i in range(200)]  # 約6MB
        with patch("config.FACT_ARCHIVE_MAX_ENTRIES", 500):
            trimmed = _trim_archive_entries(big, size_limited=True)
        assert estimate_document_size({"channel_id": 0, "archived_facts": trimmed}) <= 1_000_000
        assert trimmed[-1]["fact_id"] == "199"
        assert len(trimmed) < 200

    def test_firestore_archive_document_fits(self):
        existing = [{"fact_id": f"old{i}", "embedding": [0.1] * 768, "content": "x"} for i in range(500)]
        doc = MagicMock()
        doc.exists = True
        doc.to_dict.return_value = {"archived_facts": existing}
        mock_db = MagicMock()
        doc_ref = mock_db.collection.return_value.document.return_value
        doc_ref.get.return_value = doc

        with patch("utils.firestore_client.get_firestore_client", return_value=mock_db), \
             patch("config.FACT_ARCHIVE_MAX_ENTRIES", 500):
            FactStore()._append_to_firestore_archive(1, [_fact("new", dims=768)])

        data = doc_ref.set.call_args.args[0]
        assert estimate_document_size(data) <= 1_000_000
        assert data["archived_facts"][-1]["fact_id"] == "new"
        assert all("embedding" not in e for e in data["archived_facts"])


class TestUserProfileDirty:
    def _store(self) -> UserProfileStore:
        store = UserProfileStore()
        store._load_profile = MagicMock(return_value=None)  # type: ignore[method-assign]
        store._load_legacy_profile = MagicMock(return_value=None)  # type: ignore[method-assign]
        return store

    def test_get_profile_alone_is_not_dirty(self):
        store = self._store()
        store.get_profile(1, 10, "u")
        with patch.object(store, "_save_profile", return_value=True) as save:
            store.persist_all()
        save.assert_not_called()

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda s: s.record_message(1, 10, 100, "u"),
            lambda s: s.record_bot_mention(1, 10),
            lambda s: s.update_last_topic(1, 10, ["話題"]),
            lambda s: s.update_from_reflection(1, 10, {"tags": ["タグ"]}),
            lambda s: s.update_nickname(1, 10, "ニック"),
        ],
    )
    def test_mutations_mark_dirty(self, mutate):
        store = self._store()
        store.get_profile(1, 10, "u")
        store.get_profile(1, 20, "other")
        mutate(store)
        with patch.object(store, "_save_profile", return_value=True) as save:
            store.persist_all()
        assert [c.args[0].user_id for c in save.call_args_list] == [10]

    def test_failed_write_is_retried(self):
        store = self._store()
        store.record_message(1, 10, 100, "u")
        with patch.object(store, "_save_profile", side_effect=[False, True]) as save:
            store.persist_all()
            store.persist_all()
            store.persist_all()
        assert save.call_count == 2

    def test_update_last_topic_without_keywords_is_not_dirty(self):
        store = self._store()
        store.get_profile(1, 10, "u")
        store.update_last_topic(1, 10, [])
        assert store._dirty == set()

    @pytest.mark.parametrize("storage", ["local", "firestore"])
    def test_save_errors_return_false(self, storage):
        store = self._store()
        profile = store.get_profile(1, 10, "u")
        with patch("config.STORAGE_TYPE", storage), \
             patch("utils.file_utils.atomic_write_json", side_effect=OSError("disk")), \
             patch("utils.firestore_client.get_firestore_client", side_effect=RuntimeError("down")):
            assert store._save_profile(profile) is False
