import threading

from google.cloud.firestore import Client as FirestoreClient

from log_utils.logger import logger

_firestore_client: FirestoreClient | None = None
_firestore_client_lock = threading.Lock()


def get_firestore_client() -> FirestoreClient:
    """シングルトンなFirestoreクライアントインスタンスを取得する

    Returns:
        FirestoreClient: Firestoreクライアントインスタンス
    """
    global _firestore_client
    if _firestore_client is None:
        with _firestore_client_lock:
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


# Firestore のドキュメントサイズ上限は 1 MiB。ドキュメント名やインデックス分の余裕を残して判定する
FIRESTORE_MAX_DOCUMENT_BYTES = 1_048_576
FIRESTORE_SAFE_DOCUMENT_BYTES = 1_000_000

# ドキュメント自体のオーバーヘッド (ドキュメント名を除く)
_DOCUMENT_OVERHEAD_BYTES = 32


def estimate_value_size(value: object) -> int:
    """Firestoreの保存サイズ規則に従って値のサイズ（バイト）を見積もる

    数値は8バイト、文字列はUTF-8バイト数+1、配列は要素の合計、
    マップはフィールド名（UTF-8+1）と値の合計で数える。
    JSON文字列長で見積もると浮動小数の配列（embedding）を約2.5倍に過大評価するため使わない。

    Args:
        value: 保存する値

    Returns:
        見積もりサイズ（バイト）
    """
    if value is None or isinstance(value, bool):
        return 1
    if isinstance(value, (int, float)):
        return 8
    if isinstance(value, str):
        return len(value.encode("utf-8")) + 1
    if isinstance(value, (list, tuple)):
        return sum(estimate_value_size(v) for v in value)
    if isinstance(value, dict):
        return sum(
            len(str(k).encode("utf-8")) + 1 + estimate_value_size(v) for k, v in value.items()
        )
    # datetime 等その他の型は8バイトとして扱う
    return 8


def estimate_document_size(data: dict) -> int:
    """Firestoreドキュメント (ドキュメント名を除く) のサイズを見積もる"""
    return estimate_value_size(data) + _DOCUMENT_OVERHEAD_BYTES
