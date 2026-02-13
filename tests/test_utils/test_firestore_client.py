"""
Firestoreクライアント（firestore_client）のテスト
"""

# type: ignore
# mypy: ignore-errors

from unittest.mock import MagicMock, patch

from utils.firestore_client import get_firestore_client


class TestFirestoreClient:
    """Firestoreクライアントのテスト"""

    @patch("utils.firestore_client._firestore_client", None)
    @patch("utils.firestore_client.FirestoreClient")
    def test_get_firestore_client_singleton(self, mock_firestore_class):
        """シングルトンパターンで同一インスタンスが返されることを確認"""
        mock_instance = MagicMock()
        mock_firestore_class.return_value = mock_instance

        client1 = get_firestore_client()
        client2 = get_firestore_client()

        assert client1 is client2
        # FirestoreClientのコンストラクタは1回だけ呼ばれる
        mock_firestore_class.assert_called_once()

    @patch("utils.firestore_client._firestore_client", None)
    @patch("utils.firestore_client.FirestoreClient")
    def test_get_firestore_client_initialization_error(self, mock_firestore_class):
        """初期化失敗時にRuntimeErrorが発生することを確認"""
        mock_firestore_class.side_effect = Exception("接続エラー")

        try:
            get_firestore_client()
            assert False, "RuntimeError should have been raised"
        except RuntimeError as e:
            assert "Failed to initialize Firestore client" in str(e)
