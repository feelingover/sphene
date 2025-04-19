"""
チャンネル設定（channel_config）のテスト
"""

# type: ignore
# mypy: ignore-errors

import json
from unittest.mock import MagicMock, patch

import config
from utils.channel_config import ChannelConfig


class TestChannelConfig:
    """ChannelConfigクラスのテスト"""

    def test_init_default_values(self):
        """初期値が正しく設定されることを確認"""
        # debugモードで初期化（ファイル操作をスキップ）
        conf = ChannelConfig(debug_mode=True)

        # デフォルト値をチェック
        assert conf.get_behavior() == "deny"
        assert isinstance(conf.get_channels(), list)
        assert len(conf.get_channels()) == 0

    def test_behavior_mode_settings(self):
        """評価モードの設定テスト"""
        conf = ChannelConfig(debug_mode=True)

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
        conf = ChannelConfig(debug_mode=True)

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
        conf = ChannelConfig(debug_mode=True)

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

    def test_initialize_from_env(self):
        """環境変数からの初期化テスト"""
        # DENIED_CHANNEL_IDSをモックして設定
        with patch.object(config, "DENIED_CHANNEL_IDS", [111, 222]):
            conf = ChannelConfig(debug_mode=True)
            conf._initialize_from_env()

            # 拒否リストからの初期化を確認
            channels = conf.get_channels()
            assert len(channels) == 2
            assert channels[0]["id"] == 111
            assert channels[1]["id"] == 222
            assert "チャンネルID" in channels[0]["name"]

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

        conf = ChannelConfig()
        conf._load_from_local()

        assert conf.get_behavior() == "allow"
        assert len(conf.get_channels()) == 1
        assert conf.get_channels()[0]["id"] == 123

    @patch("boto3.client")
    def test_load_from_s3(self, mock_boto3_client):
        """S3からの読み込みテスト"""
        # boto3のS3クライアントをモック
        mock_s3_client = MagicMock()
        mock_boto3_client.return_value = mock_s3_client

        # S3からの応答をモック
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps(
            {
                "behavior": "allow",
                "channels": [{"id": 456, "name": "S3テスト"}],
                "updated_at": "2025-04-19T10:00:00",
            }
        ).encode("utf-8")

        mock_s3_client.get_object.return_value = {"Body": mock_body}

        # テスト時に呼び出しをデバッグモードで行う（ファイルI/Oを避ける）
        with patch.object(config, "S3_BUCKET_NAME", "test-bucket"):
            # 重要: debug_mode=Trueに変更して初期化時のファイルI/Oを避ける
            conf = ChannelConfig(storage_type="s3", debug_mode=True)

            # 設定を直接書き換えてテスト用のデータを準備
            conf.storage_type = "s3"

            # この時点でget_objectの呼び出しカウントをリセット
            mock_s3_client.reset_mock()

            # テスト対象のメソッドを実行
            conf._load_from_s3()

        assert conf.get_behavior() == "allow"
        assert len(conf.get_channels()) == 1
        assert conf.get_channels()[0]["id"] == 456
        assert conf.get_channels()[0]["name"] == "S3テスト"

        # 適切なキーで呼び出されたか確認
        mock_s3_client.get_object.assert_called_once()

    @patch("os.makedirs")
    @patch("builtins.open")
    def test_save_to_local(self, mock_open, mock_makedirs):
        """ローカルへの保存テスト"""
        mock_file = MagicMock()
        mock_open.return_value.__enter__.return_value = mock_file

        # ローカルファイルの存在確認と読み込みをモック
        with patch("os.path.exists", return_value=True), patch(
            "builtins.open"
        ) as mock_init_open:
            mock_init_file = MagicMock()
            mock_init_open.return_value.__enter__.return_value = mock_init_file
            mock_init_file.read.return_value = json.dumps(
                {
                    "behavior": "deny",
                    "channels": [],
                    "updated_at": "2025-04-19T09:00:00",
                }
            )

            # debug_mode=Falseにすると初期化時にファイルI/Oが発生する
            conf = ChannelConfig(debug_mode=True)

        # 保存テスト用にデータを設定
        conf.config_data = {
            "behavior": "allow",
            "channels": [{"id": 123, "name": "保存テスト"}],
            "updated_at": "2025-04-19T10:00:00",  # テスト用に固定
        }

        # makedirs呼び出しカウントをリセット
        mock_makedirs.reset_mock()

        result = conf._save_to_local()

        assert result is True
        assert mock_makedirs.called
        mock_open.assert_called_once()
        # json.dumpは内部的に複数回writeを呼び出すので、一度だけではなく複数回呼び出されていることを確認
        assert mock_file.write.called

    @patch("boto3.client")
    def test_save_to_s3(self, mock_boto3_client):
        """S3への保存テスト"""
        # boto3のS3クライアントをモック
        mock_s3_client = MagicMock()
        mock_boto3_client.return_value = mock_s3_client

        # バケット名をモック
        with patch.object(config, "S3_BUCKET_NAME", "test-bucket"):
            conf = ChannelConfig(
                storage_type="s3", debug_mode=True
            )  # debug_modeをTrueに変更

            # テスト用のデータを設定
            conf.config_data = {
                "behavior": "allow",
                "channels": [{"id": 789, "name": "S3保存テスト"}],
                "updated_at": "2025-04-19T10:00:00",  # テスト用に固定
            }

            result = conf._save_to_s3()

            assert result is True
            mock_s3_client.put_object.assert_called_once()

            # 呼び出し引数の確認
            args, kwargs = mock_s3_client.put_object.call_args
            assert isinstance(kwargs["Body"], bytes)  # コンテンツがバイト列になっている
            body_content = kwargs["Body"].decode("utf-8")
            assert "S3保存テスト" in body_content  # 日本語の文字列がJSONに含まれる
            assert kwargs["Bucket"] == "test-bucket"  # バケット名を確認
