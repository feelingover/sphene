"""
can_bot_speak メソッドの詳細なテスト
"""

from utils.channel_config import ChannelConfig


class TestChannelSpeak:
    """チャンネルでの発言可否判定のテスト"""

    def test_can_bot_speak_deny_mode(self) -> None:
        """全体モード（deny）でのテスト"""
        # デバッグモードでインスタンス作成
        config = ChannelConfig(debug_mode=True)

        # 全体モード（deny）に設定
        config.config_data["behavior"] = "deny"

        # 整数型と文字列型のIDが混在したチャンネルリスト
        config.config_data["channels"] = [
            {"id": "123456", "name": "チャンネル1"},
            {"id": 789012, "name": "チャンネル2"},
        ]

        # リストにあるチャンネルでは発言できない
        assert config.can_bot_speak(123456) is False
        assert config.can_bot_speak(789012) is False

        # リストにないチャンネルでは発言できる
        assert config.can_bot_speak(111111) is True

    def test_can_bot_speak_allow_mode(self) -> None:
        """限定モード（allow）でのテスト"""
        # デバッグモードでインスタンス作成
        config = ChannelConfig(debug_mode=True)

        # 限定モード（allow）に設定
        config.config_data["behavior"] = "allow"

        # 整数型と文字列型のIDが混在したチャンネルリスト
        config.config_data["channels"] = [
            {"id": "123456", "name": "チャンネル1"},
            {"id": 789012, "name": "チャンネル2"},
        ]

        # リストにあるチャンネルでのみ発言できる
        assert config.can_bot_speak(123456) is True
        assert config.can_bot_speak(789012) is True

        # リストにないチャンネルでは発言できない
        assert config.can_bot_speak(111111) is False

    def test_loading_mechanism(self) -> None:
        """設定読み込み後のcan_bot_speak動作確認"""
        # デバッグモードなしでインスタンス作成
        # (この場合、_initialize_from_envが呼ばれる可能性がある)
        config = ChannelConfig(debug_mode=True)

        # 全体モード（deny）に設定
        config.config_data["behavior"] = "deny"

        # チャンネルリストを設定
        config.config_data["channels"] = [
            {"id": "123456", "name": "チャンネル1"},
            {"id": 789012, "name": "チャンネル2"},
        ]

        # リストにあるチャンネルでは発言できないことを確認
        assert (
            config.is_channel_in_list(123456) is True
        )  # まずリストに含まれていることを確認
        assert config.can_bot_speak(123456) is False  # リストに含まれるので発言不可

        # リストにないチャンネルでは発言できることを確認
        assert (
            config.is_channel_in_list(111111) is False
        )  # リストに含まれていないことを確認
        assert config.can_bot_speak(111111) is True  # リストに含まれないので発言可能
