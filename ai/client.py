from __future__ import annotations

from typing import Any

from google import genai
from google.genai import types
import google.auth

import config
from log_utils.logger import logger

_client: genai.Client | None = None


def _get_genai_client() -> genai.Client:
    """Google Gen AI SDKのクライアントを取得する"""
    global _client
    
    if _client is not None:
        return _client

    logger.info("Google Gen AIクライアントを初期化しています")
    
    # 認証情報を取得
    credentials, project = google.auth.default()
    if not config.VERTEX_AI_PROJECT_ID:
        config.VERTEX_AI_PROJECT_ID = project or ""

    # 新しいSDKのクライアント作成
    # vertexai=True を指定することで Vertex AI エンドポイントを使用する
    _client = genai.Client(
        vertexai=True,
        project=config.VERTEX_AI_PROJECT_ID,
        location=config.VERTEX_AI_LOCATION,
    )
    
    logger.info(f"Google Gen AIクライアントを初期化しました（プロジェクト: {config.VERTEX_AI_PROJECT_ID}, リージョン: {config.VERTEX_AI_LOCATION}）")
    return _client


def get_model_name() -> str:
    """使用するモデル名を取得する（google/ プレフィックスを調整）"""
    model_name = config.GEMINI_MODEL
    if model_name.startswith("google/"):
        model_name = model_name.replace("google/", "")
    return model_name


def reset_client() -> None:
    """クライアントの状態をリセットする（テスト用）"""
    global _client
    _client = None
