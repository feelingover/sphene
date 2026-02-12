from google.cloud.firestore import Client as FirestoreClient

from log_utils.logger import logger

_firestore_client: FirestoreClient | None = None


def get_firestore_client() -> FirestoreClient:
    """シングルトンなFirestoreクライアントインスタンスを取得する

    Returns:
        FirestoreClient: Firestoreクライアントインスタンス
    """
    global _firestore_client
    if _firestore_client is None:
        logger.info("Firestoreクライアントを初期化しています")
        try:
            _firestore_client = FirestoreClient()
            logger.info("Firestoreクライアントの初期化に成功")
        except Exception as e:
            logger.critical(
                f"Firestoreクライアントの初期化に失敗: {str(e)}", exc_info=True
            )
            raise RuntimeError(
                f"Failed to initialize Firestore client: {str(e)}"
            ) from e
    return _firestore_client
