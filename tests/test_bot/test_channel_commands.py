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
    @patch("bot.commands.channel_config")
    async def test_mode_command(self, mock_channel_config):
        """modeコマンドのテスト"""
        # モックのセットアップ
        mock_channel_config.get_mode_display_name.return_value = "全体モード"
        mock_channel_config.get_list_display_name.return_value = "拒否チャンネルリスト"

        # インタラクションのモック
        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()

        # コマンド実行
        await cmd_mode(interaction)

        # アサーション
        interaction.response.send_message.assert_called_once()
        # モードとリスト表示名の取得を確認
        mock_channel_config.get_mode_display_name.assert_called_once()
        mock_channel_config.get_list_display_name.assert_called_once()
        # Viewオブジェクトが渡されたことを確認
        args, kwargs = interaction.response.send_message.call_args
        assert "view" in kwargs

    @pytest.mark.asyncio
    @patch("bot.commands.channel_config")
    async def test_list_channels_command_empty(self, mock_channel_config):
        """チャンネル一覧コマンドのテスト（空リスト）"""
        # モックのセットアップ
        mock_channel_config.get_behavior.return_value = "deny"
        mock_channel_config.get_mode_display_name.return_value = "全体モード"
        mock_channel_config.get_list_display_name.return_value = "拒否チャンネルリスト"
        mock_channel_config.get_channels.return_value = []  # 空リスト

        # インタラクションのモック
        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()

        # ボットのモック
        bot = MagicMock()

        # コマンド実行
        await cmd_list_channels(bot, interaction)

        # アサーション
        interaction.response.send_message.assert_called_once()

        # メッセージに「リストは空です」が含まれていることを確認
        args, kwargs = interaction.response.send_message.call_args
        assert "リストは空です" in args[0]

    @pytest.mark.asyncio
    @patch("bot.commands.channel_config")
    async def test_list_channels_command_with_channels(self, mock_channel_config):
        """チャンネル一覧コマンドのテスト（複数チャンネル）"""
        # モックのセットアップ
        mock_channel_config.get_behavior.return_value = "allow"
        mock_channel_config.get_mode_display_name.return_value = "限定モード"
        mock_channel_config.get_list_display_name.return_value = "許可チャンネルリスト"

        # テスト用チャンネルリスト
        mock_channels = [
            {"id": 111, "name": "チャンネル1"},
            {"id": 222, "name": "チャンネル2"},
        ]
        mock_channel_config.get_channels.return_value = mock_channels

        # インタラクションのモック
        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()

        # ボットのモック
        bot = MagicMock()
        channel1 = MagicMock()
        channel1.name = "実際のチャンネル1"
        bot.get_channel.return_value = channel1

        # コマンド実行
        await cmd_list_channels(bot, interaction, page=1)

        # アサーション
        interaction.response.send_message.assert_called_once()

        # チャンネル情報がメッセージに含まれていることを確認
        args, kwargs = interaction.response.send_message.call_args
        assert "限定モード" in args[0]
        assert "許可チャンネルリスト" in args[0]
        assert "実際のチャンネル1" in args[0]

    @pytest.mark.asyncio
    @patch("bot.commands.channel_config")
    async def test_add_channel_command(self, mock_channel_config):
        """チャンネル追加コマンドのテスト"""
        # モックのセットアップ
        mock_channel_config.add_channel.return_value = True
        mock_channel_config.get_list_display_name.return_value = "許可チャンネルリスト"

        # インタラクションのモック
        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()

        # チャンネルのモック
        channel = MagicMock()
        channel.id = 12345
        channel.name = "テストチャンネル"
        interaction.channel = channel

        # コマンド実行
        await cmd_add_channel(interaction)

        # アサーション
        mock_channel_config.add_channel.assert_called_once_with(
            12345, "テストチャンネル"
        )
        interaction.response.send_message.assert_called_once()

        # 成功メッセージが表示されていることを確認
        args, kwargs = interaction.response.send_message.call_args
        assert "✅" in args[0]
        assert "テストチャンネル" in args[0]

    @pytest.mark.asyncio
    @patch("bot.commands.channel_config")
    async def test_add_channel_command_failure(self, mock_channel_config):
        """チャンネル追加失敗のテスト"""
        # モックのセットアップ - 追加失敗
        mock_channel_config.add_channel.return_value = False

        # インタラクションのモック
        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()

        # チャンネルのモック
        channel = MagicMock()
        channel.id = 12345
        channel.name = "テストチャンネル"
        interaction.channel = channel

        # コマンド実行
        await cmd_add_channel(interaction)

        # アサーション - 失敗メッセージが表示されることを確認
        args, kwargs = interaction.response.send_message.call_args
        assert "❌" in args[0]

    @pytest.mark.asyncio
    @patch("bot.commands.channel_config")
    async def test_remove_channel_command(self, mock_channel_config):
        """チャンネル削除コマンドのテスト"""
        # モックのセットアップ
        mock_channel_config.remove_channel.return_value = True
        mock_channel_config.is_channel_in_list.return_value = (
            False  # 削除後にリストに存在しない
        )
        mock_channel_config.get_list_display_name.return_value = "拒否チャンネルリスト"

        # インタラクションのモック
        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()

        # チャンネルのモック
        channel = MagicMock()
        channel.id = 12345
        channel.name = "テストチャンネル"
        interaction.channel = channel

        # コマンド実行
        await cmd_remove_channel(interaction)

        # アサーション
        mock_channel_config.remove_channel.assert_called_once_with(12345)
        interaction.response.send_message.assert_called_once()

        # 成功メッセージが表示されていることを確認
        args, kwargs = interaction.response.send_message.call_args
        assert "✅" in args[0]
        assert "テストチャンネル" in args[0]

    @pytest.mark.asyncio
    @patch("bot.commands.channel_config")
    async def test_clear_channels_command(self, mock_channel_config):
        """チャンネルクリアコマンドのテスト"""
        # モックのセットアップ
        mock_channel_config.get_list_display_name.return_value = "拒否チャンネルリスト"

        # インタラクションのモック
        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()

        # コマンド実行
        await cmd_clear_channels(interaction)

        # アサーション - 確認ビューが表示されること
        interaction.response.send_message.assert_called_once()
        args, kwargs = interaction.response.send_message.call_args
        assert "クリアしますか" in args[0]
        assert "view" in kwargs

    @pytest.mark.asyncio
    @patch("bot.commands.channel_config")
    async def test_update_list_command_success(self, mock_channel_config):
        """チャンネルリスト保存コマンドのテスト（成功）"""
        # モックのセットアップ
        mock_channel_config.save_config.return_value = True
        mock_channel_config.get_list_display_name.return_value = "拒否チャンネルリスト"
        mock_channel_config.storage_type = "local"

        # インタラクションのモック
        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()

        # コマンド実行
        await cmd_update_list(interaction)

        # アサーション
        mock_channel_config.save_config.assert_called_once()
        interaction.response.send_message.assert_called_once()

        # 成功メッセージが表示されていることを確認
        args, kwargs = interaction.response.send_message.call_args
        assert "✅" in args[0]
        assert "保存しました" in args[0]

    @pytest.mark.asyncio
    @patch("bot.commands.channel_config")
    async def test_update_list_command_failure(self, mock_channel_config):
        """チャンネルリスト保存コマンドのテスト（失敗）"""
        # モックのセットアップ
        mock_channel_config.save_config.return_value = False
        mock_channel_config.get_list_display_name.return_value = "拒否チャンネルリスト"

        # インタラクションのモック
        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()

        # コマンド実行
        await cmd_update_list(interaction)

        # アサーション
        mock_channel_config.save_config.assert_called_once()
        interaction.response.send_message.assert_called_once()

        # 失敗メッセージが表示されていることを確認
        args, kwargs = interaction.response.send_message.call_args
        assert "❌" in args[0]
        assert "失敗" in args[0]
