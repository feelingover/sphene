"""ai/client.pyのテスト"""

from unittest.mock import MagicMock, patch

import pytest

import config
from ai.client import get_client, reset_client


@pytest.fixture(autouse=True)
def _reset_client_state() -> None:
    """各テスト前にクライアントの状態をリセット"""
    reset_client()


class TestOpenAIProvider:
    """AI_PROVIDER=openai のテスト"""

    def test_get_client_creates_openai_client(
        self, mock_env_vars: dict[str, str]
    ) -> None:
        """OpenAIクライアントが正しく作成されることをテスト"""
        with patch("ai.client.OpenAI") as mock_openai, patch.object(
            config, "AI_PROVIDER", "openai"
        ):
            mock_client = MagicMock()
            mock_openai.return_value = mock_client

            client = get_client()

            mock_openai.assert_called_once_with(api_key=config.OPENAI_API_KEY)
            assert client == mock_client

    def test_get_client_returns_singleton(
        self, mock_env_vars: dict[str, str]
    ) -> None:
        """同じインスタンスが返されることをテスト（シングルトン）"""
        with patch("ai.client.OpenAI") as mock_openai, patch.object(
            config, "AI_PROVIDER", "openai"
        ):
            mock_client = MagicMock()
            mock_openai.return_value = mock_client

            client1 = get_client()
            client2 = get_client()

            mock_openai.assert_called_once()
            assert client1 is client2

    def test_get_client_with_empty_api_key(self) -> None:
        """APIキーが空でもクライアントが作成されることをテスト"""
        with patch("ai.client.OpenAI") as mock_openai, patch.object(
            config, "AI_PROVIDER", "openai"
        ), patch.object(config, "OPENAI_API_KEY", ""):
            get_client()
            mock_openai.assert_called_once_with(api_key="")

    def test_get_client_with_api_error(self) -> None:
        """クライアント作成時にエラーが発生した場合のテスト"""
        with patch("ai.client.OpenAI") as mock_openai, patch.object(
            config, "AI_PROVIDER", "openai"
        ), patch("ai.client.logger"):
            mock_openai.side_effect = Exception("API初期化エラー")

            with pytest.raises(RuntimeError):
                get_client()


class TestVertexAIProvider:
    """AI_PROVIDER=vertex_ai のテスト"""

    def test_get_client_creates_vertex_ai_client(self) -> None:
        """Vertex AIクライアントが正しく作成されることをテスト"""
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.token = "test-access-token"

        with patch("ai.client.OpenAI") as mock_openai, patch.object(
            config, "AI_PROVIDER", "vertex_ai"
        ), patch.object(config, "VERTEX_AI_PROJECT_ID", "my-project"), patch.object(
            config, "VERTEX_AI_LOCATION", "asia-northeast1"
        ), patch(
            "google.auth.default", return_value=(mock_creds, "my-project")
        ):
            mock_client = MagicMock()
            mock_openai.return_value = mock_client

            client = get_client()

            mock_openai.assert_called_once_with(
                api_key="test-access-token",
                base_url=(
                    "https://asia-northeast1-aiplatform.googleapis.com/v1beta1"
                    "/projects/my-project/locations/asia-northeast1/endpoints/openapi"
                ),
            )
            assert client == mock_client

    def test_get_client_refreshes_expired_token(self) -> None:
        """トークン期限切れ時にリフレッシュされることをテスト"""
        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.token = "refreshed-token"

        mock_request_class = MagicMock()

        with patch("ai.client.OpenAI") as mock_openai, patch.object(
            config, "AI_PROVIDER", "vertex_ai"
        ), patch.object(config, "VERTEX_AI_PROJECT_ID", "my-project"), patch.object(
            config, "VERTEX_AI_LOCATION", "asia-northeast1"
        ), patch(
            "google.auth.default", return_value=(mock_creds, "my-project")
        ), patch(
            "google.auth.transport.requests.Request",
            return_value=mock_request_class,
        ):
            mock_openai.return_value = MagicMock()

            get_client()

            mock_creds.refresh.assert_called_once_with(mock_request_class)

    def test_get_client_auto_detects_project_id(self) -> None:
        """VERTEX_AI_PROJECT_IDが未設定の場合にgoogle.authから自動取得するテスト"""
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.token = "test-token"

        with patch("ai.client.OpenAI"), patch.object(
            config, "AI_PROVIDER", "vertex_ai"
        ), patch.object(config, "VERTEX_AI_PROJECT_ID", ""), patch.object(
            config, "VERTEX_AI_LOCATION", "asia-northeast1"
        ), patch(
            "google.auth.default", return_value=(mock_creds, "auto-detected-project")
        ):
            get_client()

            assert config.VERTEX_AI_PROJECT_ID == "auto-detected-project"

    def test_get_client_updates_token_on_subsequent_calls(self) -> None:
        """2回目以降の呼び出しでトークンのみ更新されることをテスト"""
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.token = "initial-token"

        with patch("ai.client.OpenAI") as mock_openai, patch.object(
            config, "AI_PROVIDER", "vertex_ai"
        ), patch.object(config, "VERTEX_AI_PROJECT_ID", "my-project"), patch.object(
            config, "VERTEX_AI_LOCATION", "asia-northeast1"
        ), patch(
            "google.auth.default", return_value=(mock_creds, "my-project")
        ):
            mock_client = MagicMock()
            mock_openai.return_value = mock_client

            # 1回目の呼び出し
            get_client()
            mock_openai.assert_called_once()

            # 2回目の呼び出し（新しいトークン）
            mock_creds.token = "updated-token"
            client2 = get_client()

            # OpenAIコンストラクタは1回だけ呼ばれる（シングルトン）
            mock_openai.assert_called_once()
            # api_keyが更新されている
            assert client2.api_key == "updated-token"


class TestResetClient:
    """reset_client()のテスト"""

    def test_reset_clears_state(self) -> None:
        """リセット後に新しいクライアントが作成されることをテスト"""
        with patch("ai.client.OpenAI") as mock_openai, patch.object(
            config, "AI_PROVIDER", "openai"
        ):
            mock_client1 = MagicMock()
            mock_client2 = MagicMock()
            mock_openai.side_effect = [mock_client1, mock_client2]

            client1 = get_client()
            reset_client()
            client2 = get_client()

            assert mock_openai.call_count == 2
            assert client1 is not client2
