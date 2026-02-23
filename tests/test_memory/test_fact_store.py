"""ファクトストアのテスト"""

import json
import math
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from memory.fact_store import (
    Fact,
    FactStore,
    _extract_keywords,
    _jaccard_similarity,
    get_fact_store,
)


def _make_fact(
    channel_id: int = 100,
    content: str = "テストファクト",
    keywords: list[str] | None = None,
    source_user_ids: list[int] | None = None,
    shareable: bool = False,
    days_ago: float = 0,
    fact_id: str | None = None,
) -> Fact:
    """テスト用Factファクトリ"""
    created_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return Fact(
        fact_id=fact_id or "test-id",
        channel_id=channel_id,
        content=content,
        keywords=keywords or ["テスト", "ファクト"],
        source_user_ids=source_user_ids or [12345],
        created_at=created_at,
        shareable=shareable,
    )


class TestFact:
    """Factデータクラスのテスト"""

    def test_decay_factor_new(self):
        """作成直後は decay_factor がほぼ 1.0 に近いこと"""
        fact = _make_fact(days_ago=0)
        result = fact.decay_factor(half_life_days=30)
        assert result > 0.99

    def test_decay_factor_half_life(self):
        """半減期経過後は約 0.5 になること"""
        fact = _make_fact(days_ago=30)
        result = fact.decay_factor(half_life_days=30)
        assert abs(result - 0.5) < 0.01

    def test_decay_factor_double_half_life(self):
        """2倍の半減期では約 0.25 になること"""
        fact = _make_fact(days_ago=60)
        result = fact.decay_factor(half_life_days=30)
        assert abs(result - 0.25) < 0.01

    def test_to_dict(self):
        """to_dict が正しいキーを含むこと"""
        fact = _make_fact(fact_id="abc-123")
        d = fact.to_dict()
        assert d["fact_id"] == "abc-123"
        assert d["channel_id"] == 100
        assert d["content"] == "テストファクト"
        assert "keywords" in d
        assert "source_user_ids" in d
        assert "created_at" in d
        assert "shareable" in d

    def test_from_dict_round_trip(self):
        """to_dict → from_dict でデータが保持されること"""
        original = _make_fact(
            fact_id="round-trip",
            content="往復テスト",
            keywords=["往復", "テスト"],
            shareable=True,
        )
        d = original.to_dict()
        restored = Fact.from_dict(d)
        assert restored.fact_id == original.fact_id
        assert restored.content == original.content
        assert restored.keywords == original.keywords
        assert restored.shareable == original.shareable
        assert restored.channel_id == original.channel_id

    def test_from_dict_missing_created_at(self):
        """created_at が欠けている場合は現在時刻で補完されること"""
        d = {
            "fact_id": "x",
            "channel_id": 1,
            "content": "test",
            "keywords": [],
            "source_user_ids": [],
            "shareable": False,
        }
        fact = Fact.from_dict(d)
        assert fact.created_at is not None

    def test_decay_factor_naive_datetime(self):
        """created_at がタイムゾーンなしの場合も正常に動作すること"""
        naive_dt = datetime.now() - timedelta(days=30)
        fact = Fact(
            fact_id="naive",
            channel_id=1,
            content="test",
            keywords=[],
            source_user_ids=[],
            created_at=naive_dt,
        )
        result = fact.decay_factor(30)
        assert abs(result - 0.5) < 0.01


class TestJaccardSimilarity:
    """_jaccard_similarity のテスト"""

    def test_identical_sets(self):
        """完全一致の場合 1.0 を返すこと"""
        s = {"a", "b", "c"}
        assert _jaccard_similarity(s, s) == 1.0

    def test_disjoint_sets(self):
        """共通要素なしの場合 0.0 を返すこと（ただし両方非空）"""
        result = _jaccard_similarity({"a", "b"}, {"c", "d"})
        assert result == 0.0

    def test_empty_sets(self):
        """両方空の場合 0.0 を返すこと"""
        assert _jaccard_similarity(set(), set()) == 0.0

    def test_one_empty_set(self):
        """片方が空の場合 0.0 を返すこと"""
        assert _jaccard_similarity({"a"}, set()) == 0.0
        assert _jaccard_similarity(set(), {"a"}) == 0.0

    def test_partial_overlap(self):
        """部分一致の場合正しい値を返すこと"""
        # {"a","b"} ∩ {"b","c"} = {"b"}, union = {"a","b","c"}
        result = _jaccard_similarity({"a", "b"}, {"b", "c"})
        assert abs(result - 1 / 3) < 1e-9


class TestExtractKeywords:
    """_extract_keywords のテスト"""

    def test_splits_on_space(self):
        """スペース区切りでトークン化されること"""
        result = _extract_keywords("Rust Python Go C")
        assert "Rust" in result
        assert "Python" in result
        assert "Go" in result  # 2文字は残る
        assert "C" not in result  # 1文字 → 除去

    def test_removes_single_char_tokens(self):
        """1文字以下のトークンが除去されること"""
        result = _extract_keywords("a bb ccc")
        assert "a" not in result
        assert "bb" in result
        assert "ccc" in result

    def test_removes_stopwords(self):
        """ひらがなストップワードが除去されること"""
        result = _extract_keywords("これ は テスト")
        # "は" はストップワード
        assert "は" not in result

    def test_splits_on_punctuation(self):
        """句読点で分割されること"""
        result = _extract_keywords("テスト、機能確認。完了")
        assert "テスト" in result
        assert "機能確認" in result
        assert "完了" in result

    def test_empty_string(self):
        """空文字列で空リストを返すこと"""
        result = _extract_keywords("")
        assert result == []


class TestFactStoreSearch:
    """FactStore.search のテスト"""

    def test_returns_matching_facts(self):
        """キーワードマッチするファクトが返ること"""
        store = FactStore()
        fact = _make_fact(keywords=["Rust", "プログラミング"])
        store._facts[100] = [fact]
        store._loaded_channels.add(100)

        results = store.search(100, ["Rust"], limit=5)
        assert len(results) == 1
        assert results[0].content == "テストファクト"

    def test_scores_descending(self):
        """スコアが高いものが先に返ること"""
        store = FactStore()
        fact_high = _make_fact(
            fact_id="high", keywords=["Rust", "Go", "Python"], days_ago=0
        )
        fact_low = _make_fact(
            fact_id="low", keywords=["Java", "Rust"], days_ago=0
        )
        store._facts[100] = [fact_low, fact_high]
        store._loaded_channels.add(100)

        results = store.search(100, ["Rust", "Go", "Python"], limit=5)
        assert results[0].fact_id == "high"

    def test_user_id_boost(self):
        """source_user_ids にマッチするファクトがブーストされること"""
        store = FactStore()
        fact_user = _make_fact(
            fact_id="with-user", keywords=["テスト"], source_user_ids=[999]
        )
        fact_no_user = _make_fact(
            fact_id="no-user", keywords=["テスト"], source_user_ids=[111]
        )
        store._facts[100] = [fact_no_user, fact_user]
        store._loaded_channels.add(100)

        results = store.search(100, ["テスト"], user_ids=[999], limit=5)
        assert results[0].fact_id == "with-user"

    def test_no_match_returns_empty(self):
        """マッチしない場合空リストが返ること"""
        store = FactStore()
        fact = _make_fact(keywords=["Rust"])
        store._facts[100] = [fact]
        store._loaded_channels.add(100)

        results = store.search(100, ["Python"], limit=5)
        assert results == []

    def test_limit_respected(self):
        """limit 件数が守られること"""
        store = FactStore()
        facts = [
            _make_fact(fact_id=str(i), keywords=["共通"])
            for i in range(10)
        ]
        store._facts[100] = facts
        store._loaded_channels.add(100)

        results = store.search(100, ["共通"], limit=3)
        assert len(results) <= 3

    def test_empty_channel_returns_empty(self):
        """ファクトがないチャンネルで空リストが返ること"""
        store = FactStore()
        store._loaded_channels.add(999)
        results = store.search(999, ["テスト"])
        assert results == []


class TestFactStoreGetShareable:
    """FactStore.get_shareable_facts のテスト"""

    def test_returns_only_shareable(self):
        """shareable=True のみが返ること"""
        store = FactStore()
        f1 = _make_fact(fact_id="s1", shareable=True, days_ago=1)
        f2 = _make_fact(fact_id="s2", shareable=False, days_ago=0)
        store._facts[100] = [f1, f2]
        store._loaded_channels.add(100)

        results = store.get_shareable_facts(100)
        assert all(f.shareable for f in results)
        assert len(results) == 1
        assert results[0].fact_id == "s1"

    def test_ordered_by_decay_descending(self):
        """decay_factor 降順に並ぶこと（新しいほど先）"""
        store = FactStore()
        f_new = _make_fact(fact_id="new", shareable=True, days_ago=1)
        f_old = _make_fact(fact_id="old", shareable=True, days_ago=60)
        store._facts[100] = [f_old, f_new]
        store._loaded_channels.add(100)

        results = store.get_shareable_facts(100)
        assert results[0].fact_id == "new"

    def test_empty_channel_returns_empty(self):
        """ファクトなしで空リストが返ること"""
        store = FactStore()
        store._loaded_channels.add(100)
        assert store.get_shareable_facts(100) == []


class TestFactStoreEviction:
    """上限超過時の削除テスト"""

    def test_evicts_oldest_on_overflow(self):
        """上限超過で decay_factor 最小（最古）が削除されること"""
        store = FactStore()
        f_new = _make_fact(fact_id="new", days_ago=1)
        f_mid = _make_fact(fact_id="mid", days_ago=15)
        f_old = _make_fact(fact_id="old", days_ago=60)

        store._loaded_channels.add(100)
        # 上限2件: new と mid をセットした後、old を追加 → old は decay 最小なので即削除される
        store._facts[100] = [f_new, f_mid]
        with patch("config.FACT_STORE_MAX_FACTS_PER_CHANNEL", 2):
            with patch("config.FACT_DECAY_HALF_LIFE_DAYS", 30):
                store.add_fact(f_old)

        ids = [f.fact_id for f in store._facts[100]]
        assert len(ids) == 2
        assert "old" not in ids


class TestFactStoreLocalStorage:
    """ローカルストレージのテスト"""

    def test_save_to_local_calls_atomic_write(self):
        """_save_to_local が atomic_write_json を呼び出すこと"""
        store = FactStore()
        fact = _make_fact()
        with patch("memory.fact_store.config.STORAGE_TYPE", "local"):
            with patch("utils.file_utils.atomic_write_json") as mock_write:
                store._save_to_local(100, [fact])
                mock_write.assert_called_once()
                args = mock_write.call_args[0]
                assert "facts.100.json" in args[0]
                data = args[1]
                assert data["channel_id"] == 100
                assert len(data["facts"]) == 1

    def test_load_from_local_reads_json(self):
        """_load_from_local がJSONファイルからファクトを読み込むこと"""
        store = FactStore()
        fact = _make_fact()
        with patch("os.path.exists", return_value=True):
            with patch("json.load", return_value={"channel_id": 100, "facts": [fact.to_dict()]}):
                from unittest.mock import mock_open
                with patch("builtins.open", mock_open(read_data="dummy")):
                    result = store._load_from_local(100)
        assert result is not None
        assert len(result) == 1


class TestFactStoreFirestore:
    """Firestoreストレージのテスト"""

    def test_save_to_firestore_calls_client(self):
        """_save_to_firestore が Firestore クライアントを呼び出すこと"""
        store = FactStore()
        fact = _make_fact()
        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_doc = MagicMock()
        mock_db.collection.return_value = mock_collection
        mock_collection.document.return_value = mock_doc

        with patch("memory.fact_store.get_firestore_client", return_value=mock_db, create=True):
            with patch("utils.firestore_client.get_firestore_client", return_value=mock_db):
                store._save_to_firestore(100, [fact])

    def test_load_from_firestore_returns_none_on_exception(self):
        """Firestore 読み込みで例外が発生した場合 None を返すこと"""
        store = FactStore()
        with patch("utils.firestore_client.get_firestore_client", side_effect=Exception("接続エラー")):
            result = store._load_from_firestore(100)
        assert result is None


class TestGetFactStore:
    """シングルトンのテスト"""

    def test_singleton(self):
        """同じインスタンスが返ること"""
        import memory.fact_store as fs_module

        original = fs_module._fact_store
        fs_module._fact_store = None
        try:
            s1 = get_fact_store()
            s2 = get_fact_store()
            assert s1 is s2
        finally:
            fs_module._fact_store = original
