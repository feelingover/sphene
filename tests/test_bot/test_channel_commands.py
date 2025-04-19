"""
チャンネル関連コマンドのテスト
"""

# type: ignore
# mypy: ignore-errors

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.commands import (
    cmd_add_channel,
    cmd_clear_channels,
    cmd_list_channels,
    cmd_mode,
    cmd_remove_channel,
    cmd_update_list,
)


class TestChannelCommands:
    """チャンネル関連コマンドのテスト"""

    @pytest.mark.asyncio
    @patch("bot.commands.config_manager")
    async def test_mode_command(self, mock_config_manager):
        """modeコマンドのテスト"""
        # モックguild設定
        mock_guild = MagicMock()
        mock_guild.id = 123456

        # モックチャンネル設定
        mock_channel_config = MagicMock()
        mock_channel_config.get_mode_display_name.return_value = "全体モード"
        mock_channel_config.get_list_display_name.return_value = "拒否チャンネルリスト"

        # マネージャーからチャンネル設定を返すようにセット
        mock_config_manager.get_config.return_value = mock_channel_config

        # インタラクションのモック
        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()
        interaction.guild = mock_guild

        # コマンド実行
        await cmd_mode(interaction)

        # アサーション
        interaction.response.send_message.assert_called_once()
        # コンフィグマネージャーがguild_idで呼び出されたことを確認
        mock_config_manager.get_config.assert_called_once_with(mock_guild.id)
        # モードとリスト表示名の取得を確認
        mock_channel_config.get_mode_display_name.assert_called_once()
        mock_channel_config.get_list_display_name.assert_called_once()
        # Viewオブジェクトが渡されたことを確認
        args, kwargs = interaction.response.send_message.call_args
        assert "view" in kwargs

    @pytest.mark.asyncio
    @patch("bot.commands.config_manager")
    async def test_list_channels_command_empty(self, mock_config_manager):
        """チャンネル一覧コマンドのテスト（空リスト）"""
        # モックguild設定
        mock_guild = MagicMock()
        mock_guild.id = 123456

        # モックチャンネル設定
        mock_channel_config = MagicMock()
        mock_channel_config.get_behavior.return_value = "deny"
        mock_channel_config.get_mode_display_name.return_value = "全体モード"
        mock_channel_config.get_list_display_name.return_value = "拒否チャンネルリスト"
        mock_channel_config.get_channels.return_value = []  # 空リスト

        # マネージャーからチャンネル設定を返すようにセット
        mock_config_manager.get_config.return_value = mock_channel_config

        # インタラクションのモック
        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()
        interaction.guild = mock_guild

        # ボットのモック
        bot = MagicMock()

        # コマンド実行
        await cmd_list_channels(bot, interaction)

        # アサーション
        interaction.response.send_message.assert_called_once()
        mock_config_manager.get_config.assert_called_once_with(mock_guild.id)

        # メッセージに「リストは空です」が含まれていることを確認
        args, kwargs = interaction.response.send_message.call_args
        assert "リストは空です" in args[0]

    @pytest.mark.asyncio
    @patch("bot.commands.config_manager")
    async def test_list_channels_command_with_channels(self, mock_config_manager):
        """チャンネル一覧コマンドのテスト（複数チャンネル）"""
        # モックguild設定
        mock_guild = MagicMock()
        mock_guild.id = 123456

        # モックチャンネル設定
        mock_channel_config = MagicMock()
        mock_channel_config.get_behavior.return_value = "allow"
        mock_channel_config.get_mode_display_name.return_value = "限定モード"
        mock_channel_config.get_list_display_name.return_value = "許可チャンネルリスト"

        # テスト用チャンネルリスト
        mock_channels = [
            {"id": 111, "name": "チャンネル1"},
            {"id": 222, "name": "チャンネル2"},
        ]
        mock_channel_config.get_channels.return_value = mock_channels

        # マネージャーからチャンネル設定を返すようにセット
        mock_config_manager.get_config.return_value = mock_channel_config

        # インタラクションのモック
        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()
        interaction.guild = mock_guild

        # ボットのモック
        bot = MagicMock()
        channel1 = MagicMock()
        channel1.name = "実際のチャンネル1"
        bot.get_channel.return_value = channel1

        # コマンド実行
        await cmd_list_channels(bot, interaction, page=1)

        # アサーション
        interaction.response.send_message.assert_called_once()
        mock_config_manager.get_config.assert_called_once_with(mock_guild.id)

        # チャンネル情報がメッセージに含まれていることを確認
        args, kwargs = interaction.response.send_message.call_args
        assert "限定モード" in args[0]
        assert "許可チャンネルリスト" in args[0]
        assert "実際のチャンネル1" in args[0]

    @pytest.mark.asyncio
    @patch("bot.commands.config_manager")
    async def test_add_channel_command(self, mock_config_manager):
        """チャンネル追加コマンドのテスト"""
        # モックguild設定
        mock_guild = MagicMock()
        mock_guild.id = 123456

        # モックチャンネル設定
        mock_channel_config = MagicMock()
        mock_channel_config.add_channel.return_value = True
        mock_channel_config.get_list_display_name.return_value = "許可チャンネルリスト"

        # マネージャーからチャンネル設定を返すようにセット
        mock_config_manager.get_config.return_value = mock_channel_config

        # インタラクションのモック
        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()
        interaction.guild = mock_guild

        # チャンネルのモック
        channel = MagicMock()
        channel.id = 12345
        channel.name = "テストチャンネル"
        interaction.channel = channel

        # コマンド実行
        await cmd_add_channel(interaction)

        # アサーション
        mock_config_manager.get_config.assert_called_once_with(mock_guild.id)
        mock_channel_config.add_channel.assert_called_once_with(
            12345, "テストチャンネル"
        )
        interaction.response.send_message.assert_called_once()

        # 成功メッセージが表示されていることを確認
        args, kwargs = interaction.response.send_message.call_args
        assert "✅" in args[0]
        assert "テストチャンネル" in args[0]

    @pytest.mark.asyncio
    @patch("bot.commands.config_manager")
    async def test_add_channel_command_failure(self, mock_config_manager):
        """チャンネル追加失敗のテスト"""
        # モックguild設定
        mock_guild = MagicMock()
        mock_guild.id = 123456

        # モックチャンネル設定
        mock_channel_config = MagicMock()
        mock_channel_config.add_channel.return_value = False

        # マネージャーからチャンネル設定を返すようにセット
        mock_config_manager.get_config.return_value = mock_channel_config

        # インタラクションのモック
        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()
        interaction.guild = mock_guild

        # チャンネルのモック
        channel = MagicMock()
        channel.id = 12345
        channel.name = "テストチャンネル"
        interaction.channel = channel

        # コマンド実行
        await cmd_add_channel(interaction)

        # アサーション
        mock_config_manager.get_config.assert_called_once_with(mock_guild.id)
        # 失敗メッセージが表示されることを確認
        args, kwargs = interaction.response.send_message.call_args
        assert "❌" in args[0]

    @pytest.mark.asyncio
    @patch("bot.commands.config_manager")
    async def test_remove_channel_command(self, mock_config_manager):
        """チャンネル削除コマンドのテスト"""
        # モックguild設定
        mock_guild = MagicMock()
        mock_guild.id = 123456

        # モックチャンネル設定
        mock_channel_config = MagicMock()
        mock_channel_config.remove_channel.return_value = True
        mock_channel_config.is_channel_in_list.return_value = (
            False  # 削除後にリストに存在しない
        )
        mock_channel_config.get_list_display_name.return_value = "拒否チャンネルリスト"

        # マネージャーからチャンネル設定を返すようにセット
        mock_config_manager.get_config.return_value = mock_channel_config

        # インタラクションのモック
        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()
        interaction.guild = mock_guild

        # チャンネルのモック
        channel = MagicMock()
        channel.id = 12345
        channel.name = "テストチャンネル"
        interaction.channel = channel

        # コマンド実行
        await cmd_remove_channel(interaction)

        # アサーション
        mock_config_manager.get_config.assert_called_once_with(mock_guild.id)
        mock_channel_config.remove_channel.assert_called_once_with(12345)
        interaction.response.send_message.assert_called_once()

        # 成功メッセージが表示されていることを確認
        args, kwargs = interaction.response.send_message.call_args
        assert "✅" in args[0]
        assert "テストチャンネル" in args[0]

    @pytest.mark.asyncio
    @patch("bot.commands.config_manager")
    async def test_clear_channels_command(self, mock_config_manager):
        """チャンネルクリアコマンドのテスト"""
        # モックguild設定
        mock_guild = MagicMock()
        mock_guild.id = 123456

        # モックチャンネル設定
        mock_channel_config = MagicMock()
        mock_channel_config.get_list_display_name.return_value = "拒否チャンネルリスト"

        # マネージャーからチャンネル設定を返すようにセット
        mock_config_manager.get_config.return_value = mock_channel_config

        # インタラクションのモック
        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()
        interaction.guild = mock_guild

        # コマンド実行
        await cmd_clear_channels(interaction)

        # アサーション
        mock_config_manager.get_config.assert_called_once_with(mock_guild.id)
        interaction.response.send_message.assert_called_once()
        args, kwargs = interaction.response.send_message.call_args
        assert "クリアしますか" in args[0]
        assert "view" in kwargs

    @pytest.mark.asyncio
    @patch("bot.commands.config_manager")
    async def test_update_list_command_success(self, mock_config_manager):
        """チャンネルリスト保存コマンドのテスト（成功）"""
        # モックguild設定
        mock_guild = MagicMock()
        mock_guild.id = 123456

        # モックチャンネル設定
        mock_channel_config = MagicMock()
        mock_channel_config.save_config.return_value = True
        mock_channel_config.get_list_display_name.return_value = "拒否チャンネルリスト"
        mock_channel_config.storage_type = "local"

        # マネージャーからチャンネル設定を返すようにセット
        mock_config_manager.get_config.return_value = mock_channel_config

        # インタラクションのモック
        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()
        interaction.guild = mock_guild

        # コマンド実行
        await cmd_update_list(interaction)

        # アサーション
        mock_config_manager.get_config.assert_called_once_with(mock_guild.id)
        mock_channel_config.save_config.assert_called_once()
        interaction.response.send_message.assert_called_once()

        # 成功メッセージが表示されていることを確認
        args, kwargs = interaction.response.send_message.call_args
        assert "✅" in args[0]
        assert "保存しました" in args[0]

    @pytest.mark.asyncio
    @patch("bot.commands.config_manager")
    async def test_update_list_command_failure(self, mock_config_manager):
        """チャンネルリスト保存コマンドのテスト（失敗）"""
        # モックguild設定
        mock_guild = MagicMock()
        mock_guild.id = 123456

        # モックチャンネル設定
        mock_channel_config = MagicMock()
        mock_channel_config.save_config.return_value = False
        mock_channel_config.get_list_display_name.return_value = "拒否チャンネルリスト"

        # マネージャーからチャンネル設定を返すようにセット
        mock_config_manager.get_config.return_value = mock_channel_config

        # インタラクションのモック
        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()
        interaction.guild = mock_guild

        # コマンド実行
        await cmd_update_list(interaction)

        # アサーション
        mock_config_manager.get_config.assert_called_once_with(mock_guild.id)
        mock_channel_config.save_config.assert_called_once()
        interaction.response.send_message.assert_called_once()

        # 失敗メッセージが表示されていることを確認
        args, kwargs = interaction.response.send_message.call_args
        assert "❌" in args[0]
        assert "失敗" in args[0]

    @pytest.mark.asyncio
    @patch("bot.commands.config_manager")
    async def test_commands_without_guild(self, mock_config_manager):
        """ギルドなしの場合のエラーメッセージテスト"""
        # インタラクションのモック（guild=Noneに設定）
        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()
        interaction.guild = None

        # 各コマンドをテスト
        await cmd_mode(interaction)
        await cmd_add_channel(interaction)
        await cmd_remove_channel(interaction)
        await cmd_clear_channels(interaction)
        await cmd_update_list(interaction)

        # 各コマンドで同じエラーメッセージが表示されていることを確認
        assert interaction.response.send_message.call_count == 5
        for i in range(5):
            args, kwargs = interaction.response.send_message.call_args_list[i]
            assert "サーバー内でのみ使用できます" in args[0]
