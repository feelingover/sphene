"""スラッシュコマンド・ビューのコールバックが I/O 前に defer することのテスト"""

from unittest.mock import MagicMock, PropertyMock, patch

import discord
import pytest

from bot.commands import (
    ClearConfirmView,
    ModeSelect,
    ModeView,
    TranslationSelect,
    TranslationView,
    _reply,
    cmd_add_channel,
    cmd_clear_channels,
    cmd_list_channels,
    cmd_mode,
    cmd_remove_channel,
    cmd_translation,
)
from tests.test_bot.interaction_helpers import attach_response_state


def _interaction(admin: bool = True) -> MagicMock:
    interaction = attach_response_state(MagicMock())
    interaction.guild.id = 1
    interaction.channel.id = 10
    interaction.channel.name = "general"
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.guild_permissions.administrator = admin
    return interaction


def _config_manager(interaction: MagicMock, calls: list[str]) -> MagicMock:
    """get_config が呼ばれた時点で defer 済みかを記録する ConfigManager モック"""
    channel_config = MagicMock()
    channel_config.get_channels.return_value = []
    channel_config.is_channel_in_list.return_value = False
    manager = MagicMock()

    def _get_config(guild_id: int) -> MagicMock:
        calls.append("deferred" if interaction.response.is_done() else "not_deferred")
        return channel_config

    manager.get_config.side_effect = _get_config
    return manager


COMMANDS = [
    cmd_mode,
    lambda i: cmd_list_channels(MagicMock(), i),
    cmd_add_channel,
    cmd_remove_channel,
    cmd_clear_channels,
    cmd_translation,
]


class TestCommandsDeferBeforeIo:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("command", COMMANDS)
    async def test_defer_before_get_config(self, command):
        interaction = _interaction()
        calls: list[str] = []
        with patch("bot.commands.config_manager", _config_manager(interaction, calls)):
            await command(interaction)

        assert calls == ["deferred"]
        interaction.response.defer.assert_awaited_once_with(thinking=True)
        interaction.response.send_message.assert_not_called()
        interaction.followup.send.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("command", "view_type"),
        [(cmd_mode, ModeView), (cmd_clear_channels, ClearConfirmView), (cmd_translation, TranslationView)],
    )
    async def test_view_is_sent_with_followup(self, command, view_type):
        interaction = _interaction()
        with patch("bot.commands.config_manager", _config_manager(interaction, [])):
            await command(interaction)

        assert isinstance(interaction.followup.send.call_args.kwargs["view"], view_type)


class TestViewCallbacksDefer:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "make_callback",
        [
            lambda: _select_callback(ModeSelect(1), "allow"),
            lambda: _select_callback(TranslationSelect(1), "true"),
            lambda: ClearConfirmView(1).confirm.callback,
        ],
    )
    async def test_defer_before_get_config(self, make_callback):
        interaction = _interaction()
        calls: list[str] = []
        with patch("bot.commands.config_manager", _config_manager(interaction, calls)):
            await make_callback()(interaction)

        assert calls == ["deferred"]
        interaction.response.defer.assert_awaited_once_with(thinking=True)
        interaction.followup.send.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "make_callback",
        [
            lambda: _select_callback(ModeSelect(1), "allow"),
            lambda: _select_callback(TranslationSelect(1), "true"),
            lambda: ClearConfirmView(1).confirm.callback,
        ],
    )
    async def test_permission_error_is_immediate_and_ephemeral(self, make_callback):
        interaction = _interaction(admin=False)
        manager = MagicMock()
        with patch("bot.commands.config_manager", manager):
            await make_callback()(interaction)

        interaction.response.defer.assert_not_called()
        manager.get_config.assert_not_called()
        assert interaction.response.send_message.call_args.kwargs["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_cancel_does_not_defer(self):
        interaction = _interaction()
        await ClearConfirmView(1).cancel.callback(interaction)
        interaction.response.defer.assert_not_called()
        interaction.response.send_message.assert_awaited_once()


def _select_callback(select, value: str):
    """Select の values (読み取り専用プロパティ) を、呼び出し中だけ差し替えるコールバックを返す"""

    async def _callback(interaction):
        with patch.object(type(select), "values", new_callable=PropertyMock, return_value=[value]):
            await select.callback(interaction)

    return _callback


class TestReply:
    @pytest.mark.asyncio
    async def test_before_response_uses_send_message(self):
        interaction = attach_response_state(MagicMock())
        await _reply(interaction, "hi")
        interaction.response.send_message.assert_awaited_once_with("hi")

    @pytest.mark.asyncio
    async def test_after_defer_uses_followup_without_view_kwarg(self):
        """followup.send に view=None を渡さない（discord.py は MISSING 以外を View として扱う）"""
        interaction = attach_response_state(MagicMock())
        await interaction.response.defer()
        await _reply(interaction, "hi")
        interaction.followup.send.assert_awaited_once_with("hi")

    @pytest.mark.asyncio
    async def test_view_is_passed(self):
        interaction = attach_response_state(MagicMock())
        view = MagicMock()
        await _reply(interaction, "hi", view=view)
        interaction.response.send_message.assert_awaited_once_with("hi", view=view)
