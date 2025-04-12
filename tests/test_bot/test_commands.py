"""bot/commands.pyのテスト"""

from unittest.mock import MagicMock, patch

import pytest
from discord import app_commands

import config
from bot.commands import (
    cmd_list_channels,
    cmd_reset_conversation,
    handle_command_error,
    setup_commands,
)


@pytest.mark.asyncio
async def test_cmd_list_channels(
    mock_discord_client: MagicMock, mock_discord_interaction: MagicMock
) -> None:
    """チャンネル一覧コマンドのテスト"""
    # 許可チャンネルIDのモック
    allowed_channels = [123456789, 987654321]
    with patch.object(config, "ALLOWED_CHANNEL_IDS", allowed_channels):
        # コマンド実行
        await cmd_list_channels(mock_discord_client, mock_discord_interaction)

        # レスポンスが送信されたかチェック
        mock_discord_interaction.response.send_message.assert_called_once()

        # レスポンスに必要な情報が含まれているかチェック
        args = mock_discord_interaction.response.send_message.call_args[0][0]
        assert "使用可能チャンネル一覧" in args
        assert "テストチャンネル" in args
        assert "123456789" in args
        assert "987654321" in args


@pytest.mark.asyncio
async def test_cmd_list_channels_no_restrictions(
    mock_discord_client: MagicMock, mock_discord_interaction: MagicMock
) -> None:
    """チャンネル制限なしの場合のテスト"""
    # 許可チャンネルIDが空のケース
    with patch.object(config, "ALLOWED_CHANNEL_IDS", []):
        # コマンド実行
        await cmd_list_channels(mock_discord_client, mock_discord_interaction)

        # レスポンスに「全てのチャンネルで使用可能」が含まれているか
        args = mock_discord_interaction.response.send_message.call_args[0][0]
        assert "全てのチャンネルで使用可能です" in args


@pytest.mark.asyncio
async def test_cmd_reset_conversation(mock_discord_interaction: MagicMock) -> None:
    """会話履歴リセットコマンドのテスト"""
    # ユーザーIDを設定
    user_id = str(mock_discord_interaction.user.id)

    # user_conversationsのモック
    mock_conversations = {user_id: MagicMock()}
    with patch("bot.commands.user_conversations", mock_conversations), patch(
        "bot.commands.load_system_prompt"
    ) as mock_load_prompt, patch("bot.commands.Sphene") as mock_sphene_cls:
        mock_load_prompt.return_value = "テストシステムプロンプト"
        mock_sphene = MagicMock()
        mock_sphene_cls.return_value = mock_sphene

        # コマンド実行 - 既存の会話がある場合
        await cmd_reset_conversation(mock_discord_interaction)

        # 新しいSpheneインスタンスが作成されたか
        mock_sphene_cls.assert_called_once_with(
            system_setting=mock_load_prompt.return_value
        )

        # 会話がリセットされたか
        assert mock_conversations[user_id] == mock_sphene

        # レスポンスが送信されたか
        mock_discord_interaction.response.send_message.assert_called_once()
        args = mock_discord_interaction.response.send_message.call_args[0][0]
        assert "会話履歴をリセットしたよ" in args


@pytest.mark.asyncio
async def test_cmd_reset_conversation_new_user(
    mock_discord_interaction: MagicMock,
) -> None:
    """初めてのユーザーの会話リセットテスト"""
    # 空の会話辞書でモック
    with patch("bot.commands.user_conversations", {}):
        # コマンド実行 - 既存の会話がない場合
        await cmd_reset_conversation(mock_discord_interaction)

        # 適切なレスポンスが送信されたか
        mock_discord_interaction.response.send_message.assert_called_once()
        args = mock_discord_interaction.response.send_message.call_args[0][0]
        assert "まだ話したことがないみたいだね" in args


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
    assert "reset" in command_names
