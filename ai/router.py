"""Router LLM: ユーザーの意図を判定し、適切なツールモードを動的に選択する (issue #94)"""

import json
from html import escape
from typing import Literal, cast

from google.genai import types

import config
from ai.client import _get_genai_client, get_lite_model_name
from ai.api import generate_content_with_retry as _generate_content_with_retry
from log_utils.logger import logger

ToolMode = Literal["grounding", "function_calling", "none"]

# プリフィルタ: この文字数以下のメッセージはRouterを呼ばずに"none"を返す
_PREFILT_MAX_CHARS = 7

_ROUTER_PROMPT = """\
あなたはDiscordボットのルーティングAIです。
ユーザーのメッセージを読んで、ボットが応答するために必要なツールの種類を判定してください。

ツールモードの種類:
- "grounding": 時事ニュース・天気・最新情報・一般的なWeb検索など、外部のリアルタイム情報が必要なケース
- "function_calling": FF14のアイテム名・製作レシピ・ステータス・マーケット情報など、特定のツール実行（XIVAPI等）が必要なケース
- "none": ツール不要。雑談・挨拶・これまでの文脈だけで完結する応答

JSONで回答してください: {"tool_mode": "grounding"|"function_calling"|"none", "reason": "判定理由"}
"""


def detect_tool_mode(message: str, context: str | None = None) -> ToolMode:
    """ユーザーメッセージからツールモードを判定する。

    Args:
        message: ユーザーの入力メッセージ
        context: チャンネルの直近会話コンテキスト（オプション）

    Returns:
        判定されたToolMode。エラー時は"function_calling"にフォールバック。
    """
    # プリフィルタ: 短すぎるメッセージはRouterを呼ばずに即返却
    if len(message.strip()) <= _PREFILT_MAX_CHARS:
        logger.debug(f"Router: プリフィルタ適用 (len={len(message.strip())}) → none")
        return "none"

    if not config.ROUTER_ENABLED:
        logger.debug("Router: 無効 → function_calling")
        return "function_calling"

    try:
        return _call_router_llm(message, context)
    except Exception as e:
        logger.error(f"Router LLM呼び出しエラー: {e}", exc_info=True)
        return "function_calling"


def _call_router_llm(message: str, context: str | None) -> ToolMode:
    """Router LLMを同期的に呼び出す。"""
    client = _get_genai_client()
    model_name = get_lite_model_name()

    prompt_parts = [_ROUTER_PROMPT]
    if context:
        safe_context = f"<context>{escape(context)}</context>"
        prompt_parts.append(f"\n\n--- チャンネルの直近の会話 ---\n{safe_context}\n---")
    safe_message = f"<message>{escape(message)}</message>"
    prompt_parts.append(f"\n\nユーザーのメッセージ:\n{safe_message}")
    prompt = "".join(prompt_parts)

    logger.debug(f"Router LLM呼び出し: model={model_name}")

    response = _generate_content_with_retry(
        client=client,
        model=model_name,
        contents=[types.Content(role="user", parts=[types.Part.from_text(text=prompt)])],
        config=types.GenerateContentConfig(
            temperature=0.0,
            response_mime_type="application/json",
        ),
    )

    content = response.text
    if not content:
        logger.warning("Router LLM: 空レスポンス → function_calling")
        return "function_calling"

    result = json.loads(content)
    if isinstance(result, list):
        result = result[0] if result else {}

    raw_mode = result.get("tool_mode", "")
    reason = result.get("reason", "")

    valid_modes: set[ToolMode] = {"grounding", "function_calling", "none"}
    if raw_mode not in valid_modes:
        logger.warning(f"Router LLM: 不正なtool_mode={raw_mode!r} → function_calling")
        return "function_calling"

    tool_mode = cast(ToolMode, raw_mode)
    logger.info(f"Router判定: tool_mode={tool_mode}, reason={reason}")
    return tool_mode
