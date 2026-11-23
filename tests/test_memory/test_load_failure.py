"""記憶ストアの読み込み失敗時に既存データを上書きしないことのテスト（#131）"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from memory.backoff import FailureBackoff
from memory.channel_context import ChannelContext, ChannelContextStore
from memory.errors import StorageLoadError, log_storage_load_failure
from memory.fact_store import Fact, FactStore, _merge_pending_facts
from memory.user_profile import UserProfile, UserProfileStore


def _fact(fact_id: str, content: str, channel_id: int = 100) -> Fact:
    return Fact(
        fact_id=fact_id,
        channel_id=channel_id,
        content=content,
        keywords=[f"kw{fact_id}"],
        source_user_ids=[1],
        created_at=datetime.now(timezone.utc),
    )


class _FakeClock:
    """バックオフの経過時間をテストから進めるための時計"""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _backoff(clock: _FakeClock) -> FailureBackoff:
    return FailureBackoff(base_seconds=30, max_seconds=600, clock=clock)


class TestFactStoreLoadFailure:
    def _store(self, load_side_effect: object, clock: _FakeClock | None = None) -> FactStore:
        store = FactStore()
        store._load_from_firestore = MagicMock(side_effect=load_side_effect)  # type: ignore[method-assign]
        store._load_backoff = _backoff(clock or _FakeClock())
        return store

    @patch("memory.fact_store.config")
    def test_failed_load_is_not_marked_loaded(self, mock_config: MagicMock) -> None:
        """読み込み失敗時はロード済みにならず、バックオフ明けに再試行すること"""
        mock_config.STORAGE_TYPE = "firestore"
        mock_config.FACT_STORE_MAX_FACTS_PER_CHANNEL = 100
        clock = _FakeClock()
        store = self._store([StorageLoadError("down"), []], clock)

        store.ensure_loaded(100)
        assert 100 not in store._loaded_channels

        # バックオフ中は I/O を繰り返さない
        store.ensure_loaded(100)
        assert store._load_from_firestore.call_count == 1  # type: ignore[attr-defined]
        assert 100 not in store._loaded_channels

        clock.now = 30
        store.ensure_loaded(100)
        assert 100 in store._loaded_channels
        assert store._load_from_firestore.call_count == 2  # type: ignore[attr-defined]
        assert store._load_backoff.failure_count(100) == 0

    @patch("memory.fact_store.config")
    def test_add_fact_during_failure_does_not_overwrite_storage(self, mock_config: MagicMock) -> None:
        """未ロード中に追加したファクトで永続化先を上書きしないこと"""
        mock_config.STORAGE_TYPE = "firestore"
        mock_config.FACT_STORE_MAX_FACTS_PER_CHANNEL = 100
        store = self._store(StorageLoadError("down"))

        store.add_fact(_fact("new", "新しいファクト"))
        with patch.object(store, "_save_channel", return_value=True) as save:
            store.persist_channel(100)
            store.persist_all()
        save.assert_not_called()
        # dirty は残し、ロード成功後に保存できるようにする
        assert 100 in store._dirty

    @patch("memory.fact_store.config")
    def test_pending_facts_are_merged_after_successful_load(self, mock_config: MagicMock) -> None:
        """ロード成功時に、既存ファクトと未ロード中に追加したファクトがマージされること"""
        mock_config.STORAGE_TYPE = "firestore"
        mock_config.FACT_STORE_MAX_FACTS_PER_CHANNEL = 100
        mock_config.FACT_DECAY_HALF_LIFE_DAYS = 30
        existing = [_fact("old", "既存のファクト")]
        clock = _FakeClock()
        store = self._store([StorageLoadError("down"), existing], clock)

        store.add_fact(_fact("new", "新しいファクト"))
        clock.now = 30
        store.ensure_loaded(100)

        ids = {f.fact_id for f in store._facts[100]}
        assert ids == {"old", "new"}
        with patch.object(store, "_save_channel", return_value=True) as save:
            store.persist_all()
        saved_ids = {f.fact_id for f in save.call_args.args[1]}
        assert saved_ids == {"old", "new"}

    @patch("memory.fact_store.config")
    def test_missing_document_is_normal_load(self, mock_config: MagicMock) -> None:
        """ドキュメント未存在（None）は正常系としてロード済みになること"""
        mock_config.STORAGE_TYPE = "firestore"
        store = self._store([None])

        store.ensure_loaded(100)
        assert 100 in store._loaded_channels

    @patch("memory.fact_store.config")
    def test_cleanup_on_unloaded_channel_does_not_write_storage(self, mock_config: MagicMock) -> None:
        """未ロードのチャンネルで忘却クリーンアップが動いても永続化先を上書きしないこと"""
        mock_config.STORAGE_TYPE = "firestore"
        mock_config.FACT_STORE_MAX_FACTS_PER_CHANNEL = 100
        mock_config.FACT_STORE_CLEANUP_THRESHOLD = 2.0  # スコアは最大1.0なので必ず削除対象
        mock_config.FACT_DECAY_HALF_LIFE_DAYS = 30
        mock_config.FACT_ACCESS_BOOST_WEIGHT = 0.1
        store = self._store(StorageLoadError("down"))
        store.add_fact(_fact("low", "関連度の低いファクト"))

        with (
            patch.object(store, "_archive_facts"),
            patch.object(store, "_save_channel", return_value=True) as save,
        ):
            removed = store.cleanup_low_relevance_facts()

        assert removed == {100: 1}
        save.assert_not_called()
        assert 100 in store._dirty


class TestMergePendingFacts:
    @patch("memory.fact_store.config")
    def test_skips_pending_duplicates_of_loaded_facts(self, mock_config: MagicMock) -> None:
        """既存ファクトと同じ内容の保留ファクトは追加しないこと"""
        mock_config.FACT_DEDUP_SIMILARITY_THRESHOLD = 0.9
        mock_config.FACT_STORE_MAX_FACTS_PER_CHANNEL = 100

        merged = _merge_pending_facts(
            [_fact("old", "同じファクト")],
            [_fact("dup", "同じファクト"), _fact("new", "新しいファクト")],
        )

        assert [f.fact_id for f in merged] == ["old", "new"]

    @patch("memory.fact_store.config")
    def test_trims_lowest_decay_facts_over_limit(self, mock_config: MagicMock) -> None:
        """上限を超えた分は decay_factor の低いもの（古いもの）から削ること"""
        mock_config.FACT_DEDUP_SIMILARITY_THRESHOLD = 0.9
        mock_config.FACT_STORE_MAX_FACTS_PER_CHANNEL = 2
        mock_config.FACT_DECAY_HALF_LIFE_DAYS = 30
        stale = _fact("stale", "古いファクト")
        stale.created_at = datetime(2020, 1, 1, tzinfo=timezone.utc)

        merged = _merge_pending_facts(
            [stale, _fact("old", "既存のファクト")], [_fact("new", "新しいファクト")]
        )

        assert {f.fact_id for f in merged} == {"old", "new"}


class TestUserProfileLoadFailure:
    @patch("memory.user_profile.config")
    def test_failed_load_returns_uncached_profile_and_skips_save(self, mock_config: MagicMock) -> None:
        """読み込み失敗時は一時プロファイルを返し、キャッシュも保存もしないこと"""
        mock_config.STORAGE_TYPE = "firestore"
        mock_config.CHANNELS_ACTIVE_LIMIT = 10
        store = UserProfileStore()
        store._load_profile = MagicMock(side_effect=StorageLoadError("down"))  # type: ignore[method-assign]

        store.record_message(1, 10, 100, "user")

        assert store.get_cached_profile(1, 10) is None
        with patch.object(store, "_save_profile", return_value=True) as save:
            store.persist_all()
        save.assert_not_called()

    @patch("memory.user_profile.config")
    def test_retries_load_on_next_access(self, mock_config: MagicMock) -> None:
        """バックオフ中は再読み込みせず、明けたら再読み込みして既存プロファイルを使うこと"""
        mock_config.STORAGE_TYPE = "firestore"
        stored = UserProfile(user_id=10, display_name="user", guild_id=1, nickname="あだ名")
        clock = _FakeClock()
        store = UserProfileStore()
        store._load_backoff = _backoff(clock)
        store._load_profile = MagicMock(  # type: ignore[method-assign]
            side_effect=[StorageLoadError("down"), stored]
        )

        assert store.get_profile(1, 10, "user").nickname != "あだ名"
        assert store.get_profile(1, 10, "user").nickname != "あだ名"
        assert store._load_profile.call_count == 1  # type: ignore[attr-defined]

        clock.now = 30
        assert store.get_profile(1, 10, "user").nickname == "あだ名"
        assert store.get_cached_profile(1, 10) is stored

    @patch("memory.user_profile.config")
    def test_legacy_load_failure_is_also_treated_as_failure(self, mock_config: MagicMock) -> None:
        """旧形式プロファイルの読み込み失敗でも新規プロファイルをキャッシュしないこと"""
        mock_config.STORAGE_TYPE = "firestore"
        store = UserProfileStore()
        store._load_profile = MagicMock(return_value=None)  # type: ignore[method-assign]
        store._load_legacy_profile = MagicMock(  # type: ignore[method-assign]
            side_effect=StorageLoadError("down")
        )

        store.get_profile(1, 10, "user")
        assert store.get_cached_profile(1, 10) is None

    @patch("memory.user_profile.os.path.exists", return_value=True)
    @patch("builtins.open", side_effect=OSError("read error"))
    def test_local_read_error_raises(self, _open: MagicMock, _exists: MagicMock) -> None:
        """ローカル読み込みエラーは StorageLoadError になること"""
        import pytest

        with pytest.raises(StorageLoadError):
            UserProfileStore()._load_from_local("storage/x.json", 1, 10)


class TestChannelContextLoadFailure:
    @patch("memory.channel_context.config")
    def test_failed_load_returns_uncached_context(self, mock_config: MagicMock) -> None:
        """読み込み失敗時は一時コンテキストを返し、キャッシュしないこと"""
        mock_config.STORAGE_TYPE = "firestore"
        clock = _FakeClock()
        store = ChannelContextStore()
        store._load_backoff = _backoff(clock)
        store._load_context = MagicMock(  # type: ignore[method-assign]
            side_effect=[StorageLoadError("down"), ChannelContext(channel_id=100, summary="既存")]
        )

        ctx = store.get_context(100)
        assert ctx.load_failed is True
        assert 100 not in store.get_all_contexts()

        # バックオフ中は I/O を繰り返さず一時コンテキストを返す
        assert store.get_context(100).load_failed is True
        assert store._load_context.call_count == 1  # type: ignore[attr-defined]

        clock.now = 30
        assert store.get_context(100).summary == "既存"

    @patch("memory.channel_context.config")
    def test_save_refuses_failed_context(self, mock_config: MagicMock) -> None:
        """読み込み失敗した一時コンテキストは保存しないこと"""
        mock_config.STORAGE_TYPE = "firestore"
        store = ChannelContextStore()
        ctx = ChannelContext(channel_id=100, summary="新しい要約", load_failed=True)

        with patch.object(store, "_save_to_firestore") as save:
            store.save_context(ctx)
        save.assert_not_called()
        assert 100 not in store.get_all_contexts()

    def test_load_failed_is_not_serialized(self) -> None:
        """load_failed は永続化データに含まれないこと"""
        assert "load_failed" not in ChannelContext(channel_id=1, load_failed=True).to_dict()


class TestLogStorageLoadFailure:
    @patch("memory.errors.logger")
    def test_traceback_only_on_first_failure(self, mock_logger: MagicMock) -> None:
        """traceback は連続失敗の初回だけ出すこと"""
        log_storage_load_failure("失敗", 1)
        log_storage_load_failure("失敗", 2)

        exc_info_flags = [c.kwargs["exc_info"] for c in mock_logger.warning.call_args_list]
        assert exc_info_flags == [True, False]
