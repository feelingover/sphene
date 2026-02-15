"""
bot/commands.py の広範なテスト
"""

# type: ignore
# mypy: ignore-errors

from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest
import discord

from bot.commands import (
    ModeSelect,
    TranslationSelect,
    ClearConfirmView,
    cmd_list_channels,
    cmd_remove_channel,
    cmd_reload_prompt,
    handle_command_error,
    _format_channel_info,
)


class TestCommandsExtensive:
    """スラッシュコマンドの広範なテスト"""

    @pytest.mark.asyncio
    @patch("bot.commands.config_manager")
    async def test_mode_select_callback(self, mock_config_manager):
        """モード選択ドロップダウンのコールバックテスト"""
        mock_config = MagicMock()
        mock_config.set_behavior.return_value = True
        mock_config_manager.get_config.return_value = mock_config
        
        interaction = MagicMock(spec=discord.Interaction)
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()
        
        select = ModeSelect(guild_id=123)
        with patch.object(ModeSelect, "values", new_callable=PropertyMock) as mock_values:
            mock_values.return_value = ["allow"]
            await select.callback(interaction)
        
        mock_config.set_behavior.assert_called_once_with("allow")
        interaction.response.send_message.assert_called_once()
        assert "限定モード" in interaction.response.send_message.call_args[0][0]

    @pytest.mark.asyncio
    @patch("bot.commands.config_manager")
    async def test_translation_select_callback(self, mock_config_manager):
        """翻訳設定ドロップダウンのコールバックテスト"""
        mock_config = MagicMock()
        mock_config.set_translation_enabled.return_value = True
        mock_config_manager.get_config.return_value = mock_config
        
        interaction = MagicMock(spec=discord.Interaction)
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()
        
        select = TranslationSelect(guild_id=123)
        with patch.object(TranslationSelect, "values", new_callable=PropertyMock) as mock_values:
            mock_values.return_value = ["true"]
            await select.callback(interaction)
        
        mock_config.set_translation_enabled.assert_called_once_with(True)
        interaction.response.send_message.assert_called_once()
        assert "有効" in interaction.response.send_message.call_args[0][0]

    @pytest.mark.asyncio
    @patch("bot.commands.config_manager")
    async def test_clear_confirm_callback(self, mock_config_manager):
        """クリア確認ボタンのコールバックテスト"""
        mock_config = MagicMock()
        mock_config.clear_channels.return_value = True
        mock_config_manager.get_config.return_value = mock_config
        
        interaction = MagicMock(spec=discord.Interaction)
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()
        
        view = ClearConfirmView(guild_id=123)
        
        # confirmボタンのコールバックを直接呼ぶ
        # discord.pyの内部構造に依存しないように、callback属性を直接実行
        await view.confirm.callback(interaction)
        
        mock_config.clear_channels.assert_called_once()
        interaction.response.send_message.assert_called_once()
        assert "クリアしました" in interaction.response.send_message.call_args[0][0]

    @pytest.mark.asyncio
    @patch("bot.commands.config_manager")
    async def test_cmd_list_channels_pagination(self, mock_config_manager):
        """チャンネル一覧のページングテスト"""
        mock_config = MagicMock()
        # 15個のチャンネルを作成
        channels = [{"id": i, "name": f"Ch{i}"} for i in range(15)]
        mock_config.get_channels.return_value = channels
        mock_config.get_behavior.return_value = "allow"
        mock_config.get_mode_display_name.return_value = "限定モード"
        mock_config.get_list_display_name.return_value = "許可チャンネルリスト"
        mock_config_manager.get_config.return_value = mock_config
        
        bot = MagicMock()
        bot.get_channel.return_value = None # dictの名前を使わせる
        interaction = AsyncMock()
        interaction.guild.id = 123
        
        # 2ページ目を表示
        await cmd_list_channels(bot, interaction, page=2)
        
        interaction.response.send_message.assert_called_once()
        content = interaction.response.send_message.call_args[0][0]
        assert "ページ: 2/2" in content
        assert "Ch10" in content
        assert "Ch14" in content

    @pytest.mark.asyncio
    @patch("bot.commands.config_manager")
    async def test_cmd_remove_channel_not_really_removed(self, mock_config_manager):
        """削除に失敗（リストに残り続けている）場合のテスト"""
        mock_config = MagicMock()
        mock_config.remove_channel.return_value = True
        mock_config.is_channel_in_list.return_value = True  # まだリストにある
        mock_config_manager.get_config.return_value = mock_config
        
        interaction = AsyncMock()
        interaction.guild.id = 123
        interaction.channel.id = 456
        interaction.channel.name = "TestCh"
        
        await cmd_remove_channel(interaction)
        
        interaction.response.send_message.assert_called_once()
        assert "削除に失敗しました" in interaction.response.send_message.call_args[0][0]

    @pytest.mark.asyncio
    @patch("bot.commands.reload_system_prompt")
    async def test_cmd_reload_prompt_success_failure(self, mock_reload):
        """プロンプト再読み込みコマンドのテスト"""
        interaction = AsyncMock()
        
        # 成功ケース
        mock_reload.return_value = True
        await cmd_reload_prompt(interaction)
        args, _ = interaction.followup.send.call_args
        assert "再読み込みしました" in args[0]
        
        # 失敗ケース
        mock_reload.return_value = False
        await cmd_reload_prompt(interaction)
        args, _ = interaction.followup.send.call_args
        assert "失敗しました" in args[0]

    def test_format_channel_info_edge_cases(self):
        """チャンネル情報の整形エッジケーステスト"""
        bot = MagicMock()
        bot.get_channel.return_value = None  # チャンネルが見つからない
        
        # IDのみのケース
        info = _format_channel_info({"id": 123}, bot)
        assert "不明なチャンネル" in info
        assert "123" in info
        
        # 無効なID
        info2 = _format_channel_info({"id": "invalid"}, bot)
        assert "invalid" in info2

    @pytest.mark.asyncio
    async def test_handle_command_error_scenarios(self):
        """コマンドエラーハンドリングのテスト"""
        interaction = AsyncMock()
        
        # 権限不足
        err1 = discord.app_commands.errors.MissingPermissions(["administrator"])
        await handle_command_error(interaction, err1)
        args, kwargs = interaction.response.send_message.call_args
        assert "管理者権限" in args[0]
        assert kwargs["ephemeral"] is True
        
        # 一般エラー
        err2 = Exception("General Error")
        await handle_command_error(interaction, err2)
        args, kwargs = interaction.response.send_message.call_args
        assert "エラーが発生" in args[0]
        assert kwargs["ephemeral"] is True
