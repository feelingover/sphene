"""pytestの共通設定と共通fixturesの定義"""

from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from discord import Client, Interaction
from pytest import MonkeyPatch


@pytest.fixture()
def mock_env_vars(monkeypatch: MonkeyPatch) -> dict[str, str]:
    """テスト用環境変数のモック化"""
    env_vars = {
        "OPENAI_API_KEY": "test-api-key",
        "DISCORD_TOKEN": "test-discord-token",
        "BOT_NAME": "テストボット",
        "COMMAND_GROUP_NAME": "test",
        "DENIED_CHANNEL_IDS": "123456789,987654321",  # 禁止リストとして扱うチャンネルID
        "LOG_LEVEL": "DEBUG",  # テスト時はDEBUGレベルで詳細に確認
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


@pytest.fixture(autouse=True)
def mock_load_system_prompt() -> Generator[MagicMock, None, None]:
    """ai.conversation.load_system_promptを自動でモックする"""
    with patch("ai.conversation.load_system_prompt") as mock_load:
        mock_load.return_value = "テスト用のシステムプロンプト from fixture"
        yield mock_load  # テスト関数内でモックを使いたい場合のためにyieldする


@pytest.fixture()
def mock_logger() -> Generator[MagicMock, None, None]:
    """ロガーのモックと初期化テスト用fixture"""
    with patch("log_utils.logger.setup_logger") as mock_setup:
        mock_logger = MagicMock()
        mock_setup.return_value = mock_logger
        yield mock_logger


@pytest.fixture()
def mock_requests_head() -> Generator[MagicMock, None, None]:
    """requests.headのモック"""
    with patch("requests.head") as mock_head:
        response = MagicMock()
        response.status_code = 200  # デフォルトで成功を返す
        mock_head.return_value = response
        yield mock_head


@pytest.fixture()
def mock_requests_get() -> Generator[MagicMock, None, None]:
    """requests.getのモック"""
    with patch("requests.get") as mock_get:
        response = MagicMock()
        response.status_code = 200
        response.content = b"test_image_data"  # テスト用画像データ
        response.headers = {"Content-Type": "image/jpeg"}  # デフォルトでJPEG
        mock_get.return_value = response
        yield mock_get


@pytest.fixture()
def mock_base64_encode() -> Generator[MagicMock, None, None]:
    """base64.b64encodeのモック"""
    with patch("base64.b64encode") as mock_encode:
        mock_encode.return_value = b"encoded_image_data"
        yield mock_encode
