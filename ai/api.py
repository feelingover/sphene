"""GenAI API レイヤー: リトライ付きAPI呼び出し、ツール実行、エラーハンドリング"""

import json
import logging
from typing import Any, TYPE_CHECKING

from google.genai import types, errors as genai_errors
from google.api_core import exceptions as google_exceptions
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception,
    before_sleep_log,
)

from ai.client import _get_genai_client, get_model_name
from ai.tools import get_tools, TOOL_FUNCTIONS
from config import GEMINI_MODEL, MAX_TOOL_CALL_ROUNDS
from log_utils.logger import logger
from utils.text_utils import truncate_text

if TYPE_CHECKING:
    from ai.router import ToolMode


def _should_retry_api_error(exception: BaseException) -> bool:
    """リトライすべきエラーかどうかを判定する"""
    if isinstance(exception, genai_errors.APIError):
        # 429: Too Many Requests, 500: Internal Server Error, 503: Service Unavailable, 504: Gateway Timeout
        return exception.code in (429, 500, 503, 504)

    # google.api_core.exceptions も念のためハンドル
    if isinstance(
        exception,
        (
            google_exceptions.TooManyRequests,
            google_exceptions.ResourceExhausted,
            google_exceptions.ServiceUnavailable,
            google_exceptions.InternalServerError,
            google_exceptions.DeadlineExceeded,
        ),
    ):
        return True

    # エラーメッセージに 429 が含まれている場合もリトライを検討（SDKがラップしていないケース用）
    error_str = str(exception)
    if "429" in error_str or "503" in error_str or "500" in error_str:
        return True

    return False


@retry(
    reraise=True,
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    retry=retry_if_exception(_should_retry_api_error),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def generate_content_with_retry(
    client: Any,
    model: str,
    contents: list[types.Content],
    config: types.GenerateContentConfig,
) -> Any:
    """Vertex AI API呼び出しをリトライ付きで実行する"""
    return client.models.generate_content(
        model=model,
        contents=contents,
        config=config,
    )


def _execute_tool_calls(tool_calls: list[types.FunctionCall]) -> list[types.Part]:
    """共通のツール実行ロジック"""
    results: list[types.Part] = []
    for call in tool_calls:
        function_name = call.name
        if function_name is None:
            logger.warning("名前のないツール呼び出しをスキップ")
            continue
        logger.info(f"ツール呼び出し: {function_name}")
        func = TOOL_FUNCTIONS.get(function_name)
        result_content: dict[str, object] | str
        if func is None:
            result_content = {"error": f"未知の関数: {function_name}"}
        else:
            try:
                arguments = call.args or {}
                result_content = func(**arguments)
            except Exception as e:
                logger.error(f"ツール実行エラー: {function_name}: {e}", exc_info=True)
                result_content = {"error": "ツールの実行中にエラーが発生しました"}

        if isinstance(result_content, str):
            try:
                result_dict = json.loads(result_content)
            except (ValueError, json.JSONDecodeError):
                result_dict = {"content": result_content}
        else:
            result_dict = result_content

        results.append(
            types.Part.from_function_response(
                name=function_name,
                response=result_dict,
            )
        )
    return results


def _handle_api_error(error: Exception) -> str:
    if (isinstance(error, genai_errors.APIError) and error.code == 404) or isinstance(
        error, google_exceptions.NotFound
    ):
        return f"ごめんね、指定されたAIモデル「{GEMINI_MODEL}」が見つからないか、このリージョンでは使えないみたい…😢"
    if (isinstance(error, genai_errors.APIError) and error.code == 429) or isinstance(
        error, (google_exceptions.TooManyRequests, google_exceptions.ResourceExhausted)
    ):
        return "ごめんね、今ちょっとAIが混み合ってるみたい…💦 少し時間を置いてからもう一度話しかけてみてね！"
    logger.error(f"APIエラー: {error}", exc_info=True)
    return "ごめん！AIとの通信中にエラーが発生しちゃった...😢"


def call_genai_with_tools(
    contents: list[types.Content],
    system_instruction: str,
    tool_mode: "ToolMode" = "function_calling",
) -> tuple[bool, str, list[types.Content]]:
    """ツール呼び出しループを含むGenAI呼び出し (共通ロジック)

    Args:
        contents: 会話履歴
        system_instruction: システムプロンプト
        tool_mode: Router LLMが判定したツールモード。
            "grounding" → Google Search grounding、
            "function_calling" → XIVAPI等のFunction Calling、
            "none" → ツールなし
    """
    client = _get_genai_client()
    model_id = get_model_name()

    # tool_modeに応じてツールを動的選択
    # Vertex AIの制約: google_search(grounding)とfunction_declarationsは同一リクエストに混在不可
    tools: list[types.Tool]
    if tool_mode == "grounding":
        tools = [types.Tool(google_search=types.GoogleSearch())]
        logger.debug("グラウンディングモード: function callingは無効 (Vertex AI制約)")
    elif tool_mode == "function_calling":
        tools = get_tools()
    else:
        tools = []
        logger.debug("ツールなしモード")

    # contentsリストをコピーして操作する
    local_history = list(contents)

    for round_num in range(MAX_TOOL_CALL_ROUNDS + 1):
        logger.info(f"GenAIリクエスト送信 (ラウンド {round_num + 1}, モデル: {model_id})")

        try:
            response = generate_content_with_retry(
                client=client,
                model=model_id,
                contents=local_history,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    tools=tools,  # type: ignore[arg-type]
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(
                        disable=True
                    ),  # 手動ループ
                ),
            )
        except Exception as e:
            return False, _handle_api_error(e), local_history

        if not response.candidates:
            return False, "AIからの応答が空だったよ…🤔", local_history

        candidate = response.candidates[0]
        resp_content = candidate.content

        # Grounding情報のログ出力
        if hasattr(candidate, "grounding_metadata") and candidate.grounding_metadata:
            logger.info(f"Groundingメタデータを検出: {candidate.grounding_metadata}")

        if resp_content is None or resp_content.parts is None:
            return False, "応答を読み取れなかったよ…😢", local_history

        local_history.append(resp_content)

        # ツール呼び出しがあるか確認 (grounding時はfunction callsは来ない)
        function_calls = [p.function_call for p in resp_content.parts if p.function_call]

        if function_calls:
            logger.info(f"ツール呼び出し検出: {len(function_calls)}件")
            tool_results = _execute_tool_calls(function_calls)
            local_history.append(types.Content(role="user", parts=tool_results))
            continue

        # テキスト応答を抽出
        text_parts = [p.text for p in resp_content.parts if p.text]
        if text_parts:
            final_text = "".join(text_parts)
            logger.debug(f"GenAI応答受信: {truncate_text(final_text)}")
            return True, final_text, local_history

        return False, "応答を読み取れなかったよ…😢", local_history

    # ループ上限到達: ツールなしで最終応答を取得（集めた情報を活かす）
    logger.info("ツール呼び出しラウンド上限到達 - ツールなしで最終応答を取得")
    try:
        response = generate_content_with_retry(
            client=client,
            model=model_id,
            contents=local_history,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
            ),
        )
    except Exception as e:
        return False, _handle_api_error(e), local_history

    if response.candidates:
        candidate = response.candidates[0]
        resp_content = candidate.content
        if resp_content and resp_content.parts:
            local_history.append(resp_content)
            text_parts = [p.text for p in resp_content.parts if p.text]
            if text_parts:
                final_text = "".join(text_parts)
                logger.debug(f"最終応答受信: {truncate_text(final_text)}")
                return True, final_text, local_history

    return False, "処理が複雑すぎて諦めちゃった…😢", local_history
