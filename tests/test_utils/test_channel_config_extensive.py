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
        
        with patch("config.STORAGE_TYPE", "local"):
            result = manager.delete_guild_config("12345")
            assert result is True
            mock_remove.assert_called_once_with("storage/channel_list.12345.json")

    @patch("utils.channel_config.get_firestore_client")
    def test_delete_firestore_document(self, mock_get_firestore):
        """Firestoreドキュメント削除テスト"""
        manager = ChannelConfigManager(debug_mode=False)
        mock_db = MagicMock()
        mock_get_firestore.return_value = mock_db
        
        with patch("config.STORAGE_TYPE", "firestore"):
            with patch("config.FIRESTORE_COLLECTION_CHANNEL_CONFIGS", "test_cols"):
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

    def test_atomic_save_failure(self):
        """アトミック保存の失敗ケーステスト"""
        config = ChannelConfig(guild_id="test", storage_type="local", debug_mode=False)

        with patch("utils.file_utils.atomic_write_json", side_effect=Exception("Disk Full")):
            result = config._save_to_local()
            assert result is False


class TestChannelConfigLoadFailure:
    """設定読み込み失敗時に既存データを上書きしないことのテスト"""

    @staticmethod
    def _firestore_db(get_side_effect=None, exists=True, data=None):
        mock_db = MagicMock()
        doc_ref = mock_db.collection.return_value.document.return_value
        if get_side_effect is not None:
            doc_ref.get.side_effect = get_side_effect
        else:
            doc = MagicMock()
            doc.exists = exists
            doc.to_dict.return_value = data
            doc_ref.get.return_value = doc
        return mock_db, doc_ref

    @patch("utils.channel_config.get_firestore_client")
    def test_transient_error_marks_load_failed_and_refuses_save(self, mock_get_fs):
        """一時的な読み込みエラーでは load_failed になり、保存を拒否すること"""
        mock_db, doc_ref = self._firestore_db(get_side_effect=Exception("unavailable"))
        mock_get_fs.return_value = mock_db

        cfg = ChannelConfig(guild_id="123", storage_type="firestore")

        assert cfg.load_failed is True
        assert cfg.save_config() is False
        doc_ref.set.assert_not_called()

    @patch("utils.channel_config.get_firestore_client")
    def test_load_failed_config_denies_speaking(self, mock_get_fs):
        """読み込み失敗時は全体モードのデフォルトに落ちず、発言不可になること（fail-closed）"""
        mock_db, _ = self._firestore_db(get_side_effect=Exception("unavailable"))
        mock_get_fs.return_value = mock_db

        cfg = ChannelConfig(guild_id="123", storage_type="firestore")

        assert cfg.load_failed is True
        assert cfg.can_bot_speak(456) is False

    @patch("utils.channel_config.get_firestore_client")
    def test_missing_document_still_allows_speaking(self, mock_get_fs):
        """ドキュメント未作成（正常系）は従来どおり全体モードで発言可能なこと"""
        mock_db, _ = self._firestore_db(exists=False)
        mock_get_fs.return_value = mock_db

        cfg = ChannelConfig(guild_id="123", storage_type="firestore")

        assert cfg.can_bot_speak(456) is True

    @patch("utils.channel_config.get_firestore_client")
    def test_missing_document_uses_defaults_and_allows_save(self, mock_get_fs):
        """ドキュメント未作成は正常系としてデフォルト設定で保存できること"""
        mock_db, doc_ref = self._firestore_db(exists=False)
        mock_get_fs.return_value = mock_db

        cfg = ChannelConfig(guild_id="123", storage_type="firestore")

        assert cfg.load_failed is False
        assert cfg.get_behavior() == "deny"
        assert cfg.save_config() is True
        doc_ref.set.assert_called_once()

    @patch("utils.channel_config.config")
    @patch("utils.channel_config.get_firestore_client")
    def test_manager_does_not_cache_failed_load_and_retries(self, mock_get_fs, mock_config):
        """読み込み失敗した設定はキャッシュせず、次回の取得で再読み込みすること"""
        mock_config.STORAGE_TYPE = "firestore"
        stored = {"behavior": "allow", "channels": [{"id": "1", "name": "c"}]}
        ok_doc = MagicMock(exists=True)
        ok_doc.to_dict.return_value = stored
        mock_db, doc_ref = self._firestore_db(
            get_side_effect=[Exception("unavailable"), ok_doc]
        )
        mock_get_fs.return_value = mock_db
        manager = ChannelConfigManager(debug_mode=False)

        first = manager.get_config("123")
        assert first.load_failed is True
        assert "123" not in manager.guild_configs

        second = manager.get_config("123")
        assert second.load_failed is False
        assert second.get_behavior() == "allow"
        assert manager.guild_configs["123"] is second

    @patch("utils.channel_config.config")
    @patch("utils.channel_config.get_firestore_client")
    def test_create_guild_config_does_not_overwrite_on_load_failure(
        self, mock_get_fs, mock_config
    ):
        """ギルド参加時に読み込み失敗した場合、デフォルトで上書き保存しないこと"""
        mock_config.STORAGE_TYPE = "firestore"
        mock_db, doc_ref = self._firestore_db(get_side_effect=Exception("unavailable"))
        mock_get_fs.return_value = mock_db
        manager = ChannelConfigManager(debug_mode=False)

        manager.create_guild_config("123")

        doc_ref.set.assert_not_called()
        assert "123" not in manager.guild_configs
