"""pytestの共通設定と共通fixturesの定義"""

from typing import Dict
from unittest.mock import AsyncMock, MagicMock

import pytest
from discord import Client, Interaction
from pytest import MonkeyPatch


@pytest.fixture()
def mock_env_vars(monkeypatch: MonkeyPatch) -> Dict[str, str]:
    """テスト用環境変数のモック化"""
    env_vars = {
        "OPENAI_API_KEY": "test-api-key",
        "DISCORD_TOKEN": "test-discord-token",
        "BOT_NAME": "テストボット",
        "COMMAND_GROUP_NAME": "test",
        "DENIED_CHANNEL_IDS": "123456789,987654321",  # 禁止リストとして扱うチャンネルID
    }
    for key, value in env_vars.items():
        monkeypatch.setenv(key, value)
    return env_vars


@pytest.fixture()
def mock_discord_client() -> MagicMock:
    """Discordクライアントのモック"""
    client = MagicMock(spec=Client)
    # チャンネル取得のモック
    mock_channel = MagicMock()
    mock_channel.name = "テストチャンネル"
    client.get_channel.return_value = mock_channel
    return client


@pytest.fixture()
def mock_discord_interaction() -> MagicMock:
    """Discordインタラクションのモック"""
    interaction = MagicMock(spec=Interaction)
    # レスポンスメソッドを非同期モックに
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.user.id = 12345
    return interaction


@pytest.fixture()
def mock_openai_response() -> MagicMock:
    """OpenAI APIレスポンスのモック"""
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "これはテスト応答です。"
    mock_response.choices = [mock_choice]
    return mock_response
