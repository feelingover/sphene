"""config.py のテスト"""

import os
from unittest.mock import patch

import pytest

from config import get_collection_name


class TestGetCollectionName:
    """get_collection_name() のテスト"""

    def test_empty_namespace(self):
        """ネームスペースが空の場合、ベース名がそのまま返る"""
        with patch("config.FIRESTORE_NAMESPACE", ""):
            assert get_collection_name("channel_configs") == "channel_configs"
            assert get_collection_name("user_profiles") == "user_profiles"
            assert get_collection_name("channel_contexts") == "channel_contexts"

    def test_with_namespace(self):
        """ネームスペースが設定されている場合、プレフィックス付きで返る"""
        with patch("config.FIRESTORE_NAMESPACE", "prod"):
            assert get_collection_name("channel_configs") == "prod_channel_configs"
            assert get_collection_name("user_profiles") == "prod_user_profiles"
            assert get_collection_name("channel_contexts") == "prod_channel_contexts"

    def test_with_dev_namespace(self):
        """開発環境用のネームスペースでも正しく動作する"""
        with patch("config.FIRESTORE_NAMESPACE", "dev"):
            assert get_collection_name("channel_configs") == "dev_channel_configs"


class TestInstanceName:
    """INSTANCE_NAME / FIRESTORE_NAMESPACE / COMMAND_GROUP_NAME のテスト"""

    def test_firestore_namespace_defaults_to_instance_name(self):
        """FIRESTORE_NAMESPACE 未設定時は INSTANCE_NAME がデフォルト値"""
        env = {k: v for k, v in os.environ.items() if k != "FIRESTORE_NAMESPACE"}
        env["INSTANCE_NAME"] = "mybot"
        with patch("dotenv.load_dotenv"):
            with patch.dict(os.environ, env, clear=True):
                import importlib

                import config as cfg

                importlib.reload(cfg)
                assert cfg.FIRESTORE_NAMESPACE == "mybot"

    def test_firestore_namespace_explicit_value_takes_precedence(self):
        """FIRESTORE_NAMESPACE を明示的に設定した場合はその値が優先される"""
        with patch.dict(os.environ, {"INSTANCE_NAME": "mybot", "FIRESTORE_NAMESPACE": "custom"}, clear=False):
            import importlib

            import config as cfg

            importlib.reload(cfg)
            assert cfg.FIRESTORE_NAMESPACE == "custom"

    def test_command_group_name_defaults_to_instance_name(self):
        """COMMAND_GROUP_NAME 未設定時は INSTANCE_NAME がデフォルト値"""
        with patch.dict(os.environ, {"INSTANCE_NAME": "mybot"}, clear=False):
            import importlib

            import config as cfg

            os.environ.pop("COMMAND_GROUP_NAME", None)
            importlib.reload(cfg)
            assert cfg.COMMAND_GROUP_NAME == "mybot"

    def test_command_group_name_explicit_value_takes_precedence(self):
        """COMMAND_GROUP_NAME を明示的に設定した場合はその値が優先される"""
        with patch.dict(os.environ, {"INSTANCE_NAME": "mybot", "COMMAND_GROUP_NAME": "custom_cmd"}, clear=False):
            import importlib

            import config as cfg

            importlib.reload(cfg)
            assert cfg.COMMAND_GROUP_NAME == "custom_cmd"

    def test_missing_instance_name_raises_value_error(self):
        """INSTANCE_NAME 未設定時に ValueError が発生する"""
        env_without_instance = {k: v for k, v in os.environ.items() if k != "INSTANCE_NAME"}
        with patch("dotenv.load_dotenv"):
            with patch.dict(os.environ, env_without_instance, clear=True):
                import importlib

                import config as cfg

                with pytest.raises(ValueError, match="INSTANCE_NAME is required"):
                    importlib.reload(cfg)


def test_find_deprecated_env_vars_detects_set_variables(monkeypatch) -> None:
    """設定されている廃止済み環境変数だけを移行先の案内付きで返すこと"""
    import config

    for name in config.DEPRECATED_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MEMORY_ENABLED", "true")
    monkeypatch.setenv("JUDGE_MODEL", "gemini-x")

    found = dict(config.find_deprecated_env_vars())

    assert set(found) == {"MEMORY_ENABLED", "JUDGE_MODEL"}
    assert "LIVING_MEMORY_ENABLED" in found["MEMORY_ENABLED"]
    assert "BOT_LITE_MODEL" in found["JUDGE_MODEL"]


def test_find_deprecated_env_vars_empty(monkeypatch) -> None:
    """廃止済み環境変数が無ければ空リストを返すこと"""
    import config

    for name in config.DEPRECATED_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    assert config.find_deprecated_env_vars() == []


def test_deprecated_env_vars_are_not_read_by_config() -> None:
    """廃止済みとした環境変数を config.py が読んでいないこと（一覧の誤登録防止）"""
    import inspect

    import config

    source = inspect.getsource(config)
    for name in config.DEPRECATED_ENV_VARS:
        assert f'os.getenv("{name}"' not in source, name


class TestParseQuietHours:
    """PROACTIVE_QUIET_HOURS の解釈"""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("0-8", (0, 8)), ("22-6", (22, 6)), (" 1 - 5 ", (1, 5)), ("", None), ("3-3", None)],
    )
    def test_valid(self, raw, expected):
        from config import parse_quiet_hours

        assert parse_quiet_hours(raw) == expected

    @pytest.mark.parametrize("raw", ["0", "0-8-9", "a-b", "-1-8", "0-24", "25-3", "0:8"])
    def test_invalid(self, raw):
        from config import parse_quiet_hours

        with pytest.raises(ValueError, match="PROACTIVE_QUIET_HOURS"):
            parse_quiet_hours(raw)


class TestValidateProactiveConfig:
    """PROACTIVE_ENABLED=true のときの起動時バリデーション"""

    _DEFAULTS = {
        "LIVING_MEMORY_ENABLED": True,
        "PROACTIVE_CHECK_INTERVAL_MINUTES": 10,
        "PROACTIVE_MIN_SILENCE_MINUTES": 120,
        "PROACTIVE_MAX_SILENCE_HOURS": 24,
        "PROACTIVE_COOLDOWN_HOURS": 24,
        "PROACTIVE_FACT_COOLDOWN_HOURS": 72,
        "PROACTIVE_QUIET_HOURS": "0-8",
        "PROACTIVE_TIMEZONE": "Asia/Tokyo",
        "PROACTIVE_FOLLOW_UP_WINDOW_HOURS": 24,
    }

    def _validate(self, **overrides):
        import config as cfg

        values = {**self._DEFAULTS, **overrides}
        patches = [patch.object(cfg, k, v) for k, v in values.items()]
        for p in patches:
            p.start()
        try:
            cfg.validate_proactive_config()
        finally:
            for p in patches:
                p.stop()

    def test_defaults_are_valid(self):
        self._validate()

    def test_requires_living_memory(self):
        with pytest.raises(ValueError, match="LIVING_MEMORY_ENABLED"):
            self._validate(LIVING_MEMORY_ENABLED=False)

    @pytest.mark.parametrize(
        "name",
        [
            "PROACTIVE_CHECK_INTERVAL_MINUTES",
            "PROACTIVE_MIN_SILENCE_MINUTES",
            "PROACTIVE_MAX_SILENCE_HOURS",
            "PROACTIVE_FOLLOW_UP_WINDOW_HOURS",
        ],
    )
    def test_non_positive_rejected(self, name):
        with pytest.raises(ValueError, match=name):
            self._validate(**{name: 0})

    def test_cooldown_zero_allowed(self):
        self._validate(PROACTIVE_COOLDOWN_HOURS=0)

    def test_negative_cooldown_rejected(self):
        with pytest.raises(ValueError, match="PROACTIVE_COOLDOWN_HOURS"):
            self._validate(PROACTIVE_COOLDOWN_HOURS=-1)

    def test_fact_cooldown_zero_allowed(self):
        self._validate(PROACTIVE_FACT_COOLDOWN_HOURS=0)

    def test_negative_fact_cooldown_rejected(self):
        with pytest.raises(ValueError, match="PROACTIVE_FACT_COOLDOWN_HOURS"):
            self._validate(PROACTIVE_FACT_COOLDOWN_HOURS=-1)

    def test_fact_cooldown_default_and_env(self):
        import importlib

        import config as cfg

        try:
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("PROACTIVE_FACT_COOLDOWN_HOURS", None)
                importlib.reload(cfg)
                assert cfg.PROACTIVE_FACT_COOLDOWN_HOURS == 72
            with patch.dict(os.environ, {"PROACTIVE_FACT_COOLDOWN_HOURS": "48"}, clear=False):
                importlib.reload(cfg)
                assert cfg.PROACTIVE_FACT_COOLDOWN_HOURS == 48
        finally:
            importlib.reload(cfg)

    def test_min_silence_over_max_rejected(self):
        with pytest.raises(ValueError, match="PROACTIVE_MIN_SILENCE_MINUTES"):
            self._validate(PROACTIVE_MIN_SILENCE_MINUTES=25 * 60)

    def test_invalid_quiet_hours_rejected(self):
        with pytest.raises(ValueError, match="PROACTIVE_QUIET_HOURS"):
            self._validate(PROACTIVE_QUIET_HOURS="night")

    def test_invalid_timezone_rejected(self):
        with pytest.raises(ValueError, match="PROACTIVE_TIMEZONE"):
            self._validate(PROACTIVE_TIMEZONE="Mars/Olympus")

    def test_enabled_without_living_memory_fails_at_import(self):
        import importlib

        import config as cfg

        env = {"PROACTIVE_ENABLED": "true", "LIVING_MEMORY_ENABLED": "false"}
        try:
            with patch.dict(os.environ, env, clear=False):
                with pytest.raises(ValueError, match="LIVING_MEMORY_ENABLED"):
                    importlib.reload(cfg)
        finally:
            importlib.reload(cfg)
