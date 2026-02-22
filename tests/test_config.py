"""config.py のテスト"""

# type: ignore
# mypy: ignore-errors

from unittest.mock import patch

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
