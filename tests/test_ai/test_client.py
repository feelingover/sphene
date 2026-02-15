"""ai/client.pyのテスト"""

from unittest.mock import MagicMock, patch

import pytest

import config
from ai.client import _get_genai_client, get_model_name, reset_client


@pytest.fixture(autouse=True)
def _reset_client_state() -> None:
    """各テスト前にクライアントの状態をリセット"""
    reset_client()


class TestGetGenaiClient:
    """_get_genai_client()のテスト"""

    def test_creates_genai_client(self) -> None:
        """Google Gen AIクライアントが正しく作成されることをテスト"""
        mock_creds = MagicMock()

        with patch("ai.client.genai.Client") as mock_client_cls, patch(
            "ai.client.google.auth.default",
            return_value=(mock_creds, "my-project"),
        ), patch.object(config, "VERTEX_AI_PROJECT_ID", "my-project"), patch.object(
            config, "VERTEX_AI_LOCATION", "asia-northeast1"
        ):
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client

            client = _get_genai_client()

            mock_client_cls.assert_called_once_with(
                vertexai=True,
                project="my-project",
                location="asia-northeast1",
            )
            assert client == mock_client

    def test_returns_singleton(self) -> None:
        """同じインスタンスが返されることをテスト（シングルトン）"""
        mock_creds = MagicMock()

        with patch("ai.client.genai.Client") as mock_client_cls, patch(
            "ai.client.google.auth.default",
            return_value=(mock_creds, "my-project"),
        ), patch.object(config, "VERTEX_AI_PROJECT_ID", "my-project"), patch.object(
            config, "VERTEX_AI_LOCATION", "asia-northeast1"
        ):
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client

            client1 = _get_genai_client()
            client2 = _get_genai_client()

            mock_client_cls.assert_called_once()
            assert client1 is client2

    def test_auto_detects_project_id(self) -> None:
        """VERTEX_AI_PROJECT_IDが未設定の場合にgoogle.authから自動取得するテスト"""
        mock_creds = MagicMock()

        with patch("ai.client.genai.Client") as mock_client_cls, patch(
            "ai.client.google.auth.default",
            return_value=(mock_creds, "auto-detected-project"),
        ), patch.object(config, "VERTEX_AI_PROJECT_ID", ""), patch.object(
            config, "VERTEX_AI_LOCATION", "asia-northeast1"
        ):
            mock_client_cls.return_value = MagicMock()

            _get_genai_client()

            mock_client_cls.assert_called_once_with(
                vertexai=True,
                project="auto-detected-project",
                location="asia-northeast1",
            )


class TestGetModelName:
    """get_model_name()のテスト"""

    def test_strips_google_prefix(self) -> None:
        """google/ プレフィックスが除去されることをテスト"""
        with patch.object(config, "GEMINI_MODEL", "google/gemini-2.5-flash"):
            assert get_model_name() == "gemini-2.5-flash"

    def test_keeps_name_without_prefix(self) -> None:
        """プレフィックスなしのモデル名がそのまま返されることをテスト"""
        with patch.object(config, "GEMINI_MODEL", "gemini-2.5-pro"):
            assert get_model_name() == "gemini-2.5-pro"


class TestResetClient:
    """reset_client()のテスト"""

    def test_reset_clears_state(self) -> None:
        """リセット後に新しいクライアントが作成されることをテスト"""
        mock_creds = MagicMock()

        with patch("ai.client.genai.Client") as mock_client_cls, patch(
            "ai.client.google.auth.default",
            return_value=(mock_creds, "my-project"),
        ), patch.object(config, "VERTEX_AI_PROJECT_ID", "my-project"), patch.object(
            config, "VERTEX_AI_LOCATION", "asia-northeast1"
        ):
            mock_client1 = MagicMock()
            mock_client2 = MagicMock()
            mock_client_cls.side_effect = [mock_client1, mock_client2]

            client1 = _get_genai_client()
            reset_client()
            client2 = _get_genai_client()

            assert mock_client_cls.call_count == 2
            assert client1 is not client2
