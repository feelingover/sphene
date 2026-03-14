from __future__ import annotations

import threading
from typing import Any

from google import genai
from google.genai import types
import google.auth

import config
from log_utils.logger import logger

_client: genai.Client | None = None
_client_lock = threading.Lock()


def _get_genai_client() -> genai.Client:
    """Google Gen AI SDKのクライアントを取得する"""
    global _client

    if _client is not None:
        return _client

    with _client_lock:
        # ロック取得後に再チェック（double-checked locking）
        if _client is not None:
            return _client

        logger.info("Google Gen AIクライアントを初期化しています")

        # 認証情報を取得
        credentials, project = google.auth.default()
        project_id = config.VERTEX_AI_PROJECT_ID or (project or "")

        # 新しいSDKのクライアント作成
        # vertexai=True を指定することで Vertex AI エンドポイントを使用する
        _client = genai.Client(
            vertexai=True,
            project=project_id,
            location=config.VERTEX_AI_LOCATION,
        )

        logger.info(
            "Google Gen AIクライアントを初期化しました（プロジェクト: "
            f"{project_id}, リージョン: {config.VERTEX_AI_LOCATION}）"
        )
    return _client


def get_model_name() -> str:
    """使用するモデル名を取得する（google/ プレフィックスを調整）"""
    model_name = config.BOT_MODEL
    if model_name.startswith("google/"):
        model_name = model_name.replace("google/", "")
    return model_name


def get_lite_model_name() -> str:
    """軽量モデル名を取得する（google/ プレフィックスを調整）"""
    model_name = config.BOT_LITE_MODEL
    if model_name.startswith("google/"):
        model_name = model_name.replace("google/", "")
    return model_name


def get_genai_client() -> genai.Client:
    """Google Gen AI SDK クライアントのパブリックアクセサ"""
    return _get_genai_client()


def generate_embedding(text: str) -> list[float] | None:
    """テキストからEmbeddingベクトルを生成する。

    Args:
        text: 埋め込みを生成するテキスト

    Returns:
        Embeddingベクトル。エラー時はNone。
    """
    try:
        client = get_genai_client()
        result = client.models.embed_content(
            model=config.EMBEDDING_MODEL,
            contents=text,
        )
        if not result.embeddings:
            return None
        values = result.embeddings[0].values
        if values is None:
            return None
        return list(values)
    except Exception:
        logger.warning("Embedding生成に失敗しました", exc_info=True)
        return None


def reset_client() -> None:
    """クライアントの状態をリセットする（テスト用）"""
    global _client
    _client = None
