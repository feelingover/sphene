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
