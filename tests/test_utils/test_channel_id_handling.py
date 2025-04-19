"""
チャンネルID処理に関するテスト
文字列型と整数型のIDが正しく扱われるかをテスト
"""

from utils.channel_config import ChannelConfig


class TestChannelIdHandling:
    """チャンネルID型処理のテスト"""

    def test_is_channel_in_list_with_string_id(self) -> None:
        """文字列型のチャンネルIDがリストに含まれるか正しく判定できるかテスト"""
        # デバッグモードでインスタンス作成（ファイルI/Oなし）
        config = ChannelConfig(guild_id="test_guild", debug_mode=True)

        # 文字列型のIDをリストに追加
        config.config_data["channels"] = [
            {"id": "123456", "name": "テストチャンネル1"},
            {"id": "789012", "name": "テストチャンネル2"},
        ]

        # 整数型のIDで検索して正しく見つかることを確認
        assert config.is_channel_in_list(123456) is True
        assert config.is_channel_in_list(789012) is True
        assert config.is_channel_in_list(999999) is False

    def test_is_channel_in_list_with_integer_id(self) -> None:
        """整数型のチャンネルIDがリストに含まれるか正しく判定できるかテスト"""
        # デバッグモードでインスタンス作成（ファイルI/Oなし）
        config = ChannelConfig(guild_id="test_guild", debug_mode=True)

        # 整数型のIDをリストに追加
        config.config_data["channels"] = [
            {"id": 123456, "name": "テストチャンネル1"},
            {"id": 789012, "name": "テストチャンネル2"},
        ]

        # 整数型のIDで検索して正しく見つかることを確認
        assert config.is_channel_in_list(123456) is True
        assert config.is_channel_in_list(789012) is True
        assert config.is_channel_in_list(999999) is False

    def test_remove_channel_with_different_id_types(self) -> None:
        """異なる型のIDでもチャンネルが正しく削除されることをテスト"""
        # デバッグモードでインスタンス作成（ファイルI/Oなし）
        config = ChannelConfig(guild_id="test_guild", debug_mode=True)

        # 文字列型と整数型の混在したIDをリストに追加
        config.config_data["channels"] = [
            {"id": "123456", "name": "テストチャンネル1"},
            {"id": 789012, "name": "テストチャンネル2"},
        ]

        # 整数型のIDで削除
        config.remove_channel(123456)

        # 削除されたことを確認
        assert config.is_channel_in_list(123456) is False
        assert config.is_channel_in_list(789012) is True

        # 文字列のIDでも削除できることを確認
        config.remove_channel(789012)
        assert config.is_channel_in_list(789012) is False
