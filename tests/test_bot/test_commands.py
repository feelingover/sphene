"""bot/commands.pyのテスト"""

from unittest.mock import MagicMock, patch

import pytest
from discord import app_commands

import config
from bot.commands import (
    cmd_list_channels,
    handle_command_error,
    setup_commands,
)


@pytest.mark.asyncio
async def test_cmd_list_channels(
    mock_discord_client: MagicMock, mock_discord_interaction: MagicMock
) -> None:
    """チャンネル一覧コマンドのテスト"""
    # チャンネル一覧のテスト

    # guildのモック
    mock_guild = MagicMock()
    mock_guild.id = 54321
    mock_discord_interaction.guild = mock_guild

    # チャンネル設定のモック
    mock_channel_config = MagicMock()
    mock_channel_config.get_behavior.return_value = "deny"
    mock_channel_config.get_mode_display_name.return_value = "全体モード"
    mock_channel_config.get_list_display_name.return_value = "拒否チャンネルリスト"
    mock_channel_config.get_channels.return_value = [
        {"id": 123456789, "name": "テストチャンネル1"},
        {"id": 987654321, "name": "テストチャンネル2"},
    ]

    # ConfigManagerのモック
    mock_config_manager = MagicMock()
    mock_config_manager.get_config.return_value = mock_channel_config

    # ConfigManagerをパッチ
    with patch("bot.commands.config_manager", mock_config_manager):
        # コマンド実行
        await cmd_list_channels(mock_discord_client, mock_discord_interaction)

        # config_manager.get_configが呼ばれたかチェック
        mock_config_manager.get_config.assert_called_once_with(54321)

        # レスポンスが送信されたかチェック
        mock_discord_interaction.response.send_message.assert_called_once()

        # レスポンスに必要な情報が含まれているかチェック
        args = mock_discord_interaction.response.send_message.call_args[0][0]
        assert "拒否チャンネルリスト" in args
        assert "123456789" in args


@pytest.mark.asyncio
async def test_cmd_list_channels_no_restrictions(
    mock_discord_client: MagicMock, mock_discord_interaction: MagicMock
) -> None:
    """チャンネル制限なしの場合のテスト"""
    # guildのモック
    mock_guild = MagicMock()
    mock_guild.id = 54321
    mock_discord_interaction.guild = mock_guild

    # チャンネル設定のモック
    mock_channel_config = MagicMock()
    mock_channel_config.get_behavior.return_value = "deny"
    mock_channel_config.get_mode_display_name.return_value = "全体モード"
    mock_channel_config.get_list_display_name.return_value = "拒否チャンネルリスト"
    # 空のチャンネルリストを設定
    mock_channel_config.get_channels.return_value = []

    # ConfigManagerのモック
    mock_config_manager = MagicMock()
    mock_config_manager.get_config.return_value = mock_channel_config

    # ConfigManagerをパッチ
    with patch("bot.commands.config_manager", mock_config_manager):
        # コマンド実行
        await cmd_list_channels(mock_discord_client, mock_discord_interaction)

        # config_manager.get_configが呼ばれたかチェック
        mock_config_manager.get_config.assert_called_once_with(54321)

        # レスポンスに「全てのチャンネルで発言可能」が含まれているか
        args = mock_discord_interaction.response.send_message.call_args[0][0]
        assert "全てのチャンネルで発言可能" in args



@pytest.mark.asyncio
async def test_handle_command_error_missing_permissions(
    mock_discord_interaction: MagicMock,
) -> None:
    """権限不足エラーのテスト"""
    error = app_commands.errors.MissingPermissions(["administrator"])

    await handle_command_error(mock_discord_interaction, error)

    # エラーメッセージが送信されたか
    mock_discord_interaction.response.send_message.assert_called_once()
    args = mock_discord_interaction.response.send_message.call_args[0][0]
    assert "管理者権限が必要" in args
    assert (
        mock_discord_interaction.response.send_message.call_args[1]["ephemeral"] is True
    )


@pytest.mark.asyncio
async def test_handle_command_error_general(
    mock_discord_interaction: MagicMock,
) -> None:
    """一般的なエラーのテスト"""
    error = app_commands.AppCommandError("テストエラー")

    await handle_command_error(mock_discord_interaction, error)

    # エラーメッセージが送信されたか
    mock_discord_interaction.response.send_message.assert_called_once()
    args = mock_discord_interaction.response.send_message.call_args[0][0]
    assert "エラーが発生" in args
    assert "テストエラー" in args


def test_setup_commands() -> None:
    """スラッシュコマンドのセットアップをテスト"""
    mock_bot = MagicMock()

    # コマンドグループをセットアップ
    command_group = setup_commands(mock_bot)

    # コマンドグループが作成されたか
    assert isinstance(command_group, app_commands.Group)
    assert command_group.name == config.COMMAND_GROUP_NAME

    # コマンドが追加されたか
    command_names = [cmd.name for cmd in command_group.commands]
    assert "channels" in command_names
    assert "reset" not in command_names
    assert "reload_prompt" not in command_names
    assert "updatelist" not in command_names
