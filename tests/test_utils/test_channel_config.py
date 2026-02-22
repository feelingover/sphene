"""
チャンネル設定（channel_config）のテスト
"""

# type: ignore
# mypy: ignore-errors

import json
from unittest.mock import MagicMock, patch

import config
from utils.channel_config import ChannelConfig, ChannelConfigManager


class TestChannelConfigManager:
    """ChannelConfigManagerクラスのテスト"""

    def test_get_instance(self):
        """シングルトンインスタンス取得のテスト"""
        manager1 = ChannelConfigManager.get_instance()
        manager2 = ChannelConfigManager.get_instance()
        assert manager1 is manager2  # 同一インスタンスであること

        # デバッグモードでは別インスタンスになることを確認
        debug_manager = ChannelConfigManager.get_instance(debug_mode=True)
        assert manager1 is not debug_manager

    def test_get_config(self):
        """ギルド設定取得のテスト"""
        manager = ChannelConfigManager(debug_mode=True)

        # 同じguild_idならば同じインスタンスを返す
        config1 = manager.get_config("123")
        config2 = manager.get_config("123")
        assert config1 is config2

        # 異なるguild_idならば異なるインスタンス
        config3 = manager.get_config("456")
        assert config1 is not config3

        # guild_idが異なる場合、別々の設定として管理される
        config1.set_behavior("allow")
        config3.set_behavior("deny")
        assert config1.get_behavior() == "allow"
        assert config3.get_behavior() == "deny"


class TestChannelConfig:
    """ChannelConfigクラスのテスト"""

    def test_init_default_values(self):
        """初期値が正しく設定されることを確認"""
        # テスト用のguild_idとdebugモードで初期化（ファイル操作をスキップ）
        conf = ChannelConfig(guild_id="test_guild", debug_mode=True)

        # デフォルト値をチェック
        assert conf.get_behavior() == "deny"
        assert isinstance(conf.get_channels(), list)
        assert len(conf.get_channels()) == 0

    def test_behavior_mode_settings(self):
        """評価モードの設定テスト"""
        conf = ChannelConfig(guild_id="test_guild", debug_mode=True)

        # モード切替
        assert conf.get_behavior() == "deny"
        assert conf.get_mode_display_name() == "全体モード"
        assert conf.get_list_display_name() == "拒否チャンネルリスト"

        # allowモードへ変更
        conf.set_behavior("allow")
        assert conf.get_behavior() == "allow"
        assert conf.get_mode_display_name() == "限定モード"
        assert conf.get_list_display_name() == "許可チャンネルリスト"

        # 無効なモード設定
        assert not conf.set_behavior("invalid")  # Falseを返す

    def test_channel_operations(self):
        """チャンネル操作のテスト"""
        conf = ChannelConfig(guild_id="test_guild", debug_mode=True)

        # チャンネル追加
        assert conf.add_channel(123456, "テストチャンネル")
        assert conf.is_channel_in_list(123456)

        # リストの確認
        channels = conf.get_channels()
        assert len(channels) == 1
        assert channels[0]["id"] == 123456
        assert channels[0]["name"] == "テストチャンネル"

        # チャンネル削除
        assert conf.remove_channel(123456)
        assert not conf.is_channel_in_list(123456)
        assert len(conf.get_channels()) == 0

        # 複数チャンネルの操作
        conf.add_channel(111, "チャンネル1")
        conf.add_channel(222, "チャンネル2")
        conf.add_channel(333, "チャンネル3")
        assert len(conf.get_channels()) == 3

        # クリア操作
        assert conf.clear_channels()
        assert len(conf.get_channels()) == 0

    def test_can_bot_speak(self):
        """ボット発言可否のチェック機能テスト"""
        conf = ChannelConfig(guild_id="test_guild", debug_mode=True)

        # 全体モード（denyモード）のテスト
        conf.set_behavior("deny")

        # リストが空の場合
        assert conf.can_bot_speak(12345)  # リストが空なら全てのチャンネルで発言可能

        # リストにチャンネルを追加
        conf.add_channel(111, "禁止チャンネル1")
        conf.add_channel(222, "禁止チャンネル2")

        # 発言可否チェック
        assert not conf.can_bot_speak(111)  # リストに含まれるチャンネルでは発言不可
        assert not conf.can_bot_speak(222)
        assert conf.can_bot_speak(333)  # リストに含まれないチャンネルでは発言可能

        # 限定モード（allowモード）のテスト
        conf.set_behavior("allow")

        # 発言可否チェック
        assert conf.can_bot_speak(111)  # リストに含まれるチャンネルでは発言可能
        assert conf.can_bot_speak(222)
        assert not conf.can_bot_speak(333)  # リストに含まれないチャンネルでは発言不可

    @patch("os.path.exists")
    @patch("builtins.open")
    def test_load_from_local(self, mock_open, mock_exists):
        """ローカルファイルからの読み込みテスト"""
        mock_exists.return_value = True

        # ファイル読み込みをモック
        mock_file = MagicMock()
        mock_open.return_value.__enter__.return_value = mock_file
        mock_file.read.return_value = json.dumps(
            {
                "behavior": "allow",
                "channels": [{"id": 123, "name": "テストチャンネル"}],
                "updated_at": "2025-04-19T10:00:00",
            }
        )

        conf = ChannelConfig(guild_id="test_guild", debug_mode=True)
        # テスト用にdebug_modeを一時的に無効化
        conf.debug_mode = False
        conf._load_from_local()
        # テスト後に元に戻す
        conf.debug_mode = True

        assert conf.get_behavior() == "allow"
        assert len(conf.get_channels()) == 1
        assert conf.get_channels()[0]["id"] == 123

        # ファイルパスが正しく生成されているか確認
        mock_open.assert_called_with(
            f"storage/channel_list.{conf.guild_id}.json", "r", encoding="utf-8"
        )

    @patch("utils.channel_config.get_firestore_client")
    def test_load_from_firestore(self, mock_get_firestore_client):
        """Firestoreからの読み込みテスト"""
        mock_db = MagicMock()
        mock_get_firestore_client.return_value = mock_db

        # Firestoreドキュメントのモック
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {
            "behavior": "allow",
            "channels": [{"id": 456, "name": "Firestoreテスト"}],
            "updated_at": "2025-04-19T10:00:00",
        }
        mock_db.collection.return_value.document.return_value.get.return_value = (
            mock_doc
        )

        with patch.object(config, "FIRESTORE_COLLECTION_CHANNEL_CONFIGS", "test_collection"):
            conf = ChannelConfig(
                guild_id="test_guild", storage_type="firestore", debug_mode=True
            )

            # モックをリセット
            mock_db.reset_mock()
            mock_get_firestore_client.reset_mock()

            # テスト対象のメソッドを実行
            conf.debug_mode = False
            conf._load_from_firestore()
            conf.debug_mode = True

        assert conf.get_behavior() == "allow"
        assert len(conf.get_channels()) == 1
        assert conf.get_channels()[0]["id"] == 456
        assert conf.get_channels()[0]["name"] == "Firestoreテスト"

        # 正しいコレクション・ドキュメントで呼び出されたか確認
        mock_db.collection.assert_called_once_with("test_collection")
        mock_db.collection.return_value.document.assert_called_once_with("test_guild")

    @patch("utils.channel_config.get_firestore_client")
    def test_load_from_firestore_not_found(self, mock_get_firestore_client):
        """Firestoreにドキュメントがない場合の読み込みテスト"""
        mock_db = MagicMock()
        mock_get_firestore_client.return_value = mock_db

        # ドキュメントが存在しないケース
        mock_doc = MagicMock()
        mock_doc.exists = False
        mock_db.collection.return_value.document.return_value.get.return_value = (
            mock_doc
        )

        with patch.object(config, "FIRESTORE_COLLECTION_CHANNEL_CONFIGS", "test_collection"):
            conf = ChannelConfig(
                guild_id="test_guild", storage_type="firestore", debug_mode=True
            )

            conf.debug_mode = False
            try:
                conf._load_from_firestore()
                assert False, "FileNotFoundError should have been raised"
            except FileNotFoundError:
                pass  # 期待通りの例外
            conf.debug_mode = True

    @patch("os.makedirs")
    @patch("os.replace")
    @patch("utils.channel_config.tempfile.NamedTemporaryFile")
    def test_save_to_local(self, mock_tempfile, mock_replace, mock_makedirs):
        """ローカルへの保存テスト"""
        mock_file = MagicMock()
        mock_tempfile.return_value.__enter__.return_value = mock_file
        mock_file.name = "temp_file_path"

        # テスト用のインスタンス作成
        conf = ChannelConfig(guild_id="12345", debug_mode=True)

        # 保存テスト用にデータを設定
        conf.config_data = {
            "behavior": "allow",
            "channels": [{"id": 123, "name": "保存テスト"}],
            "updated_at": "2025-04-19T10:00:00",  # テスト用に固定
        }

        # 一時的にdebug_modeを無効化
        conf.debug_mode = False

        # makedirs呼び出しカウントをリセット
        mock_makedirs.reset_mock()

        result = conf._save_to_local()

        # テスト後に元に戻す
        conf.debug_mode = True

        assert result is True
        assert mock_makedirs.called
        assert mock_tempfile.called
        assert mock_replace.called

        # ファイルパスが正しく生成されているか確認
        mock_replace.assert_called_with(
            "temp_file_path", f"storage/channel_list.{conf.guild_id}.json"
        )

    @patch("utils.channel_config.get_firestore_client")
    def test_save_to_firestore(self, mock_get_firestore_client):
        """Firestoreへの保存テスト"""
        mock_db = MagicMock()
        mock_get_firestore_client.return_value = mock_db

        with patch.object(config, "FIRESTORE_COLLECTION_CHANNEL_CONFIGS", "test_collection"):
            conf = ChannelConfig(
                guild_id="test_guild", storage_type="firestore", debug_mode=True
            )

            # モックをリセット
            mock_db.reset_mock()
            mock_get_firestore_client.reset_mock()

            # テスト用のデータを設定
            conf.config_data = {
                "behavior": "allow",
                "channels": [{"id": 789, "name": "Firestore保存テスト"}],
                "updated_at": "2025-04-19T10:00:00",
            }

            conf.debug_mode = False
            result = conf._save_to_firestore()
            conf.debug_mode = True

            assert result is True
            mock_db.collection.assert_called_once_with("test_collection")
            mock_db.collection.return_value.document.assert_called_once_with(
                "test_guild"
            )
            mock_db.collection.return_value.document.return_value.set.assert_called_once_with(
                conf.config_data
            )

    @patch("utils.channel_config.get_firestore_client")
    def test_delete_firestore_document(self, mock_get_firestore_client):
        """Firestoreドキュメント削除テスト"""
        mock_db = MagicMock()
        mock_get_firestore_client.return_value = mock_db

        manager = ChannelConfigManager(debug_mode=False)

        with patch.object(
            config, "STORAGE_TYPE", "firestore"
        ), patch.object(config, "FIRESTORE_COLLECTION_CHANNEL_CONFIGS", "test_collection"):
            # ChannelConfigの初期化時にFirestoreにアクセスしないようdebug_modeで作成
            mock_config = ChannelConfig(
                guild_id="test_guild", debug_mode=True
            )
            manager.guild_configs["test_guild"] = mock_config

            result = manager._delete_firestore_document("test_guild")

        assert result is True
        mock_db.collection.assert_called_once_with("test_collection")
        mock_db.collection.return_value.document.assert_called_once_with("test_guild")
        mock_db.collection.return_value.document.return_value.delete.assert_called_once()

    def test_file_paths(self):
        """ファイルパス生成のテスト"""
        guild_id = "test_guild_123"
        conf = ChannelConfig(guild_id=guild_id, debug_mode=True)

        # ローカルファイルパス
        assert conf._get_config_file_path() == f"storage/channel_list.{guild_id}.json"
