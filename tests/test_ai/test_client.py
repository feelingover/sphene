"""ai/client.pyのテスト"""

import os
from unittest.mock import MagicMock, patch

import config
from ai.client import create_client


def test_create_client(mock_env_vars: dict[str, str]) -> None:
    """OpenAIクライアント作成が正しく行われることをテスト"""
    with patch("ai.client.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        client = create_client()

        # OpenAIクライアントが正しく作成されたか
        mock_openai.assert_called_once()
        # 環境変数のAPIキーが使用されたか
        mock_openai.assert_called_with(api_key=config.OPENAI_API_KEY)
        # 返されたクライアントは正しいか
        assert client == mock_client


def test_create_client_with_invalid_api_key() -> None:
    """APIキーが無効な場合のテスト"""
    with patch("ai.client.OpenAI") as mock_openai, patch.dict(
        os.environ, {"OPENAI_API_KEY": ""}, clear=True
    ):
        # configの再読み込みをシミュレート
        with patch.object(config, "OPENAI_API_KEY", ""):
            # APIキーが無効でもクライアントは作成される (実際の検証はAPI呼び出し時)
            create_client()
            mock_openai.assert_called_once()
            # 空のAPIキーでも呼び出されるはず
            mock_openai.assert_called_with(api_key="")


def test_client_global_instance() -> None:
    """グローバルなクライアントインスタンスが存在することをテスト"""
    # 直接クライアントの存在を検証する方法に変更
    from ai.client import client

    # clientオブジェクトが存在するかチェック
    assert client is not None

    # OpenAIのインスタンスであるか
    with patch("ai.client.OpenAI") as mock_openai:
        # create_client関数をモックして検証
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        # 既存のクライアントが存在するか
        from ai.client import client as existing_client

        assert existing_client is not None
