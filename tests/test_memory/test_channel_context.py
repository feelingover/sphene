"""チャンネルコンテキストのテスト"""

# type: ignore
# mypy: ignore-errors

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, mock_open, patch

import pytest

from memory.channel_context import (
    ChannelContext,
    ChannelContextStore,
    get_channel_context_store,
)


class TestChannelContextDefaults:
    """ChannelContextのデフォルト値テスト"""

    def test_defaults(self):
        """全フィールドが正しいデフォルト値を持つこと"""
        ctx = ChannelContext(channel_id=123)
        assert ctx.channel_id == 123
        assert ctx.summary == ""
        assert ctx.mood == ""
        assert ctx.topic_keywords == []
        assert ctx.active_users == []
        assert isinstance(ctx.last_updated, datetime)
        assert ctx.last_updated.tzinfo == timezone.utc
        assert ctx.message_count_since_update == 0

    def test_custom_values(self):
        """カスタム値が正しく設定されること"""
        now = datetime.now(timezone.utc)
        ctx = ChannelContext(
            channel_id=456,
            summary="テスト要約",
            mood="楽しい",
            topic_keywords=["Python", "テスト"],
            active_users=["UserA", "UserB"],
            last_updated=now,
            message_count_since_update=5,
        )
        assert ctx.channel_id == 456
        assert ctx.summary == "テスト要約"
        assert ctx.mood == "楽しい"
        assert ctx.topic_keywords == ["Python", "テスト"]
        assert ctx.active_users == ["UserA", "UserB"]
        assert ctx.last_updated == now
        assert ctx.message_count_since_update == 5


class TestIncrementMessageCount:
    """increment_message_countのテスト"""

    def test_increment(self):
        """カウンタが1ずつ増加すること"""
        ctx = ChannelContext(channel_id=100)
        assert ctx.message_count_since_update == 0

        ctx.increment_message_count()
        assert ctx.message_count_since_update == 1

        ctx.increment_message_count()
        assert ctx.message_count_since_update == 2

    def test_increment_from_nonzero(self):
        """初期値が0以外でも正しくインクリメントされること"""
        ctx = ChannelContext(channel_id=100, message_count_since_update=10)
        ctx.increment_message_count()
        assert ctx.message_count_since_update == 11


class TestShouldSummarizeByCount:
    """should_summarize_by_countのテスト"""

    @patch("memory.channel_context.config")
    def test_true_when_count_meets_threshold(self, mock_config):
        """カウントが閾値以上でTrueを返すこと"""
        mock_config.SUMMARIZE_EVERY_N_MESSAGES = 20
        ctx = ChannelContext(channel_id=100, message_count_since_update=20)
        assert ctx.should_summarize_by_count() is True

    @patch("memory.channel_context.config")
    def test_true_when_count_exceeds_threshold(self, mock_config):
        """カウントが閾値を超えてもTrueを返すこと"""
        mock_config.SUMMARIZE_EVERY_N_MESSAGES = 20
        ctx = ChannelContext(channel_id=100, message_count_since_update=25)
        assert ctx.should_summarize_by_count() is True

    @patch("memory.channel_context.config")
    def test_false_when_count_below_threshold(self, mock_config):
        """カウントが閾値未満でFalseを返すこと"""
        mock_config.SUMMARIZE_EVERY_N_MESSAGES = 20
        ctx = ChannelContext(channel_id=100, message_count_since_update=19)
        assert ctx.should_summarize_by_count() is False

    @patch("memory.channel_context.config")
    def test_false_when_count_zero(self, mock_config):
        """カウントが0でFalseを返すこと"""
        mock_config.SUMMARIZE_EVERY_N_MESSAGES = 20
        ctx = ChannelContext(channel_id=100, message_count_since_update=0)
        assert ctx.should_summarize_by_count() is False


class TestShouldSummarizeByTime:
    """should_summarize_by_timeのテスト"""

    @patch("memory.channel_context.config")
    def test_true_when_elapsed_meets_threshold(self, mock_config):
        """経過時間が閾値以上かつメッセージ数>0でTrueを返すこと"""
        mock_config.SUMMARIZE_EVERY_N_MINUTES = 15
        ctx = ChannelContext(
            channel_id=100,
            message_count_since_update=1,
            last_updated=datetime.now(timezone.utc) - timedelta(minutes=16),
        )
        assert ctx.should_summarize_by_time() is True

    @patch("memory.channel_context.config")
    def test_false_when_elapsed_below_threshold(self, mock_config):
        """経過時間が閾値未満でFalseを返すこと"""
        mock_config.SUMMARIZE_EVERY_N_MINUTES = 15
        ctx = ChannelContext(
            channel_id=100,
            message_count_since_update=5,
            last_updated=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        assert ctx.should_summarize_by_time() is False

    @patch("memory.channel_context.config")
    def test_false_when_count_zero(self, mock_config):
        """メッセージ数が0のとき、時間超過してもFalseを返すこと"""
        mock_config.SUMMARIZE_EVERY_N_MINUTES = 15
        ctx = ChannelContext(
            channel_id=100,
            message_count_since_update=0,
            last_updated=datetime.now(timezone.utc) - timedelta(minutes=30),
        )
        assert ctx.should_summarize_by_time() is False


class TestShouldSummarize:
    """should_summarizeのテスト（ハイブリッド判定）"""

    @patch("memory.channel_context.config")
    def test_true_when_count_triggers(self, mock_config):
        """カウント条件のみでTrueを返すこと"""
        mock_config.SUMMARIZE_EVERY_N_MESSAGES = 10
        mock_config.SUMMARIZE_EVERY_N_MINUTES = 60
        ctx = ChannelContext(
            channel_id=100,
            message_count_since_update=10,
            last_updated=datetime.now(timezone.utc),  # 時間条件は満たさない
        )
        assert ctx.should_summarize() is True

    @patch("memory.channel_context.config")
    def test_true_when_time_triggers(self, mock_config):
        """時間条件のみでTrueを返すこと"""
        mock_config.SUMMARIZE_EVERY_N_MESSAGES = 100
        mock_config.SUMMARIZE_EVERY_N_MINUTES = 15
        ctx = ChannelContext(
            channel_id=100,
            message_count_since_update=1,  # カウント条件は満たさない
            last_updated=datetime.now(timezone.utc) - timedelta(minutes=20),
        )
        assert ctx.should_summarize() is True

    @patch("memory.channel_context.config")
    def test_true_when_both_trigger(self, mock_config):
        """両方の条件を満たしてもTrueを返すこと"""
        mock_config.SUMMARIZE_EVERY_N_MESSAGES = 10
        mock_config.SUMMARIZE_EVERY_N_MINUTES = 15
        ctx = ChannelContext(
            channel_id=100,
            message_count_since_update=20,
            last_updated=datetime.now(timezone.utc) - timedelta(minutes=30),
        )
        assert ctx.should_summarize() is True

    @patch("memory.channel_context.config")
    def test_false_when_neither_triggers(self, mock_config):
        """両方の条件を満たさないときFalseを返すこと"""
        mock_config.SUMMARIZE_EVERY_N_MESSAGES = 100
        mock_config.SUMMARIZE_EVERY_N_MINUTES = 60
        ctx = ChannelContext(
            channel_id=100,
            message_count_since_update=5,
            last_updated=datetime.now(timezone.utc),
        )
        assert ctx.should_summarize() is False


class TestFormatForInjection:
    """format_for_injectionのテスト"""

    def test_empty_when_no_summary(self):
        """summaryが空の場合、空文字列を返すこと"""
        ctx = ChannelContext(
            channel_id=100,
            mood="楽しい",
            topic_keywords=["Python"],
            active_users=["UserA"],
        )
        assert ctx.format_for_injection() == ""

    def test_full_format(self):
        """全フィールドが設定されている場合のフォーマット"""
        ctx = ChannelContext(
            channel_id=100,
            summary="テストの要約です",
            mood="和やか",
            topic_keywords=["Python", "テスト"],
            active_users=["UserA", "UserB"],
        )
        result = ctx.format_for_injection()
        assert "【チャンネルの状況】" in result
        assert "テストの要約です" in result
        assert "雰囲気: 和やか" in result
        assert "話題: Python, テスト" in result
        assert "参加者: UserA, UserB" in result

    def test_summary_only(self):
        """summaryのみ設定されている場合"""
        ctx = ChannelContext(channel_id=100, summary="要約だけ")
        result = ctx.format_for_injection()
        assert "【チャンネルの状況】" in result
        assert "要約だけ" in result
        assert "雰囲気:" not in result
        assert "話題:" not in result
        assert "参加者:" not in result

    def test_partial_fields(self):
        """一部のフィールドのみ設定されている場合"""
        ctx = ChannelContext(
            channel_id=100,
            summary="部分的な要約",
            mood="",
            topic_keywords=["ゲーム"],
            active_users=[],
        )
        result = ctx.format_for_injection()
        assert "【チャンネルの状況】" in result
        assert "部分的な要約" in result
        assert "雰囲気:" not in result
        assert "話題: ゲーム" in result
        assert "参加者:" not in result


class TestToDictFromDict:
    """to_dict / from_dictのラウンドトリップテスト"""

    def test_roundtrip(self):
        """to_dictとfrom_dictでデータが保持されること"""
        now = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        original = ChannelContext(
            channel_id=789,
            summary="ラウンドトリップテスト",
            mood="テスト中",
            topic_keywords=["A", "B"],
            active_users=["User1", "User2"],
            last_updated=now,
            message_count_since_update=42,
        )
        data = original.to_dict()
        restored = ChannelContext.from_dict(data)

        assert restored.channel_id == original.channel_id
        assert restored.summary == original.summary
        assert restored.mood == original.mood
        assert restored.topic_keywords == original.topic_keywords
        assert restored.active_users == original.active_users
        assert restored.last_updated == original.last_updated
        assert restored.message_count_since_update == original.message_count_since_update

    def test_to_dict_contains_all_keys(self):
        """to_dictが必要な全キーを含むこと"""
        ctx = ChannelContext(channel_id=100)
        data = ctx.to_dict()
        expected_keys = {
            "channel_id",
            "summary",
            "mood",
            "topic_keywords",
            "active_users",
            "last_updated",
            "message_count_since_update",
        }
        assert set(data.keys()) == expected_keys

    def test_to_dict_last_updated_is_isoformat(self):
        """last_updatedがISO形式文字列であること"""
        ctx = ChannelContext(channel_id=100)
        data = ctx.to_dict()
        assert isinstance(data["last_updated"], str)
        # パース可能であることを確認
        datetime.fromisoformat(data["last_updated"])

    def test_from_dict_with_missing_optional_fields(self):
        """オプショナルフィールドが欠損している辞書からも復元できること"""
        data = {"channel_id": 100}
        ctx = ChannelContext.from_dict(data)
        assert ctx.channel_id == 100
        assert ctx.summary == ""
        assert ctx.mood == ""
        assert ctx.topic_keywords == []
        assert ctx.active_users == []
        assert isinstance(ctx.last_updated, datetime)
        assert ctx.message_count_since_update == 0

    def test_from_dict_with_none_last_updated(self):
        """last_updatedがNoneの場合、現在時刻が設定されること"""
        data = {"channel_id": 100, "last_updated": None}
        ctx = ChannelContext.from_dict(data)
        assert isinstance(ctx.last_updated, datetime)
        assert ctx.last_updated.tzinfo == timezone.utc

    def test_from_dict_with_string_last_updated(self):
        """last_updatedが文字列の場合、正しくパースされること"""
        data = {
            "channel_id": 100,
            "last_updated": "2025-06-15T12:00:00+00:00",
        }
        ctx = ChannelContext.from_dict(data)
        assert ctx.last_updated == datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


class TestChannelContextStore:
    """ChannelContextStoreのテスト"""

    @patch("memory.channel_context.config")
    def test_get_context_returns_new_context(self, mock_config):
        """存在しないチャンネルIDで新しいコンテキストが作成されること"""
        mock_config.CHANNEL_CONTEXT_STORAGE_TYPE = "memory"
        store = ChannelContextStore()
        ctx = store.get_context(100)
        assert ctx.channel_id == 100
        assert ctx.summary == ""
        assert ctx.message_count_since_update == 0

    @patch("memory.channel_context.config")
    def test_get_context_caches(self, mock_config):
        """同じチャンネルIDで同一オブジェクトがキャッシュから返されること"""
        mock_config.CHANNEL_CONTEXT_STORAGE_TYPE = "memory"
        store = ChannelContextStore()
        ctx1 = store.get_context(100)
        ctx1.summary = "キャッシュテスト"
        ctx2 = store.get_context(100)
        assert ctx2 is ctx1
        assert ctx2.summary == "キャッシュテスト"

    @patch("memory.channel_context.config")
    def test_get_context_different_channels(self, mock_config):
        """異なるチャンネルIDで別のコンテキストが返されること"""
        mock_config.CHANNEL_CONTEXT_STORAGE_TYPE = "memory"
        store = ChannelContextStore()
        ctx1 = store.get_context(100)
        ctx2 = store.get_context(200)
        assert ctx1 is not ctx2
        assert ctx1.channel_id == 100
        assert ctx2.channel_id == 200

    @patch("memory.channel_context.config")
    def test_save_context_memory_noop(self, mock_config):
        """storage_type=memoryの場合、インメモリキャッシュのみ更新すること"""
        mock_config.CHANNEL_CONTEXT_STORAGE_TYPE = "memory"
        store = ChannelContextStore()
        ctx = ChannelContext(channel_id=100, summary="保存テスト")
        store.save_context(ctx)
        # インメモリキャッシュに反映されていること
        cached = store.get_context(100)
        assert cached.summary == "保存テスト"
        assert cached is ctx

    @patch("memory.channel_context.config")
    def test_save_context_local_calls_save_to_local(self, mock_config):
        """storage_type=localの場合、_save_to_localが呼ばれること"""
        mock_config.CHANNEL_CONTEXT_STORAGE_TYPE = "local"
        store = ChannelContextStore()
        ctx = ChannelContext(channel_id=100, summary="ローカル保存")

        with patch.object(store, "_save_to_local") as mock_save:
            store.save_context(ctx)
            mock_save.assert_called_once_with(ctx)

    @patch("memory.channel_context.config")
    def test_save_context_firestore_calls_save_to_firestore(self, mock_config):
        """storage_type=firestoreの場合、_save_to_firestoreが呼ばれること"""
        mock_config.CHANNEL_CONTEXT_STORAGE_TYPE = "firestore"
        store = ChannelContextStore()
        ctx = ChannelContext(channel_id=100, summary="Firestore保存")

        with patch.object(store, "_save_to_firestore") as mock_save:
            store.save_context(ctx)
            mock_save.assert_called_once_with(ctx)

    @patch("memory.channel_context.config")
    def test_save_context_updates_cache(self, mock_config):
        """save_contextがインメモリキャッシュを更新すること"""
        mock_config.CHANNEL_CONTEXT_STORAGE_TYPE = "memory"
        store = ChannelContextStore()
        ctx = ChannelContext(channel_id=100, summary="新しい要約")
        store.save_context(ctx)
        assert store._contexts[100] is ctx

    @patch("memory.channel_context.config")
    def test_load_context_from_local(self, mock_config):
        """ローカルファイルからコンテキストを読み込めること"""
        mock_config.CHANNEL_CONTEXT_STORAGE_TYPE = "local"
        store = ChannelContextStore()

        stored_data = {
            "channel_id": 100,
            "summary": "ファイルから復元",
            "mood": "テスト",
            "topic_keywords": [],
            "active_users": [],
            "last_updated": "2025-06-15T12:00:00+00:00",
            "message_count_since_update": 3,
        }

        with patch("memory.channel_context.os.path.exists", return_value=True), \
             patch("builtins.open", mock_open(read_data='{"channel_id": 100, "summary": "ファイルから復元", "mood": "テスト", "topic_keywords": [], "active_users": [], "last_updated": "2025-06-15T12:00:00+00:00", "message_count_since_update": 3}')):
            ctx = store.get_context(100)
            assert ctx.summary == "ファイルから復元"
            assert ctx.mood == "テスト"
            assert ctx.message_count_since_update == 3

    @patch("memory.channel_context.config")
    def test_load_context_local_file_not_found(self, mock_config):
        """ローカルファイルが存在しない場合、新規コンテキストが作成されること"""
        mock_config.CHANNEL_CONTEXT_STORAGE_TYPE = "local"
        store = ChannelContextStore()

        with patch("memory.channel_context.os.path.exists", return_value=False):
            ctx = store.get_context(999)
            assert ctx.channel_id == 999
            assert ctx.summary == ""

    @patch("memory.channel_context.config")
    def test_load_context_local_read_error(self, mock_config):
        """ローカルファイル読み込みエラー時にNoneが返り新規作成されること"""
        mock_config.CHANNEL_CONTEXT_STORAGE_TYPE = "local"
        store = ChannelContextStore()

        with patch("memory.channel_context.os.path.exists", return_value=True), \
             patch("builtins.open", side_effect=OSError("read error")):
            ctx = store.get_context(100)
            assert ctx.channel_id == 100
            assert ctx.summary == ""


class TestGetChannelContextStore:
    """get_channel_context_storeシングルトンのテスト"""

    @patch("memory.channel_context.config")
    def test_singleton(self, mock_config):
        """同一インスタンスが返されること"""
        mock_config.CHANNEL_CONTEXT_STORAGE_TYPE = "memory"
        import memory.channel_context as mod

        mod._store = None  # シングルトンをリセット
        store1 = get_channel_context_store()
        store2 = get_channel_context_store()
        assert store1 is store2
        mod._store = None  # テスト後にクリーンアップ

    @patch("memory.channel_context.config")
    def test_creates_new_instance_when_none(self, mock_config):
        """_storeがNoneの場合に新しいインスタンスが作成されること"""
        mock_config.CHANNEL_CONTEXT_STORAGE_TYPE = "memory"
        import memory.channel_context as mod

        mod._store = None
        store = get_channel_context_store()
        assert isinstance(store, ChannelContextStore)
        mod._store = None  # テスト後にクリーンアップ
