"""記憶ストアの読み込み失敗時に既存データを上書きしないことのテスト（#131）"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from memory.channel_context import ChannelContext, ChannelContextStore
from memory.errors import StorageLoadError
from memory.fact_store import Fact, FactStore
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


class TestFactStoreLoadFailure:
    def _store(self, load_side_effect: object) -> FactStore:
        store = FactStore()
        store._load_from_firestore = MagicMock(side_effect=load_side_effect)  # type: ignore[method-assign]
        return store

    @patch("memory.fact_store.config")
    def test_failed_load_is_not_marked_loaded(self, mock_config: MagicMock) -> None:
        """読み込み失敗時はロード済みにならず、次回アクセスで再試行すること"""
        mock_config.STORAGE_TYPE = "firestore"
        mock_config.FACT_STORE_MAX_FACTS_PER_CHANNEL = 100
        store = self._store([StorageLoadError("down"), []])

        store.ensure_loaded(100)
        assert 100 not in store._loaded_channels

        store.ensure_loaded(100)
        assert 100 in store._loaded_channels
        assert store._load_from_firestore.call_count == 2  # type: ignore[attr-defined]

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
        store = self._store([StorageLoadError("down"), existing])

        store.add_fact(_fact("new", "新しいファクト"))
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
        """次回アクセスで再読み込みし、成功すれば既存プロファイルを使うこと"""
        mock_config.STORAGE_TYPE = "firestore"
        stored = UserProfile(user_id=10, display_name="user", guild_id=1, nickname="あだ名")
        store = UserProfileStore()
        store._load_profile = MagicMock(  # type: ignore[method-assign]
            side_effect=[StorageLoadError("down"), stored]
        )

        assert store.get_profile(1, 10, "user").nickname != "あだ名"
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
        store = ChannelContextStore()
        store._load_context = MagicMock(  # type: ignore[method-assign]
            side_effect=[StorageLoadError("down"), ChannelContext(channel_id=100, summary="既存")]
        )

        ctx = store.get_context(100)
        assert ctx.load_failed is True
        assert 100 not in store.get_all_contexts()

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
