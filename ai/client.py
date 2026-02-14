from __future__ import annotations

from typing import Any

from openai import OpenAI

import config
from log_utils.logger import logger

_client: OpenAI | None = None
_credentials: Any = None


def _create_openai_client() -> OpenAI:
    """OpenAI APIクライアントを作成する"""
    logger.info("OpenAIクライアントを初期化しています")
    return OpenAI(api_key=config.OPENAI_API_KEY)


def _get_vertex_ai_client() -> OpenAI:
    """Vertex AI OpenAI互換クライアントを取得する

    GCEのWorkload Identityを利用して自動認証する。
    トークンの有効期限切れ時は自動的にリフレッシュする。

    Returns:
        OpenAI: Vertex AI OpenAI互換クライアント
    """
    global _client, _credentials

    import google.auth
    from google.auth.transport.requests import Request

    # 認証情報の初期化
    if _credentials is None:
        logger.info("Vertex AI用の認証情報を取得しています")
        scopes = ["https://www.googleapis.com/auth/cloud-platform"]
        _credentials, project = google.auth.default(scopes=scopes)
        # プロジェクトIDが未設定の場合は自動取得した値を使用
        if not config.VERTEX_AI_PROJECT_ID:
            config.VERTEX_AI_PROJECT_ID = project or ""

    # トークンのリフレッシュ
    if not _credentials.valid:
        logger.debug("認証トークンをリフレッシュしています")
        _credentials.refresh(Request())

    location = config.VERTEX_AI_LOCATION
    project_id = config.VERTEX_AI_PROJECT_ID
    base_url = (
        f"https://{location}-aiplatform.googleapis.com/v1beta1"
        f"/projects/{project_id}/locations/{location}/endpoints/openapi"
    )

    if _client is None:
        logger.info(f"Vertex AIクライアントを初期化しています（リージョン: {location}）")
        _client = OpenAI(api_key=_credentials.token, base_url=base_url)
    else:
        # トークンだけ更新（リフレッシュ済み）
        _client.api_key = _credentials.token

    return _client


def get_client() -> OpenAI:
    """AIプロバイダーに応じたOpenAIクライアントを取得する

    AI_PROVIDER環境変数に基づいてOpenAIまたはVertex AIクライアントを返す。
    OpenAIの場合はシングルトン、Vertex AIの場合はトークン自動リフレッシュ付き。

    Returns:
        OpenAI: クライアントインスタンス

    Raises:
        RuntimeError: クライアント初期化時にエラーが発生した場合
    """
    global _client

    try:
        if config.AI_PROVIDER == "vertex_ai":
            return _get_vertex_ai_client()

        # OpenAI（デフォルト）
        if _client is None:
            _client = _create_openai_client()
        return _client
    except Exception as e:
        error_msg = f"AIクライアントの初期化に失敗しました: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise RuntimeError(error_msg) from e


def reset_client() -> None:
    """クライアントの状態をリセットする（テスト用）"""
    global _client, _credentials
    _client = None
    _credentials = None
