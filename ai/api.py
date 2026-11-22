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

from ai.client import _get_genai_client, get_main_thinking_config, get_model_name
from ai.tools import get_tools, TOOL_FUNCTIONS
from config import BOT_MODEL, MAX_TOOL_CALL_ROUNDS
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
        logger.error(f"AIモデルが見つからないか利用不可: model={BOT_MODEL}", exc_info=True)
        return "ごめんね、AIモデルが見つからないか、このリージョンでは使えないみたい…😢"
    if (isinstance(error, genai_errors.APIError) and error.code == 429) or isinstance(
        error, (google_exceptions.TooManyRequests, google_exceptions.ResourceExhausted)
    ):
        return "ごめんね、今ちょっとAIが混み合ってるみたい…💦 少し時間を置いてからもう一度話しかけてみてね！"
    logger.error(f"APIエラー: {error}", exc_info=True)
    return "ごめん！AIとの通信中にエラーが発生しちゃった...😢"


def _extract_text(content: types.Content | None) -> str | None:
    """Contentからテキスト部分のみを連結して返す (function_call等は無視)"""
    if content is None or not content.parts:
        return None
    text_parts = [p.text for p in content.parts if p.text]
    return "".join(text_parts) if text_parts else None


def _function_response_to_text(part: types.Part) -> types.Part:
    """function_responseのpartを、ツール結果を説明するテキストpartに変換する"""
    fr = part.function_response
    if fr is None:
        return part
    result = json.dumps(fr.response, ensure_ascii=False, default=str)
    return types.Part.from_text(text=f"（ツール {fr.name} の実行結果）\n{result}")


def _flatten_function_parts(contents: list[types.Content]) -> list[types.Content]:
    """履歴のfunction系partをテキスト化・除去した送信用コピーを作る

    ツール未宣言のリクエストで履歴中のfunction_callをモデルが模倣するのを防ぐ。
    function_callは除去し、function_responseは集めた情報を活かせるよう
    テキストpartに変換する。partが空になったContentは丸ごと除外し、
    同じroleが連続した場合は1つのContentにまとめる。

    Args:
        contents: 会話履歴

    Returns:
        function系partを含まない送信用の履歴
    """
    flattened: list[types.Content] = []
    for content in contents:
        parts = [
            _function_response_to_text(p) if p.function_response else p
            for p in (content.parts or [])
            if not p.function_call
        ]
        if not parts:
            continue
        if flattened and flattened[-1].role == content.role:
            prev = flattened[-1]
            flattened[-1] = types.Content(role=prev.role, parts=[*(prev.parts or []), *parts])
        else:
            flattened.append(types.Content(role=content.role, parts=parts))
    return flattened


def _handle_undeclared_function_calls(
    resp_content: types.Content,
    tool_mode: "ToolMode",
    local_history: list[types.Content],
    request: dict[str, Any],
    failure_message: str = "応答を読み取れなかったよ…😢",
    phase: str = "main",
) -> tuple[bool, str, list[types.Content]]:
    """ツール未宣言時に返されたfunction_callを破棄し、テキスト応答を得る

    function_callに添えられたテキストは「調べてみるね」のような前置きであることが
    多いため採用せず、履歴のfunction系partをテキスト化・除去して1回だけ再リクエストする。
    function_callは履歴に追加しない。

    Args:
        resp_content: function_callを含むモデル応答
        tool_mode: 現在のツールモード
        local_history: 会話履歴
        request: 再リクエスト用の client / model / config
        failure_message: 再リクエストでもテキストを得られなかった場合の応答
        phase: ログ用の呼び出し箇所 ("main" | "final_call")

    Returns:
        (成功フラグ, 応答テキスト, 更新後の履歴)
    """
    call_names = [p.function_call.name for p in (resp_content.parts or []) if p.function_call]
    logger.warning(
        f"ツール未宣言のモードでfunction_callを検出したため無視: "
        f"tool_mode={tool_mode}, phase={phase}, calls={call_names}"
    )
    logger.info("function系partをテキスト化した履歴で再リクエスト")
    try:
        response = generate_content_with_retry(
            contents=_flatten_function_parts(local_history), **request
        )
    except Exception as e:
        return False, _handle_api_error(e), local_history
    candidate = response.candidates[0] if response.candidates else None
    retry_content = candidate.content if candidate else None
    if retry_content is not None and any(p.function_call for p in (retry_content.parts or [])):
        # 添えられたテキストは前置きの可能性が高いため、初回と同じく採用しない
        logger.warning("再リクエストでもfunction_callが返されたため応答を破棄")
        return False, failure_message, local_history
    final_text = _extract_text(retry_content)
    if final_text is None:
        logger.warning("再リクエストでもテキスト応答を得られなかった")
        return False, failure_message, local_history

    local_history.append(
        types.Content(role="model", parts=[types.Part.from_text(text=final_text)])
    )
    logger.debug(f"GenAI応答受信: {truncate_text(final_text)}")
    return True, final_text, local_history


def _request_final_answer(
    local_history: list[types.Content],
    request: dict[str, Any],
) -> tuple[bool, str, list[types.Content]]:
    """ツール呼び出しラウンド上限到達後、ツールなしで最終応答を取得する

    履歴中のfunction_callを模倣してfunction_callが返された場合は実行せず、
    function系partをテキスト化して再リクエストする。

    Args:
        local_history: ツール呼び出し結果を含む会話履歴
        request: ツールなしの client / model / config

    Returns:
        (成功フラグ, 応答テキスト, 更新後の履歴)
    """
    give_up_message = "処理が複雑すぎて諦めちゃった…😢"
    logger.info("ツール呼び出しラウンド上限到達 - ツールなしで最終応答を取得")
    try:
        response = generate_content_with_retry(contents=local_history, **request)
    except Exception as e:
        return False, _handle_api_error(e), local_history

    candidate = response.candidates[0] if response.candidates else None
    resp_content = candidate.content if candidate else None
    if resp_content is None or not resp_content.parts:
        return False, give_up_message, local_history

    if any(p.function_call for p in resp_content.parts):
        return _handle_undeclared_function_calls(
            resp_content,
            "function_calling",
            local_history,
            request,
            failure_message=give_up_message,
            phase="final_call",
        )

    final_text = _extract_text(resp_content)
    if final_text is None:
        return False, give_up_message, local_history
    local_history.append(resp_content)
    logger.debug(f"最終応答受信: {truncate_text(final_text)}")
    return True, final_text, local_history


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

    request: dict[str, Any] = {
        "client": client,
        "model": model_id,
        "config": types.GenerateContentConfig(
            system_instruction=system_instruction,
            thinking_config=get_main_thinking_config(),
            tools=tools,  # type: ignore[arg-type]
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),  # 手動ループ
        ),
    }

    # contentsリストをコピーして操作する
    local_history = list(contents)

    for round_num in range(MAX_TOOL_CALL_ROUNDS + 1):
        logger.info(f"GenAIリクエスト送信 (ラウンド {round_num + 1}, モデル: {model_id})")

        # ツール未宣言のモードでは、履歴のfunction_callを模倣されないよう最初からテキスト化して送る
        send_contents = (
            local_history
            if tool_mode == "function_calling"
            else _flatten_function_parts(local_history)
        )
        try:
            response = generate_content_with_retry(contents=send_contents, **request)
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

        function_calls = [p.function_call for p in resp_content.parts if p.function_call]

        if function_calls and tool_mode != "function_calling":
            # ツール未宣言なのにモデルがfunction_callを返した (履歴の模倣など)。実行せず無視する
            return _handle_undeclared_function_calls(
                resp_content, tool_mode, local_history, request
            )

        local_history.append(resp_content)

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
    final_request: dict[str, Any] = {
        **request,
        "config": types.GenerateContentConfig(
            system_instruction=system_instruction,
            thinking_config=get_main_thinking_config(),
        ),
    }
    return _request_final_answer(local_history, final_request)
