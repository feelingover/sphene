"""/{group} proactive コマンドのテスト"""

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import discord
import pytest
from discord import app_commands

import config
from bot.commands import cmd_proactive, setup_commands
from tests.test_bot.interaction_helpers import attach_response_state
from utils.proactive_registry import ClaimResult, ClaimStatus

CHANNEL_ID = 555


def _interaction(guild: bool = True) -> MagicMock:
    interaction = MagicMock()
    attach_response_state(interaction)
    interaction.guild = MagicMock(id=123) if guild else None
    interaction.channel = MagicMock(id=CHANNEL_ID)
    return interaction


def _sent_text(interaction: MagicMock) -> str:
    """最後に送ったメッセージ本文"""
    return interaction.followup.send.call_args.args[0]


@pytest.fixture
def channel_config() -> Iterator[MagicMock]:
    conf = MagicMock()
    conf.load_failed = False
    conf.add_proactive_channel.return_value = True
    conf.remove_proactive_channel.return_value = True
    conf.is_proactive_channel.return_value = False
    with patch("bot.commands.config_manager") as manager:
        manager.get_config.return_value = conf
        yield conf


@pytest.fixture
def registry() -> Iterator[MagicMock]:
    reg = MagicMock()
    reg.claim.return_value = ClaimResult(ClaimStatus.CLAIMED, config.INSTANCE_NAME)
    reg.release.return_value = True
    with patch("bot.commands.get_proactive_registry", return_value=reg):
        yield reg


class TestProactiveOn:
    """ON にする"""

    @pytest.mark.asyncio
    async def test_claim_then_save(self, channel_config: MagicMock, registry: MagicMock) -> None:
        interaction = _interaction()
        await cmd_proactive(interaction, True)
        registry.claim.assert_called_once_with(CHANNEL_ID, config.INSTANCE_NAME)
        channel_config.add_proactive_channel.assert_called_once_with(CHANNEL_ID)
        registry.release.assert_not_called()
        assert "ONにしました" in _sent_text(interaction)
        interaction.response.defer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_already_owned_succeeds(
        self, channel_config: MagicMock, registry: MagicMock
    ) -> None:
        registry.claim.return_value = ClaimResult(ClaimStatus.ALREADY_OWNED, config.INSTANCE_NAME)
        interaction = _interaction()
        await cmd_proactive(interaction, True)
        channel_config.add_proactive_channel.assert_called_once_with(CHANNEL_ID)
        assert "ONにしました" in _sent_text(interaction)

    @pytest.mark.asyncio
    async def test_rejected_when_owned_by_other(
        self, channel_config: MagicMock, registry: MagicMock
    ) -> None:
        registry.claim.return_value = ClaimResult(ClaimStatus.OWNED_BY_OTHER, "other-bot")
        interaction = _interaction()
        await cmd_proactive(interaction, True)
        channel_config.add_proactive_channel.assert_not_called()
        assert "「other-bot」が担当" in _sent_text(interaction)

    @pytest.mark.asyncio
    async def test_save_failure_releases_new_claim(
        self, channel_config: MagicMock, registry: MagicMock
    ) -> None:
        channel_config.add_proactive_channel.return_value = False
        interaction = _interaction()
        await cmd_proactive(interaction, True)
        registry.release.assert_called_once_with(CHANNEL_ID, config.INSTANCE_NAME)
        assert "変更できませんでした" in _sent_text(interaction)

    @pytest.mark.asyncio
    async def test_save_failure_keeps_existing_claim(
        self, channel_config: MagicMock, registry: MagicMock
    ) -> None:
        """もともと自分が担当していた登録は巻き戻しで消さない"""
        registry.claim.return_value = ClaimResult(ClaimStatus.ALREADY_OWNED, config.INSTANCE_NAME)
        channel_config.add_proactive_channel.return_value = False
        interaction = _interaction()
        await cmd_proactive(interaction, True)
        registry.release.assert_not_called()
        assert "変更できませんでした" in _sent_text(interaction)

    @pytest.mark.asyncio
    async def test_rollback_failure_is_logged(
        self, channel_config: MagicMock, registry: MagicMock
    ) -> None:
        channel_config.add_proactive_channel.return_value = False
        registry.release.side_effect = RuntimeError("down")
        interaction = _interaction()
        with patch("bot.commands.logger") as logger:
            await cmd_proactive(interaction, True)
        assert logger.error.call_args.kwargs["exc_info"] is True
        assert "変更できませんでした" in _sent_text(interaction)

    @pytest.mark.asyncio
    async def test_registry_error_returns_generic_message(
        self, channel_config: MagicMock, registry: MagicMock
    ) -> None:
        registry.claim.side_effect = RuntimeError("secret internal detail")
        interaction = _interaction()
        with patch("bot.commands.logger") as logger:
            await cmd_proactive(interaction, True)
        channel_config.add_proactive_channel.assert_not_called()
        text = _sent_text(interaction)
        assert "変更できませんでした" in text
        assert "secret" not in text
        assert logger.error.call_args.kwargs["exc_info"] is True


class TestProactiveOff:
    """OFF にする"""

    @pytest.mark.asyncio
    async def test_remove_then_release(
        self, channel_config: MagicMock, registry: MagicMock
    ) -> None:
        interaction = _interaction()
        await cmd_proactive(interaction, False)
        channel_config.remove_proactive_channel.assert_called_once_with(CHANNEL_ID)
        registry.release.assert_called_once_with(CHANNEL_ID, config.INSTANCE_NAME)
        assert "OFFにしました" in _sent_text(interaction)

    @pytest.mark.asyncio
    async def test_not_owner_still_succeeds(
        self, channel_config: MagicMock, registry: MagicMock
    ) -> None:
        """別インスタンスが担当中なら release は何もしない（False）が、OFF は成功する"""
        registry.release.return_value = False
        interaction = _interaction()
        await cmd_proactive(interaction, False)
        assert "OFFにしました" in _sent_text(interaction)

    @pytest.mark.asyncio
    async def test_save_failure_does_not_release(
        self, channel_config: MagicMock, registry: MagicMock
    ) -> None:
        channel_config.remove_proactive_channel.return_value = False
        interaction = _interaction()
        await cmd_proactive(interaction, False)
        registry.release.assert_not_called()
        assert "変更できませんでした" in _sent_text(interaction)

    @pytest.mark.asyncio
    async def test_release_error_asks_retry(
        self, channel_config: MagicMock, registry: MagicMock
    ) -> None:
        registry.release.side_effect = RuntimeError("secret internal detail")
        interaction = _interaction()
        await cmd_proactive(interaction, False)
        text = _sent_text(interaction)
        assert "担当の解除に失敗" in text
        assert "secret" not in text


class TestProactiveStatusAndGuards:
    """状態表示と前提条件"""

    @pytest.mark.asyncio
    async def test_status_shows_owner(
        self, channel_config: MagicMock, registry: MagicMock
    ) -> None:
        channel_config.is_proactive_channel.return_value = True
        registry.get_owner.return_value = "test-bot"
        interaction = _interaction()
        await cmd_proactive(interaction, None)
        text = _sent_text(interaction)
        assert "「ON」" in text
        assert "test-bot" in text
        registry.claim.assert_not_called()
        registry.release.assert_not_called()

    @pytest.mark.asyncio
    async def test_status_when_registry_unavailable(
        self, channel_config: MagicMock, registry: MagicMock
    ) -> None:
        registry.get_owner.side_effect = RuntimeError("down")
        interaction = _interaction()
        await cmd_proactive(interaction, None)
        text = _sent_text(interaction)
        assert "「OFF」" in text
        assert "取得できませんでした" in text

    @pytest.mark.asyncio
    async def test_status_without_owner(
        self, channel_config: MagicMock, registry: MagicMock
    ) -> None:
        registry.get_owner.return_value = None
        interaction = _interaction()
        await cmd_proactive(interaction, None)
        assert "担当: なし" in _sent_text(interaction)

    @pytest.mark.asyncio
    async def test_outside_guild(self, registry: MagicMock) -> None:
        interaction = _interaction(guild=False)
        await cmd_proactive(interaction, True)
        registry.claim.assert_not_called()
        interaction.response.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_channel(self, registry: MagicMock) -> None:
        interaction = _interaction()
        interaction.channel = None
        await cmd_proactive(interaction, True)
        registry.claim.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("enabled", [True, False, None])
    async def test_rejected_in_thread(
        self, channel_config: MagicMock, registry: MagicMock, enabled: bool | None
    ) -> None:
        """スレッドでは ON・OFF・状態表示のどれも行わない"""
        interaction = _interaction()
        interaction.channel = MagicMock(spec=discord.Thread, id=CHANNEL_ID)
        with patch("bot.commands.config_manager") as manager:
            await cmd_proactive(interaction, enabled)
        manager.get_config.assert_not_called()
        registry.claim.assert_not_called()
        registry.release.assert_not_called()
        registry.get_owner.assert_not_called()
        channel_config.add_proactive_channel.assert_not_called()
        channel_config.remove_proactive_channel.assert_not_called()
        text = interaction.response.send_message.call_args.args[0]
        assert "スレッドでは使えません" in text

    @pytest.mark.asyncio
    async def test_load_failed_config(
        self, channel_config: MagicMock, registry: MagicMock
    ) -> None:
        channel_config.load_failed = True
        interaction = _interaction()
        await cmd_proactive(interaction, True)
        registry.claim.assert_not_called()
        assert "読み込めなかった" in _sent_text(interaction)


def test_proactive_command_requires_administrator() -> None:
    """proactive コマンドは管理者権限のチェック付きで登録される"""
    group = setup_commands(MagicMock())
    command = next(c for c in group.commands if c.name == "proactive")
    assert isinstance(command, app_commands.Command)
    assert len(command.checks) == 1

    member = MagicMock()
    member.guild_permissions.administrator = False
    interaction = MagicMock(user=member, permissions=member.guild_permissions)
    with pytest.raises(app_commands.MissingPermissions):
        command.checks[0](interaction)

    interaction.permissions.administrator = True
    assert command.checks[0](interaction) is True

    param = command.parameters[0]
    assert param.name == "enabled"
    assert param.required is False
