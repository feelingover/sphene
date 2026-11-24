"""記憶ストアのキャッシュ追い出し（LRU / TTL）のテスト"""

# type: ignore
# mypy: ignore-errors

from datetime import datetime, timedelta, timezone

import pytest

import config
from memory.backoff import FailureBackoff
from memory.cache_eviction import LruTracker
from memory.channel_context import ChannelContextStore
from memory.fact_store import Fact, FactStore
from memory.judge import RuleBasedJudge
from memory.user_profile import UserProfileStore

MIN_IDLE = 100


class FakeClock:
    """手動で進める単調時計"""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture(autouse=True)
def local_storage(tmp_path, monkeypatch):
    """ローカルストレージを一時ディレクトリに向け、追い出し設定を小さくする"""
    monkeypatch.setattr(config, "STORAGE_TYPE", "local")
    monkeypatch.setattr(config, "LOCAL_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "MEMORY_CACHE_MIN_IDLE_SECONDS", MIN_IDLE)
    monkeypatch.setattr(config, "USER_PROFILE_CACHE_MAX_ENTRIES", 1)
    monkeypatch.setattr(config, "FACT_STORE_CACHE_MAX_CHANNELS", 1)
    monkeypatch.setattr(config, "CHANNEL_CONTEXT_CACHE_MAX_ENTRIES", 1)
    return tmp_path


class TestLruTracker:
    def test_candidates_are_oldest_first_and_limited_to_excess(self, clock):
        lru = LruTracker(clock=clock)
        for key in ("a", "b", "c"):
            lru.touch(key)
        clock.advance(MIN_IDLE)
        assert lru.eviction_candidates(1, MIN_IDLE, lambda k: False) == ["a", "b"]

    def test_touch_moves_key_to_newest(self, clock):
        lru = LruTracker(clock=clock)
        for key in ("a", "b", "c"):
            lru.touch(key)
        lru.touch("a")
        clock.advance(MIN_IDLE)
        assert lru.eviction_candidates(2, MIN_IDLE, lambda k: False) == ["b"]

    def test_protected_keys_are_skipped(self, clock):
        lru = LruTracker(clock=clock)
        for key in ("a", "b", "c"):
            lru.touch(key)
        clock.advance(MIN_IDLE)
        assert lru.eviction_candidates(1, MIN_IDLE, lambda k: k == "a") == ["b", "c"]

    def test_recently_accessed_keys_are_not_candidates(self, clock):
        lru = LruTracker(clock=clock)
        lru.touch("a")
        clock.advance(MIN_IDLE)
        lru.touch("b")
        assert lru.eviction_candidates(0, MIN_IDLE, lambda k: False) == ["a"]

    def test_under_limit_returns_nothing(self, clock):
        lru = LruTracker(clock=clock)
        lru.touch("a")
        clock.advance(MIN_IDLE)
        assert lru.eviction_candidates(1, MIN_IDLE, lambda k: False) == []


def _profile_store(clock: FakeClock) -> UserProfileStore:
    store = UserProfileStore()
    store._lru = LruTracker(clock=clock)
    return store


class TestUserProfileEviction:
    def test_evicts_saved_profiles_past_limit(self, clock):
        store = _profile_store(clock)
        for uid in (1, 2, 3):
            store.record_message(10, uid, 100, f"user{uid}")
        store.persist_all()
        clock.advance(MIN_IDLE)

        assert store.prune() == 2
        assert store.get_cached_profile(10, 1) is None
        assert store.get_cached_profile(10, 2) is None
        assert store.get_cached_profile(10, 3) is not None
        # 保存ロックもプロファイルと一緒に破棄される
        assert len(store._save_locks) == 1

    def test_dirty_profiles_are_not_evicted(self, clock):
        store = _profile_store(clock)
        for uid in (1, 2):
            store.record_message(10, uid, 100, f"user{uid}")
        clock.advance(MIN_IDLE)

        assert store.prune() == 0
        assert store.get_cached_profile(10, 1) is not None

    def test_profile_being_saved_is_not_evicted(self, clock):
        store = _profile_store(clock)
        for uid in (1, 2):
            store.record_message(10, uid, 100, f"user{uid}")
        store.persist_all()
        clock.advance(MIN_IDLE)

        with store._save_locks.get((10, 1)):
            assert store.prune() == 0
        assert store.get_cached_profile(10, 1) is not None

    def test_recently_accessed_profile_is_not_evicted(self, clock):
        store = _profile_store(clock)
        for uid in (1, 2):
            store.record_message(10, uid, 100, f"user{uid}")
        store.persist_all()
        clock.advance(MIN_IDLE)
        store.get_profile(10, 1)
        store.get_profile(10, 2)

        assert store.prune() == 0

    def test_evicted_profile_reloads_from_storage(self, clock):
        store = _profile_store(clock)
        for _ in range(3):
            store.record_message(10, 1, 100, "user1")
        store.record_message(10, 2, 100, "user2")
        store.persist_all()
        clock.advance(MIN_IDLE)
        assert store.prune() == 1

        profile = store.get_profile(10, 1)
        assert profile.interaction_count == 3
        assert store.get_cached_profile(10, 1) is not None


def _fact(channel_id: int, content: str) -> Fact:
    return Fact(
        fact_id=f"{channel_id}-{content}",
        channel_id=channel_id,
        content=content,
        keywords=[content],
        source_user_ids=[1],
        created_at=datetime.now(timezone.utc),
    )


def _fact_store(clock: FakeClock) -> FactStore:
    store = FactStore()
    store._lru = LruTracker(clock=clock)
    return store


class TestFactStoreEviction:
    def test_evicts_saved_channels_past_limit(self, clock):
        store = _fact_store(clock)
        for cid in (1, 2, 3):
            store.add_fact(_fact(cid, f"topic{cid}"))
        store.persist_all()
        clock.advance(MIN_IDLE)

        assert store.prune() == 2
        assert set(store._facts) == {3}
        assert store._loaded_channels == {3}
        assert len(store._save_locks) == 1

    def test_dirty_channel_is_not_evicted(self, clock):
        store = _fact_store(clock)
        for cid in (1, 2):
            store.add_fact(_fact(cid, f"topic{cid}"))
        clock.advance(MIN_IDLE)

        assert store.prune() == 0
        assert set(store._facts) == {1, 2}

    def test_channel_being_saved_is_not_evicted(self, clock):
        store = _fact_store(clock)
        for cid in (1, 2):
            store.add_fact(_fact(cid, f"topic{cid}"))
        store.persist_all()
        clock.advance(MIN_IDLE)

        with store._save_locks.get(1):
            assert store.prune() == 0
        assert 1 in store._loaded_channels

    def test_pending_facts_of_unloaded_channel_are_kept(self, clock):
        store = _fact_store(clock)
        for cid in (1, 2):
            store.add_fact(_fact(cid, f"topic{cid}"))
        store.persist_all()
        # 読み込み失敗中に追加された保留ファクトを模す（dirty は保存試行で外れた状態）
        store._loaded_channels.discard(1)
        clock.advance(MIN_IDLE)

        assert store._is_pinned(1)
        store.prune()
        assert 1 in store._facts

    def test_evicted_channel_reloads_from_storage(self, clock):
        store = _fact_store(clock)
        store.add_fact(_fact(1, "ラーメン"))
        store.add_fact(_fact(2, "カレー"))
        store.persist_all()
        clock.advance(MIN_IDLE)
        assert store.prune() == 1
        assert 1 not in store._loaded_channels

        results = store.search(1, ["ラーメン"])
        assert [f.content for f in results] == ["ラーメン"]
        assert 1 in store._loaded_channels


def _context_store(clock: FakeClock) -> ChannelContextStore:
    store = ChannelContextStore()
    store._lru = LruTracker(clock=clock)
    return store


def _saved_context(store: ChannelContextStore, channel_id: int, summary: str) -> None:
    ctx = store.get_context(channel_id)
    ctx.summary = summary
    assert store.save_context(ctx)


class TestChannelContextEviction:
    def test_evicts_saved_contexts_past_limit(self, clock):
        store = _context_store(clock)
        for cid in (1, 2, 3):
            _saved_context(store, cid, f"summary{cid}")
        clock.advance(MIN_IDLE)

        assert store.prune() == 2
        assert set(store.get_all_contexts()) == {3}

    def test_dirty_or_pending_count_context_is_not_evicted(self, clock):
        store = _context_store(clock)
        _saved_context(store, 1, "summary1")
        _saved_context(store, 2, "summary2")
        store.get_context(1).increment_message_count()
        ctx2 = store.get_context(2)
        ctx2.message_count_since_update = 3  # 永続化済みでも要約待ちのカウントがある
        clock.advance(MIN_IDLE)

        assert store.prune() == 0
        assert set(store.get_all_contexts()) == {1, 2}

    def test_context_being_saved_is_not_evicted(self, clock):
        store = _context_store(clock)
        _saved_context(store, 1, "summary1")
        _saved_context(store, 2, "summary2")
        clock.advance(MIN_IDLE)
        store._saving[1] = 1

        assert store.prune() == 1
        assert set(store.get_all_contexts()) == {1}

    def test_evicted_context_reloads_from_storage(self, clock):
        store = _context_store(clock)
        _saved_context(store, 1, "summary1")
        _saved_context(store, 2, "summary2")
        clock.advance(MIN_IDLE)
        assert store.prune() == 1

        assert store.get_context(1).summary == "summary1"
        assert 1 in store.get_all_contexts()


class TestJudgePrune:
    @pytest.fixture(autouse=True)
    def judge_config(self, monkeypatch):
        monkeypatch.setattr(config, "COOLDOWN_SECONDS", 120)
        monkeypatch.setattr(config, "ENGAGEMENT_DURATION_SECONDS", 300)

    def test_prune_drops_entries_older_than_ttl(self):
        judge = RuleBasedJudge()
        now = datetime.now(timezone.utc)
        judge._last_response_times = {
            1: now - timedelta(seconds=301),
            2: now - timedelta(seconds=200),  # エンゲージメント期間中なので残す
        }
        assert judge.prune(now) == 1
        assert set(judge._last_response_times) == {2}
        assert judge._is_engaged(2)

    def test_record_response_prunes_periodically(self):
        judge = RuleBasedJudge()
        now = datetime.now(timezone.utc)
        judge._last_response_times = {1: now - timedelta(seconds=1000)}
        judge._last_prune = now - timedelta(seconds=300)

        judge.record_response(2)
        assert set(judge._last_response_times) == {2}

    def test_record_response_skips_prune_within_interval(self):
        judge = RuleBasedJudge()
        now = datetime.now(timezone.utc)
        judge._last_response_times = {1: now - timedelta(seconds=1000)}
        judge._last_prune = now

        judge.record_response(2)
        assert set(judge._last_response_times) == {1, 2}


class TestBackoffPrune:
    def test_prune_drops_states_long_past_retry_at(self, clock):
        backoff = FailureBackoff(10, 100, clock=clock)
        backoff.record_failure("old")
        clock.advance(50)
        backoff.record_failure("recent")
        clock.advance(60)  # old は retry_at から max_seconds 経過、recent は未経過

        assert backoff.prune() == 1
        assert backoff.failure_count("old") == 0
        assert backoff.failure_count("recent") == 1

    def test_blocked_state_is_kept(self, clock):
        backoff = FailureBackoff(10, 100, clock=clock)
        for _ in range(5):
            backoff.record_failure("key")
        clock.advance(99)
        assert backoff.prune() == 0
        assert backoff.is_blocked("key")

    def test_failure_after_prune_restarts_from_base_delay(self, clock):
        backoff = FailureBackoff(10, 100, clock=clock)
        backoff.record_failure("key")
        backoff.record_failure("key")
        clock.advance(20 + 100)
        backoff.prune()

        assert backoff.record_failure("key") == 1
        clock.advance(10)
        assert not backoff.is_blocked("key")

    def test_record_failure_prunes_periodically(self, clock):
        backoff = FailureBackoff(10, 100, clock=clock)
        backoff.record_failure("old")
        clock.advance(10 + 100)

        backoff.record_failure("new")
        assert backoff.failure_count("old") == 0
        assert backoff.failure_count("new") == 1


class TestPruneMemoryCachesTask:
    @pytest.mark.asyncio
    async def test_prunes_all_stores_even_if_one_fails(self):
        from unittest.mock import MagicMock, patch

        from bot.discord_bot import _prune_memory_caches

        profiles, facts, contexts = MagicMock(), MagicMock(), MagicMock()
        profiles.prune.side_effect = RuntimeError("boom")
        facts.prune.return_value = 2
        contexts.prune.return_value = 0
        with (
            patch("memory.user_profile.get_user_profile_store", return_value=profiles),
            patch("memory.fact_store.get_fact_store", return_value=facts),
            patch("memory.channel_context.get_channel_context_store", return_value=contexts),
        ):
            await _prune_memory_caches()

        profiles.prune.assert_called_once()
        facts.prune.assert_called_once()
        contexts.prune.assert_called_once()
