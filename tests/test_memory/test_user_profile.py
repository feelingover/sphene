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
            mock_cfg.STORAGE_TYPE = "local"
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
            mock_cfg.STORAGE_TYPE = "local"
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
        with patch("memory.user_profile.config") as mock_cfg, \
             patch("memory.user_profile.os.path.exists", return_value=False):
            mock_cfg.STORAGE_TYPE = "local"
            mock_cfg.FAMILIARITY_THRESHOLD_ACQUAINTANCE = 6
            mock_cfg.FAMILIARITY_THRESHOLD_REGULAR = 31
            mock_cfg.FAMILIARITY_THRESHOLD_CLOSE = 101
            mock_cfg.CHANNELS_ACTIVE_LIMIT = 20
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
        with patch("memory.user_profile.config") as mock_cfg, \
             patch("memory.user_profile.os.path.exists", return_value=False):
            mock_cfg.STORAGE_TYPE = "local"
            mock_cfg.FAMILIARITY_THRESHOLD_ACQUAINTANCE = 6
            mock_cfg.FAMILIARITY_THRESHOLD_REGULAR = 31
            mock_cfg.FAMILIARITY_THRESHOLD_CLOSE = 101
            mock_cfg.CHANNELS_ACTIVE_LIMIT = 20
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
        with patch("memory.user_profile.config") as mock_cfg, \
             patch("memory.user_profile.os.path.exists", return_value=False):
            mock_cfg.STORAGE_TYPE = "local"
            mock_cfg.FAMILIARITY_THRESHOLD_ACQUAINTANCE = 6
            mock_cfg.FAMILIARITY_THRESHOLD_REGULAR = 31
            mock_cfg.FAMILIARITY_THRESHOLD_CLOSE = 101
            mock_cfg.CHANNELS_ACTIVE_LIMIT = 20
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


class TestUserProfileStoreBasicStorage:
    """local ストレージ: 基本動作確認"""

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

    def test_persist_all_calls_save_to_local(self):
        """local ストレージのとき persist_all が _save_to_local を呼ぶこと"""
        store = UserProfileStore()
        store.record_message(1, 100, "User")
        with patch.object(store, "_save_to_local") as mock_save:
            store.persist_all()
            mock_save.assert_called_once()

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
            mock_cfg.STORAGE_TYPE = "local"
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

        with patch("utils.file_utils.atomic_write_json") as mock_write:
            store._save_to_local(profile)
            mock_write.assert_called_once()
            call_args = mock_write.call_args
            assert "user_profile.555" in call_args[0][0]
            assert call_args[0][1]["user_id"] == 555

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
                mock_cfg.STORAGE_TYPE = "local"
                mock_cfg.FAMILIARITY_THRESHOLD_ACQUAINTANCE = 6
                mock_cfg.FAMILIARITY_THRESHOLD_REGULAR = 31
                mock_cfg.FAMILIARITY_THRESHOLD_CLOSE = 101
                s1 = get_user_profile_store()
                s2 = get_user_profile_store()
                assert s1 is s2
        finally:
            up_module._store = original


class TestUserProfileNewFields:
    """Phase 3B の新フィールドに関するテスト"""

    def test_new_field_defaults(self):
        """新フィールドがデフォルト値を持つこと"""
        profile = UserProfile(user_id=1, display_name="User")
        assert profile.schema_version == 1
        assert profile.tags == []
        assert profile.personality_notes == ""
        assert profile.last_conversation_summary == ""
        assert profile.preferred_tone is None
        assert profile.notable_facts == []
        assert profile.emotional_state_last is None
        assert profile.nickname is None

    def test_from_dict_legacy_format(self):
        """旧フォーマット（新フィールドなし）からも正常に復元できること"""
        data = {
            "user_id": 123,
            "display_name": "LegacyUser",
            "interaction_count": 5,
            "mentioned_bot_count": 1,
            "channels_active": [100],
            "last_interaction": datetime.now(timezone.utc).isoformat(),
            "last_topic": ["Python"],
        }
        profile = UserProfile.from_dict(data)
        assert profile.user_id == 123
        assert profile.schema_version == 1
        assert profile.tags == []
        assert profile.personality_notes == ""
        assert profile.nickname is None

    def test_round_trip_with_new_fields(self):
        """新フィールドを含むシリアライズ/デシリアライズが正しく動作すること"""
        profile = UserProfile(
            user_id=1,
            display_name="User",
            tags=["プログラマー", "猫好き"],
            notable_facts=["東京在住"],
            personality_notes="明るい性格",
            last_conversation_summary="Pythonの話をした",
            preferred_tone="カジュアル",
            emotional_state_last="楽しそう",
            nickname="ポチ",
        )
        restored = UserProfile.from_dict(profile.to_dict())
        assert restored.tags == ["プログラマー", "猫好き"]
        assert restored.notable_facts == ["東京在住"]
        assert restored.personality_notes == "明るい性格"
        assert restored.last_conversation_summary == "Pythonの話をした"
        assert restored.preferred_tone == "カジュアル"
        assert restored.emotional_state_last == "楽しそう"
        assert restored.nickname == "ポチ"


class TestChannelsActiveLimit:
    """channels_active 上限制御のテスト"""

    @pytest.fixture(autouse=True)
    def mock_config(self):
        with patch("memory.user_profile.config") as mock_cfg, \
             patch("memory.user_profile.os.path.exists", return_value=False):
            mock_cfg.STORAGE_TYPE = "local"
            mock_cfg.FAMILIARITY_THRESHOLD_ACQUAINTANCE = 6
            mock_cfg.FAMILIARITY_THRESHOLD_REGULAR = 31
            mock_cfg.FAMILIARITY_THRESHOLD_CLOSE = 101
            mock_cfg.CHANNELS_ACTIVE_LIMIT = 3
            yield mock_cfg

    def test_channels_active_limit(self):
        """CHANNELS_ACTIVE_LIMIT=3 で 4 件追加したとき、最新3件のみ残ること"""
        store = UserProfileStore()
        store.record_message(1, 100, "User")
        store.record_message(1, 200, "User")
        store.record_message(1, 300, "User")
        store.record_message(1, 400, "User")
        assert store._profiles[1].channels_active == [200, 300, 400]

    def test_channels_active_lru_order(self):
        """既存チャンネルへの再アクセスで末尾に移動すること"""
        store = UserProfileStore()
        store.record_message(1, 100, "User")
        store.record_message(1, 200, "User")
        store.record_message(1, 100, "User")  # 100に再アクセス
        assert store._profiles[1].channels_active[-1] == 100


class TestFormatMethods:
    """format_for_familiarity / format_for_context / format_for_persona のテスト"""

    @pytest.fixture(autouse=True)
    def mock_config(self):
        with patch("memory.user_profile.config") as mock_cfg:
            mock_cfg.FAMILIARITY_THRESHOLD_ACQUAINTANCE = 6
            mock_cfg.FAMILIARITY_THRESHOLD_REGULAR = 31
            mock_cfg.FAMILIARITY_THRESHOLD_CLOSE = 101
            mock_cfg.STORAGE_TYPE = "local"
            yield mock_cfg

    def test_format_for_familiarity_empty_when_no_interactions(self):
        """interaction_count=0 のとき空文字を返す"""
        profile = UserProfile(user_id=1, display_name="User")
        assert profile.format_for_familiarity() == ""

    def test_format_for_familiarity_uses_nickname(self):
        """nickname が設定されていれば display_name の代わりに使われること"""
        profile = UserProfile(user_id=1, display_name="本名", interaction_count=10, nickname="ポチ")
        result = profile.format_for_familiarity()
        assert "ポチ" in result
        assert "本名" not in result

    def test_format_for_familiarity_uses_display_name_when_no_nickname(self):
        """nickname が None のとき display_name を使うこと"""
        profile = UserProfile(user_id=1, display_name="田中", interaction_count=10)
        result = profile.format_for_familiarity()
        assert "田中" in result

    def test_format_for_context_empty_when_no_data(self):
        """summary も last_topic もないとき空文字を返す"""
        profile = UserProfile(user_id=1, display_name="User")
        assert profile.format_for_context() == ""

    def test_format_for_context_with_summary(self):
        """last_conversation_summary があれば含まれること"""
        profile = UserProfile(user_id=1, display_name="User", last_conversation_summary="Pythonの話をした")
        result = profile.format_for_context()
        assert "Pythonの話をした" in result

    def test_format_for_context_with_topic(self):
        """last_topic があれば含まれること"""
        profile = UserProfile(user_id=1, display_name="User", last_topic=["Rust", "async"])
        result = profile.format_for_context()
        assert "Rust, async" in result

    def test_format_for_persona_empty_when_no_data(self):
        """persona 情報がないとき空文字を返す"""
        profile = UserProfile(user_id=1, display_name="User")
        assert profile.format_for_persona() == ""

    def test_format_for_persona_with_tags(self):
        """tags があれば含まれること"""
        profile = UserProfile(user_id=1, display_name="User", tags=["プログラマー", "猫好き"])
        result = profile.format_for_persona()
        assert "プログラマー" in result
        assert "猫好き" in result

    def test_format_for_persona_with_notable_facts(self):
        """notable_facts があれば含まれること"""
        profile = UserProfile(user_id=1, display_name="User", notable_facts=["東京在住", "犬を飼っている"])
        result = profile.format_for_persona()
        assert "東京在住" in result
        assert "犬を飼っている" in result

    def test_format_for_persona_with_personality_notes(self):
        """personality_notes があれば含まれること"""
        profile = UserProfile(user_id=1, display_name="User", personality_notes="明るい性格")
        result = profile.format_for_persona()
        assert "明るい性格" in result


class TestUpdateFromReflection:
    """UserProfileStore.update_from_reflection のテスト"""

    @pytest.fixture(autouse=True)
    def mock_config(self):
        with patch("memory.user_profile.config") as mock_cfg, \
             patch("memory.user_profile.os.path.exists", return_value=False):
            mock_cfg.STORAGE_TYPE = "local"
            mock_cfg.FAMILIARITY_THRESHOLD_ACQUAINTANCE = 6
            mock_cfg.FAMILIARITY_THRESHOLD_REGULAR = 31
            mock_cfg.FAMILIARITY_THRESHOLD_CLOSE = 101
            mock_cfg.CHANNELS_ACTIVE_LIMIT = 20
            mock_cfg.USER_PROFILE_TAGS_LIMIT = 3
            mock_cfg.USER_PROFILE_FACTS_LIMIT = 3
            yield mock_cfg

    def test_update_tags_dedup(self):
        """重複タグは追加されないこと"""
        store = UserProfileStore()
        store.record_message(1, 100, "User")
        store.update_from_reflection(1, {"tags": ["Python", "Python", "猫好き"]})
        assert store._profiles[1].tags.count("Python") == 1

    def test_update_tags_limit(self):
        """USER_PROFILE_TAGS_LIMIT を超えた場合、古いものが削除されること"""
        store = UserProfileStore()
        store.record_message(1, 100, "User")
        store._profiles[1].tags = ["A", "B", "C"]
        store.update_from_reflection(1, {"tags": ["D"]})
        assert len(store._profiles[1].tags) == 3
        assert "A" not in store._profiles[1].tags
        assert "D" in store._profiles[1].tags

    def test_update_notable_facts_dedup(self):
        """重複ファクトは追加されないこと"""
        store = UserProfileStore()
        store.record_message(1, 100, "User")
        store.update_from_reflection(1, {"notable_facts": ["東京在住", "東京在住"]})
        assert store._profiles[1].notable_facts.count("東京在住") == 1

    def test_update_notable_facts_limit(self):
        """USER_PROFILE_FACTS_LIMIT を超えた場合、古いものが削除されること"""
        store = UserProfileStore()
        store.record_message(1, 100, "User")
        store._profiles[1].notable_facts = ["A", "B", "C"]
        store.update_from_reflection(1, {"notable_facts": ["D"]})
        assert len(store._profiles[1].notable_facts) == 3
        assert "A" not in store._profiles[1].notable_facts

    def test_update_personality_notes(self):
        """personality_notes が上書き更新されること"""
        store = UserProfileStore()
        store.record_message(1, 100, "User")
        store.update_from_reflection(1, {"personality_notes": "明るい性格"})
        assert store._profiles[1].personality_notes == "明るい性格"

    def test_update_conversation_summary(self):
        """last_conversation_summary が更新されること"""
        store = UserProfileStore()
        store.record_message(1, 100, "User")
        store.update_from_reflection(1, {"last_conversation_summary": "Pythonの話をした"})
        assert store._profiles[1].last_conversation_summary == "Pythonの話をした"

    def test_no_error_for_unknown_user(self):
        """存在しないユーザーIDでエラーにならないこと"""
        store = UserProfileStore()
        store.update_from_reflection(9999, {"tags": ["test"]})  # エラーが起きないこと


class TestUpdateNickname:
    """UserProfileStore.update_nickname のテスト"""

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

    def test_update_nickname(self):
        """ニックネームが正しく設定されること"""
        store = UserProfileStore()
        store.record_message(1, 100, "User")
        store.update_nickname(1, "ポチ")
        assert store._profiles[1].nickname == "ポチ"

    def test_update_nickname_overwrites(self):
        """既存のニックネームが上書きされること"""
        store = UserProfileStore()
        store.record_message(1, 100, "User")
        store.update_nickname(1, "ポチ")
        store.update_nickname(1, "タマ")
        assert store._profiles[1].nickname == "タマ"

    def test_no_error_for_unknown_user(self):
        """存在しないユーザーIDでエラーにならないこと"""
        store = UserProfileStore()
        store.update_nickname(9999, "ポチ")  # エラーが起きないこと
