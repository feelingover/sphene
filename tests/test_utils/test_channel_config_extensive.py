"""
utils/channel_config.py の広範なテスト
"""

# type: ignore
# mypy: ignore-errors

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from utils.channel_config import ChannelConfig, ChannelConfigManager


class TestChannelConfigExtensive:
    """ChannelConfigクラスとManagerの広範なテスト"""

    def test_guild_id_validation(self):
        """ギルドIDのバリデーションテスト"""
        # 有効なID
        ChannelConfig(guild_id="valid-id_123", debug_mode=True)
        
        # 無効なID（記号など）
        with pytest.raises(ValueError):
            ChannelConfig(guild_id="invalid/id", debug_mode=True)
        with pytest.raises(ValueError):
            ChannelConfig(guild_id="id;select", debug_mode=True)

    @patch("utils.channel_config.get_firestore_client")
    def test_load_from_firestore_error_handling(self, mock_get_firestore):
        """Firestore読み込み時のエラーハンドリングテスト"""
        mock_db = MagicMock()
        mock_db.collection().document().get.side_effect = Exception("Firestore Error")
        mock_get_firestore.return_value = mock_db
        
        # 読み込み失敗時にデフォルト設定になることを確認
        config = ChannelConfig(guild_id="test", storage_type="firestore", debug_mode=False)
        assert config.get_behavior() == "deny"

    def test_manager_singleton(self):
        """マネージャーのシングルトン動作テスト"""
        m1 = ChannelConfigManager.get_instance()
        m2 = ChannelConfigManager.get_instance()
        assert m1 is m2
        
        # デバッグモードは独立
        m3 = ChannelConfigManager.get_instance(debug_mode=True)
        assert m3 is not m1

    @patch("os.path.exists")
    @patch("os.remove")
    def test_delete_local_file(self, mock_remove, mock_exists):
        """ローカルファイル削除テスト"""
        manager = ChannelConfigManager(debug_mode=False)
        mock_exists.return_value = True
        
        with patch("config.CHANNEL_CONFIG_STORAGE_TYPE", "local"):
            result = manager.delete_guild_config("12345")
            assert result is True
            mock_remove.assert_called_once_with("storage/channel_list.12345.json")

    @patch("utils.channel_config.get_firestore_client")
    def test_delete_firestore_document(self, mock_get_firestore):
        """Firestoreドキュメント削除テスト"""
        manager = ChannelConfigManager(debug_mode=False)
        mock_db = MagicMock()
        mock_get_firestore.return_value = mock_db
        
        with patch("config.CHANNEL_CONFIG_STORAGE_TYPE", "firestore"):
            with patch("config.FIRESTORE_COLLECTION_NAME", "test_cols"):
                result = manager.delete_guild_config("54321")
                assert result is True
                mock_db.collection.assert_called_with("test_cols")
                mock_db.collection().document.assert_called_with("54321")
                mock_db.collection().document().delete.assert_called_once()

    def test_translation_enabled_setting(self):
        """翻訳機能の設定テスト"""
        config = ChannelConfig(guild_id="test", debug_mode=True)
        assert config.get_translation_enabled() is False
        
        config.set_translation_enabled(True)
        assert config.get_translation_enabled() is True
        
        config.set_translation_enabled(False)
        assert config.get_translation_enabled() is False

    @patch("tempfile.NamedTemporaryFile")
    @patch("os.replace")
    def test_atomic_save_failure(self, mock_replace, mock_temp):
        """アトミック保存の失敗ケーステスト"""
        config = ChannelConfig(guild_id="test", storage_type="local", debug_mode=False)
        
        # os.replace で失敗
        mock_replace.side_effect = Exception("Disk Full")
        
        with patch("os.makedirs"):
            with patch("os.path.exists", return_value=True):
                with patch("os.remove") as mock_remove:
                    result = config._save_to_local()
                    assert result is False
                    mock_remove.assert_called_once()
