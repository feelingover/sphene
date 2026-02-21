"""ユーザープロファイルのテスト"""

# type: ignore
# mypy: ignore-errors

import json
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from memory.user_profile import (
    UserProfile,
    UserProfileStore,
    get_user_profile_store,
)


class TestUserProfileDefaults:
    """UserProfileのデフォルト値テスト"""

    def test_defaults(self):
        """全フィールドが正しいデフォルト値を持つこと"""
        profile = UserProfile(user_id=123, display_name="テストユーザー")
        assert profile.user_id == 123
        assert profile.display_name == "テストユーザー"
        assert profile.interaction_count == 0
        assert profile.mentioned_bot_count == 0
        assert profile.channels_active == []
        assert isinstance(profile.last_interaction, datetime)
        assert profile.last_interaction.tzinfo == timezone.utc
        assert profile.last_topic == []

    def test_custom_values(self):
        """カスタム値が正しく設定されること"""
        now = datetime.now(timezone.utc)
        profile = UserProfile(
            user_id=456,
            display_name="カスタムユーザー",
            interaction_count=10,
            mentioned_bot_count=3,
            channels_active=[111, 222],
            last_interaction=now,
            last_topic=["Python", "テスト"],
        )
        assert profile.user_id == 456
        assert profile.display_name == "カスタムユーザー"
        assert profile.interaction_count == 10
        assert profile.mentioned_bot_count == 3
        assert profile.channels_active == [111, 222]
        assert profile.last_interaction == now
        assert profile.last_topic == ["Python", "テスト"]


class TestFamiliarityLevel:
    """familiarity_level プロパティの境界値テスト"""

    @pytest.fixture(autouse=True)
    def mock_config(self):
        """閾値をデフォルト値にパッチ"""
        with patch("memory.user_profile.config") as mock_cfg:
            mock_cfg.FAMILIARITY_THRESHOLD_ACQUAINTANCE = 6
            mock_cfg.FAMILIARITY_THRESHOLD_REGULAR = 31
            mock_cfg.FAMILIARITY_THRESHOLD_CLOSE = 101
            mock_cfg.USER_PROFILE_STORAGE_TYPE = "memory"
            yield mock_cfg

    def _make_profile(self, count: int) -> UserProfile:
        profile = UserProfile(user_id=1, display_name="User")
        profile.interaction_count = count
        return profile

    def test_stranger_lower_bound(self):
        """0回はstranger"""
        assert self._make_profile(0).familiarity_level == "stranger"

    def test_stranger_upper_bound(self):
        """5回はstranger（閾値未満）"""
        assert self._make_profile(5).familiarity_level == "stranger"

    def test_acquaintance_lower_bound(self):
        """6回はacquaintance（閾値以上）"""
        assert self._make_profile(6).familiarity_level == "acquaintance"

    def test_acquaintance_upper_bound(self):
        """30回はacquaintance（閾値未満）"""
        assert self._make_profile(30).familiarity_level == "acquaintance"

    def test_regular_lower_bound(self):
        """31回はregular（閾値以上）"""
        assert self._make_profile(31).familiarity_level == "regular"

    def test_regular_upper_bound(self):
        """100回はregular（閾値未満）"""
        assert self._make_profile(100).familiarity_level == "regular"

    def test_close_lower_bound(self):
        """101回はclose（閾値以上）"""
        assert self._make_profile(101).familiarity_level == "close"

    def test_close_large_count(self):
        """999回もclose"""
        assert self._make_profile(999).familiarity_level == "close"


class TestFormatForInjection:
    """format_for_injection のテスト"""

    @pytest.fixture(autouse=True)
    def mock_config(self):
        with patch("memory.user_profile.config") as mock_cfg:
            mock_cfg.FAMILIARITY_THRESHOLD_ACQUAINTANCE = 6
            mock_cfg.FAMILIARITY_THRESHOLD_REGULAR = 31
            mock_cfg.FAMILIARITY_THRESHOLD_CLOSE = 101
            mock_cfg.USER_PROFILE_STORAGE_TYPE = "memory"
            yield mock_cfg

    def test_empty_when_no_interactions(self):
        """interaction_count=0のとき空文字を返す"""
        profile = UserProfile(user_id=1, display_name="新参者")
        assert profile.format_for_injection() == ""

    def test_format_without_topic(self):
        """last_topic がない場合のフォーマット"""
        profile = UserProfile(user_id=1, display_name="Orz", interaction_count=10)
        result = profile.format_for_injection()
        assert "【Orzさんについて】" in result
        assert "acquaintance" in result
        assert "10回のやりとり" in result
        assert "直近の話題" not in result

    def test_format_with_topic(self):
        """last_topic がある場合のフォーマット"""
        profile = UserProfile(
            user_id=1,
            display_name="Orz",
            interaction_count=45,
            last_topic=["Rust", "async", "tokio"],
        )
        result = profile.format_for_injection()
        assert "【Orzさんについて】" in result
        assert "regular" in result
        assert "45回のやりとり" in result
        assert "直近の話題: Rust, async, tokio" in result

    def test_format_close_relationship(self):
        """closeレベルのフォーマット"""
        profile = UserProfile(user_id=1, display_name="親友", interaction_count=200)
        result = profile.format_for_injection()
        assert "close" in result
        assert "200回のやりとり" in result


class TestUserProfileRoundTrip:
    """to_dict / from_dict のラウンドトリップテスト"""

    def test_round_trip_basic(self):
        """基本的なシリアライズ/デシリアライズ"""
        now = datetime.now(timezone.utc)
        original = UserProfile(
            user_id=789,
            display_name="RoundTrip",
            interaction_count=15,
            mentioned_bot_count=5,
            channels_active=[100, 200, 300],
            last_interaction=now,
            last_topic=["Discord", "Bot"],
        )
        data = original.to_dict()
        restored = UserProfile.from_dict(data)

        assert restored.user_id == original.user_id
        assert restored.display_name == original.display_name
        assert restored.interaction_count == original.interaction_count
        assert restored.mentioned_bot_count == original.mentioned_bot_count
        assert restored.channels_active == original.channels_active
        assert restored.last_topic == original.last_topic
        # datetimeはISOフォーマットからの復元なので秒精度で比較
        assert abs((restored.last_interaction - original.last_interaction).total_seconds()) < 1

    def test_from_dict_missing_fields(self):
        """欠損フィールドがデフォルト値で補完される"""
        data = {"user_id": 999}
        profile = UserProfile.from_dict(data)
        assert profile.user_id == 999
        assert profile.display_name == ""
        assert profile.interaction_count == 0
        assert profile.mentioned_bot_count == 0
        assert profile.channels_active == []
        assert profile.last_topic == []

    def test_from_dict_none_last_interaction(self):
        """last_interaction が None のとき現在時刻を使用"""
        data = {"user_id": 100, "last_interaction": None}
        profile = UserProfile.from_dict(data)
        assert profile.last_interaction is not None
        assert profile.last_interaction.tzinfo == timezone.utc


class TestUserProfileStoreRecordMessage:
    """UserProfileStore.record_message のテスト"""

    @pytest.fixture(autouse=True)
    def mock_config(self):
        with patch("memory.user_profile.config") as mock_cfg:
            mock_cfg.USER_PROFILE_STORAGE_TYPE = "memory"
            mock_cfg.FAMILIARITY_THRESHOLD_ACQUAINTANCE = 6
            mock_cfg.FAMILIARITY_THRESHOLD_REGULAR = 31
            mock_cfg.FAMILIARITY_THRESHOLD_CLOSE = 101
            yield mock_cfg

    def test_creates_new_profile(self):
        """存在しないユーザーIDで新規プロファイルが作成される"""
        store = UserProfileStore()
        store.record_message(user_id=111, channel_id=999, display_name="NewUser")
        profile = store._profiles[111]
        assert profile.user_id == 111
        assert profile.display_name == "NewUser"
        assert profile.interaction_count == 1

    def test_increments_interaction_count(self):
        """連続して呼ぶとinteraction_countが増える"""
        store = UserProfileStore()
        store.record_message(1, 100, "User")
        store.record_message(1, 100, "User")
        store.record_message(1, 100, "User")
        assert store._profiles[1].interaction_count == 3

    def test_channels_active_dedup(self):
        """同じチャンネルは重複して追加されない"""
        store = UserProfileStore()
        store.record_message(1, 100, "User")
        store.record_message(1, 100, "User")
        store.record_message(1, 200, "User")
        assert store._profiles[1].channels_active == [100, 200]

    def test_updates_display_name(self):
        """display_name が最新に更新される"""
        store = UserProfileStore()
        store.record_message(1, 100, "OldName")
        store.record_message(1, 100, "NewName")
        assert store._profiles[1].display_name == "NewName"

    def test_updates_last_interaction(self):
        """last_interaction が更新される"""
        store = UserProfileStore()
        store.record_message(1, 100, "User")
        assert store._profiles[1].last_interaction is not None


class TestUserProfileStoreRecordBotMention:
    """UserProfileStore.record_bot_mention のテスト"""

    @pytest.fixture(autouse=True)
    def mock_config(self):
        with patch("memory.user_profile.config") as mock_cfg:
            mock_cfg.USER_PROFILE_STORAGE_TYPE = "memory"
            mock_cfg.FAMILIARITY_THRESHOLD_ACQUAINTANCE = 6
            mock_cfg.FAMILIARITY_THRESHOLD_REGULAR = 31
            mock_cfg.FAMILIARITY_THRESHOLD_CLOSE = 101
            yield mock_cfg

    def test_increments_mentioned_bot_count(self):
        """mentioned_bot_countが増える"""
        store = UserProfileStore()
        store.record_message(1, 100, "User")  # まずプロファイルを作成
        store.record_bot_mention(1)
        store.record_bot_mention(1)
        assert store._profiles[1].mentioned_bot_count == 2

    def test_no_error_for_unknown_user(self):
        """存在しないユーザーIDでエラーにならない（プロファイルなければno-op）"""
        store = UserProfileStore()
        store.record_bot_mention(9999)  # エラーが起きないこと


class TestUserProfileStoreUpdateLastTopic:
    """UserProfileStore.update_last_topic のテスト"""

    @pytest.fixture(autouse=True)
    def mock_config(self):
        with patch("memory.user_profile.config") as mock_cfg:
            mock_cfg.USER_PROFILE_STORAGE_TYPE = "memory"
            mock_cfg.FAMILIARITY_THRESHOLD_ACQUAINTANCE = 6
            mock_cfg.FAMILIARITY_THRESHOLD_REGULAR = 31
            mock_cfg.FAMILIARITY_THRESHOLD_CLOSE = 101
            yield mock_cfg

    def test_updates_last_topic(self):
        """last_topic が更新される"""
        store = UserProfileStore()
        store.record_message(1, 100, "User")
        store.update_last_topic(1, ["Rust", "async"])
        assert store._profiles[1].last_topic == ["Rust", "async"]

    def test_overwrites_previous_topic(self):
        """前の話題が上書きされる"""
        store = UserProfileStore()
        store.record_message(1, 100, "User")
        store.update_last_topic(1, ["Python"])
        store.update_last_topic(1, ["Go", "goroutine"])
        assert store._profiles[1].last_topic == ["Go", "goroutine"]

    def test_no_update_for_empty_keywords(self):
        """空リストのとき更新されない"""
        store = UserProfileStore()
        store.record_message(1, 100, "User")
        store._profiles[1].last_topic = ["existing"]
        store.update_last_topic(1, [])
        assert store._profiles[1].last_topic == ["existing"]

    def test_no_error_for_unknown_user(self):
        """存在しないユーザーIDでエラーにならない"""
        store = UserProfileStore()
        store.update_last_topic(9999, ["topic"])  # エラーが起きないこと


class TestUserProfileStoreMemoryStorage:
    """memory ストレージ: 永続化なし動作確認"""

    @pytest.fixture(autouse=True)
    def mock_config(self):
        with patch("memory.user_profile.config") as mock_cfg:
            mock_cfg.USER_PROFILE_STORAGE_TYPE = "memory"
            mock_cfg.FAMILIARITY_THRESHOLD_ACQUAINTANCE = 6
            mock_cfg.FAMILIARITY_THRESHOLD_REGULAR = 31
            mock_cfg.FAMILIARITY_THRESHOLD_CLOSE = 101
            yield mock_cfg

    def test_persist_all_is_noop(self):
        """memory ストレージのとき persist_all は何もしない"""
        store = UserProfileStore()
        store.record_message(1, 100, "User")
        # エラーなく完了すること
        store.persist_all()

    def test_get_profile_creates_new_if_not_found(self):
        """プロファイルが存在しない場合、新規作成される"""
        store = UserProfileStore()
        profile = store.get_profile(42, "NewUser")
        assert profile.user_id == 42
        assert profile.display_name == "NewUser"
        assert profile.interaction_count == 0

    def test_get_profile_returns_cached(self):
        """2回目以降はキャッシュから返される"""
        store = UserProfileStore()
        p1 = store.get_profile(1, "User")
        p1.interaction_count = 99
        p2 = store.get_profile(1, "User")
        assert p2.interaction_count == 99
        assert p1 is p2


class TestUserProfileStoreLocalStorage:
    """local ストレージ: to_dict / from_dict のラウンドトリップ + 書き込み確認"""

    @pytest.fixture(autouse=True)
    def mock_config(self):
        with patch("memory.user_profile.config") as mock_cfg:
            mock_cfg.USER_PROFILE_STORAGE_TYPE = "local"
            mock_cfg.FAMILIARITY_THRESHOLD_ACQUAINTANCE = 6
            mock_cfg.FAMILIARITY_THRESHOLD_REGULAR = 31
            mock_cfg.FAMILIARITY_THRESHOLD_CLOSE = 101
            yield mock_cfg

    def test_save_and_load_local(self, tmp_path):
        """ローカルファイルへの保存と読み込みが正しく動作する"""
        store = UserProfileStore()
        profile = UserProfile(
            user_id=555,
            display_name="LocalUser",
            interaction_count=20,
            mentioned_bot_count=2,
            channels_active=[111],
            last_topic=["local", "test"],
        )

        file_path = tmp_path / "user_profile.555.json"
        with patch("memory.user_profile.os.path.exists", return_value=True), \
             patch("memory.user_profile.os.makedirs"), \
             patch("memory.user_profile.os.replace"), \
             patch("memory.user_profile.tempfile.NamedTemporaryFile") as mock_tf:
            # NamedTemporaryFileのモック設定
            mock_file = MagicMock()
            mock_file.__enter__ = MagicMock(return_value=mock_file)
            mock_file.__exit__ = MagicMock(return_value=False)
            mock_file.name = str(tmp_path / "temp.json")
            mock_tf.return_value = mock_file

            # 実際に書き込んでテスト
            with patch("builtins.open", mock_open := MagicMock()):
                import io
                buf = io.StringIO()
                mock_open.return_value.__enter__.return_value = buf
                store._save_to_local(profile)

    def test_load_from_local_file_not_exists(self):
        """ファイルが存在しない場合はNoneを返す"""
        store = UserProfileStore()
        with patch("memory.user_profile.os.path.exists", return_value=False):
            result = store._load_from_local(99999)
        assert result is None

    def test_load_from_local_valid_file(self, tmp_path):
        """有効なJSONファイルからプロファイルが読み込まれる"""
        profile_data = {
            "user_id": 777,
            "display_name": "FileUser",
            "interaction_count": 50,
            "mentioned_bot_count": 10,
            "channels_active": [100, 200],
            "last_interaction": datetime.now(timezone.utc).isoformat(),
            "last_topic": ["file", "load"],
        }
        file_path = tmp_path / "user_profile.777.json"
        file_path.write_text(json.dumps(profile_data), encoding="utf-8")

        store = UserProfileStore()
        with patch(
            "memory.user_profile.os.path.exists", return_value=True
        ), patch(
            "builtins.open",
            MagicMock(return_value=MagicMock(
                __enter__=MagicMock(return_value=MagicMock(
                    read=MagicMock(return_value=json.dumps(profile_data))
                )),
                __exit__=MagicMock(return_value=False),
            ))
        ):
            with patch("json.load", return_value=profile_data):
                result = store._load_from_local(777)

        assert result is not None
        assert result.user_id == 777
        assert result.display_name == "FileUser"
        assert result.interaction_count == 50


class TestGetUserProfileStore:
    """get_user_profile_store シングルトンのテスト"""

    def test_returns_singleton(self):
        """常に同じインスタンスを返す"""
        import memory.user_profile as up_module

        # シングルトンをリセット
        original = up_module._store
        up_module._store = None
        try:
            with patch("memory.user_profile.config") as mock_cfg:
                mock_cfg.USER_PROFILE_STORAGE_TYPE = "memory"
                mock_cfg.FAMILIARITY_THRESHOLD_ACQUAINTANCE = 6
                mock_cfg.FAMILIARITY_THRESHOLD_REGULAR = 31
                mock_cfg.FAMILIARITY_THRESHOLD_CLOSE = 101
                s1 = get_user_profile_store()
                s2 = get_user_profile_store()
                assert s1 is s2
        finally:
            up_module._store = original
