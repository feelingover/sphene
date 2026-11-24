"""GenAI API レイヤー: リトライ付きAPI呼び出し、ツール実行、エラーハンドリング"""

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, TYPE_CHECKING

import httpx
from google.genai import types, errors as genai_errors
from google.api_core import exceptions as google_exceptions
from tenacity import (
    RetryCallState,
    Retrying,
    stop_after_attempt,
    stop_any,
    wait_exponential,
    retry_if_exception,
    before_sleep_log,
)
from tenacity.stop import stop_base

import config as _config
from ai.client import _get_genai_client, get_main_thinking_config, get_model_name
from ai.tools import get_tools, TOOL_FUNCTIONS
from config import BOT_MODEL, MAX_TOOL_CALL_ROUNDS, MAX_TOOL_RESULT_CHARS
from log_utils.logger import logger
from utils.text_utils import truncate_text

if TYPE_CHECKING:
    from ai.router import ToolMode


# リトライ対象の HTTP ステータス
# 408: Request Timeout, 429: Too Many Requests, 500: Internal Server Error,
# 502: Bad Gateway, 503: Service Unavailable, 504: Gateway Timeout
_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})

_RETRYABLE_GOOGLE_EXCEPTIONS = (
    google_exceptions.TooManyRequests,
    google_exceptions.ResourceExhausted,
    google_exceptions.ServiceUnavailable,
    google_exceptions.InternalServerError,
    google_exceptions.DeadlineExceeded,
)


def _should_retry_api_error(exception: BaseException) -> bool:
    """リトライすべきエラーかどうかを判定する

    例外の型とステータスコードで判定する。メッセージ文字列の一致には頼らない
    （"500" を含むだけのバリデーションエラー等を誤ってリトライしないため）。

    Args:
        exception: 発生した例外

    Returns:
        リトライすべきなら True
    """
    if isinstance(exception, genai_errors.APIError):
        return exception.code in _RETRYABLE_STATUS_CODES
    if isinstance(exception, _RETRYABLE_GOOGLE_EXCEPTIONS):
        return True
    # タイムアウト・接続断などのネットワークエラー（SDK は httpx を使用）
    if isinstance(exception, (httpx.TransportError, ConnectionError, TimeoutError)):
        return True
    return False


# タイムアウト扱いする HTTP ステータス（408: Request Timeout, 504: Gateway Timeout）
_TIMEOUT_STATUS_CODES = frozenset({408, 504})


@dataclass(frozen=True)
class RetryPolicy:
    """Gen AI API 呼び出しのリトライ設定

    Attributes:
        max_attempts: 最大試行回数（初回を含む）
        timeout_retries: タイムアウト系エラーで再試行する最大回数
        request_timeout_seconds: 1リクエストあたりのタイムアウト秒数
        total_timeout_seconds: リトライ・待機を含む全体の上限秒数
    """

    max_attempts: int
    timeout_retries: int
    request_timeout_seconds: float
    total_timeout_seconds: float

    def new_deadline(self) -> float:
        """現在時刻から全体の上限時刻（time.monotonic 基準）を求める"""
        return time.monotonic() + self.total_timeout_seconds


def main_retry_policy() -> RetryPolicy:
    """会話応答・要約・反省会用のリトライ設定を返す"""
    return RetryPolicy(
        max_attempts=_config.GENAI_MAIN_MAX_ATTEMPTS,
        timeout_retries=_config.GENAI_MAIN_TIMEOUT_RETRIES,
        request_timeout_seconds=_config.GENAI_REQUEST_TIMEOUT_SECONDS,
        total_timeout_seconds=_config.GENAI_MAIN_TOTAL_TIMEOUT_SECONDS,
    )


def light_retry_policy() -> RetryPolicy:
    """Router・LLM Judge・相槌用の短いリトライ設定を返す"""
    return RetryPolicy(
        max_attempts=_config.GENAI_LIGHT_MAX_ATTEMPTS,
        timeout_retries=_config.GENAI_LIGHT_TIMEOUT_RETRIES,
        request_timeout_seconds=_config.GENAI_LIGHT_REQUEST_TIMEOUT_SECONDS,
        total_timeout_seconds=_config.GENAI_LIGHT_TOTAL_TIMEOUT_SECONDS,
    )


def _is_timeout_error(exception: BaseException) -> bool:
    """タイムアウト系のエラーかどうかを判定する"""
    if isinstance(exception, genai_errors.APIError):
        return exception.code in _TIMEOUT_STATUS_CODES
    return isinstance(
        exception,
        (httpx.TimeoutException, TimeoutError, google_exceptions.DeadlineExceeded),
    )


def _make_retry_predicate(policy: RetryPolicy) -> Callable[[BaseException], bool]:
    """タイムアウト系エラーの再試行回数を policy.timeout_retries に抑える判定関数を作る

    1回の generate_content_with_retry 呼び出しごとに生成し、タイムアウト回数を数える。
    """
    timeout_count = 0

    def _predicate(exception: BaseException) -> bool:
        nonlocal timeout_count
        if not _should_retry_api_error(exception):
            return False
        if _is_timeout_error(exception):
            timeout_count += 1
            return timeout_count <= policy.timeout_retries
        return True

    return _predicate


class _stop_at_deadline(stop_base):
    """次の待機を終えた時点で上限時刻（time.monotonic 基準）を過ぎるなら打ち切る"""

    def __init__(self, deadline: float) -> None:
        self.deadline = deadline

    def __call__(self, retry_state: RetryCallState) -> bool:
        return time.monotonic() + retry_state.upcoming_sleep >= self.deadline


def _with_request_timeout(
    config: types.GenerateContentConfig, timeout_seconds: float
) -> types.GenerateContentConfig:
    """リクエスト単位のタイムアウトを設定した config のコピーを返す"""
    timeout_ms = max(1, int(timeout_seconds * 1000))
    base = config.http_options or types.HttpOptions()
    return config.model_copy(
        update={"http_options": base.model_copy(update={"timeout": timeout_ms})}
    )


def _generate_once(
    client: Any,
    model: str,
    contents: list[types.Content],
    config: types.GenerateContentConfig,
    policy: RetryPolicy,
    deadline: float,
) -> Any:
    """上限時刻までの残り時間でタイムアウトを絞って1回だけAPIを呼び出す"""
    remaining = deadline - time.monotonic()
    # 残り時間がわずかな場合はほぼ確実に失敗するため、リクエストを送らずに打ち切る
    if remaining < max(_config.GENAI_MIN_REQUEST_TIMEOUT_SECONDS, 0.001):
        raise TimeoutError("Gen AI API呼び出しの所要時間上限に到達しました")
    timeout_seconds = min(policy.request_timeout_seconds, remaining)
    return client.models.generate_content(
        model=model,
        contents=contents,
        config=_with_request_timeout(config, timeout_seconds),
    )


def generate_content_with_retry(
    client: Any,
    model: str,
    contents: list[types.Content],
    config: types.GenerateContentConfig,
    policy: RetryPolicy | None = None,
    deadline: float | None = None,
) -> Any:
    """Vertex AI API呼び出しをリトライ付きで実行する

    試行回数・タイムアウト系エラーの再試行回数・全体の所要時間に上限を設け、
    チャンネルロックを長時間保持しないようにする。

    Args:
        client: Gen AI クライアント
        model: モデル名
        contents: 送信する履歴
        config: 生成設定
        policy: リトライ設定。省略時は main_retry_policy()
        deadline: 全体の上限時刻（time.monotonic 基準）。複数回の呼び出しで
            予算を共有する場合に渡す。省略時は policy.total_timeout_seconds 後

    Returns:
        generate_content のレスポンス

    Raises:
        Exception: リトライ対象外のエラー、または上限到達時の最後のエラー
    """
    policy = policy or main_retry_policy()
    if deadline is None:
        deadline = policy.new_deadline()
    retryer = Retrying(
        reraise=True,
        stop=stop_any(stop_after_attempt(policy.max_attempts), _stop_at_deadline(deadline)),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        retry=retry_if_exception(_make_retry_predicate(policy)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    return retryer(_generate_once, client, model, contents, config, policy, deadline)


def _run_tool(function_name: str, call: types.FunctionCall) -> dict[str, object] | str:
    """ツール関数を実行し、結果 (JSON文字列またはエラーdict) を返す"""
    func = TOOL_FUNCTIONS.get(function_name)
    if func is None:
        return {"error": f"未知の関数: {function_name}"}
    try:
        return func(**(call.args or {}))
    except Exception as e:
        logger.error(f"ツール実行エラー: {function_name}: {e}", exc_info=True)
        return {"error": "ツールの実行中にエラーが発生しました"}


def _to_response_dict(result: dict[str, object] | str) -> dict[str, Any]:
    """ツール結果をfunction_responseに渡せるdictに正規化し、長すぎる結果は切り詰める

    function_responseのresponseはdictである必要があるため、JSONの配列・数値・文字列は
    {"result": ...} で包む。履歴の肥大化を防ぐため、JSON化して
    MAX_TOOL_RESULT_CHARS を超える結果は先頭のみを文字列として残す。
    """
    value: object = result
    if isinstance(result, str):
        try:
            value = json.loads(result)
        except (ValueError, json.JSONDecodeError):
            value = {"content": result}
    response: dict[str, Any] = value if isinstance(value, dict) else {"result": value}

    serialized = json.dumps(response, ensure_ascii=False, default=str)
    if len(serialized) <= MAX_TOOL_RESULT_CHARS:
        return response
    logger.warning(
        f"ツール結果が長すぎるため切り詰め: {len(serialized)} -> {MAX_TOOL_RESULT_CHARS}文字"
    )
    return {"truncated": True, "content": serialized[:MAX_TOOL_RESULT_CHARS]}


def _execute_tool_calls(tool_calls: list[types.FunctionCall]) -> list[types.Part]:
    """ツール呼び出しを実行し、呼び出しと1対1に対応するfunction_responseを返す

    APIはfunction_callと同数のfunction_responseを要求するため、名前のない呼び出しや
    未知の関数でもスキップせずエラー応答を返す。並列呼び出しを対応付けられるよう
    function_callのidをそのまま返す。

    Args:
        tool_calls: モデルが返したfunction_callのリスト

    Returns:
        tool_callsと同じ順序・件数のfunction_response part
    """
    results: list[types.Part] = []
    for call in tool_calls:
        function_name = call.name
        result: dict[str, object] | str
        if function_name is None:
            logger.warning("名前のないツール呼び出しを検出")
            function_name = "unknown"
            result = {"error": "関数名が指定されていません"}
        else:
            logger.info(f"ツール呼び出し: {function_name}")
            result = _run_tool(function_name, call)

        results.append(
            types.Part(
                function_response=types.FunctionResponse(
                    id=call.id,
                    name=function_name,
                    response=_to_response_dict(result),
                )
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
    if isinstance(error, (httpx.TimeoutException, TimeoutError)):
        logger.error(f"APIタイムアウト: {error}", exc_info=True)
        return "ごめんね、AIが混み合ってて時間内に返事が来なかったみたい…⏳ 少し時間を置いてからもう一度話しかけてみてね！"
    logger.error(f"APIエラー: {error}", exc_info=True)
    return "ごめん！AIとの通信中にエラーが発生しちゃった...😢"


def _extract_text(content: types.Content | None) -> str | None:
    """Contentからテキスト部分のみを連結して返す (function_call・thought パートは無視)"""
    if content is None or not content.parts:
        return None
    text_parts = [p.text for p in content.parts if p.text and not getattr(p, "thought", False)]
    return "".join(text_parts) if text_parts else None


def _function_response_to_text(part: types.Part) -> types.Part:
    """function_responseのpartを、ツール結果を説明するテキストpartに変換する"""
    fr = part.function_response
    if fr is None:
        return part
    result = json.dumps(fr.response, ensure_ascii=False, default=str)
    return types.Part.from_text(text=f"（ツール {fr.name} の実行結果）\n{result}")


def rebuild_contents(
    contents: list[types.Content],
    transform: Callable[[types.Part], types.Part | None],
) -> list[types.Content]:
    """各partを変換した履歴のコピーを作る

    transformがNoneを返したpartは除去する。partが空になったContentは丸ごと除外し、
    同じroleが連続した場合は1つのContentにまとめる (APIはroleの交互性を期待するため)。

    Args:
        contents: 会話履歴
        transform: partを変換する関数。Noneを返すとそのpartを除去する

    Returns:
        変換後の履歴 (元の履歴は変更しない)
    """
    rebuilt: list[types.Content] = []
    for content in contents:
        parts = [
            converted
            for p in (content.parts or [])
            if (converted := transform(p)) is not None
        ]
        if not parts:
            continue
        if rebuilt and rebuilt[-1].role == content.role:
            prev = rebuilt[-1]
            rebuilt[-1] = types.Content(role=prev.role, parts=[*(prev.parts or []), *parts])
        else:
            rebuilt.append(types.Content(role=content.role, parts=parts))
    return rebuilt


def _flatten_part(part: types.Part) -> types.Part | None:
    """function_callは除去し、function_responseはテキストpartに変換する"""
    if part.function_call:
        return None
    if part.function_response:
        return _function_response_to_text(part)
    return part


def _flatten_function_parts(contents: list[types.Content]) -> list[types.Content]:
    """履歴のfunction系partをテキスト化・除去した送信用コピーを作る

    ツール未宣言のリクエストで履歴中のfunction_callをモデルが模倣するのを防ぐ。
    function_callは除去し、function_responseは集めた情報を活かせるよう
    テキストpartに変換する。

    Args:
        contents: 会話履歴

    Returns:
        function系partを含まない送信用の履歴
    """
    return rebuild_contents(contents, _flatten_part)


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


def _select_tools(tool_mode: "ToolMode") -> list[types.Tool]:
    """tool_modeに応じて使用するツールを選択する

    Vertex AIの制約により、google_search(grounding)とfunction_declarationsは
    同一リクエストに混在できない。

    Args:
        tool_mode: Router LLMが判定したツールモード

    Returns:
        リクエストに含めるツールのリスト
    """
    if tool_mode == "grounding":
        logger.debug("グラウンディングモード: function callingは無効 (Vertex AI制約)")
        return [types.Tool(google_search=types.GoogleSearch())]
    if tool_mode == "function_calling":
        return get_tools()
    logger.debug("ツールなしモード")
    return []


def _build_tool_request(
    client: Any,
    model_id: str,
    system_instruction: str,
    tools: list[types.Tool],
) -> dict[str, Any]:
    """ツールループで共有するリクエスト引数を構築する

    ツールループ全体で所要時間の予算 (deadline) を共有し、
    チャンネルロックの保持時間に上限を設ける。

    Args:
        client: GenAIクライアント
        model_id: 使用するモデルID
        system_instruction: システムプロンプト
        tools: リクエストに含めるツール

    Returns:
        generate_content_with_retry に渡すキーワード引数 (contents以外)
    """
    policy = main_retry_policy()
    return {
        "client": client,
        "model": model_id,
        "policy": policy,
        "deadline": policy.new_deadline(),
        "config": types.GenerateContentConfig(
            system_instruction=system_instruction,
            thinking_config=get_main_thinking_config(),
            tools=tools,  # type: ignore[arg-type]
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),  # 手動ループ
        ),
    }


def _run_tool_round(
    local_history: list[types.Content],
    tool_mode: "ToolMode",
    request: dict[str, Any],
) -> tuple[bool, str, list[types.Content]] | None:
    """ツール呼び出しループの1ラウンドを実行する

    Args:
        local_history: 会話履歴 (応答・ツール結果がin-placeで追記される)
        tool_mode: Router LLMが判定したツールモード
        request: generate_content_with_retry に渡す共通引数

    Returns:
        ループを終了する場合は (成功フラグ, 応答テキスト, 履歴)。
        ツールを実行して次のラウンドへ進む場合はNone。
    """
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

    return _process_response_content(resp_content, tool_mode, local_history, request)


def _process_response_content(
    resp_content: types.Content,
    tool_mode: "ToolMode",
    local_history: list[types.Content],
    request: dict[str, Any],
) -> tuple[bool, str, list[types.Content]] | None:
    """モデル応答のContentを処理し、ツール実行またはテキスト抽出を行う

    Args:
        resp_content: モデル応答のContent (partsはNoneでないこと)
        tool_mode: Router LLMが判定したツールモード
        local_history: 会話履歴 (応答・ツール結果がin-placeで追記される)
        request: generate_content_with_retry に渡す共通引数

    Returns:
        ループを終了する場合は (成功フラグ, 応答テキスト, 履歴)。
        ツールを実行して次のラウンドへ進む場合はNone。
    """
    parts = resp_content.parts or []
    function_calls = [p.function_call for p in parts if p.function_call]

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
        return None

    # テキスト応答を抽出
    text_parts = [p.text for p in parts if p.text]
    if text_parts:
        final_text = "".join(text_parts)
        logger.debug(f"GenAI応答受信: {truncate_text(final_text)}")
        return True, final_text, local_history

    return False, "応答を読み取れなかったよ…😢", local_history


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

    Returns:
        (成功フラグ, 応答テキストまたはエラーメッセージ, 更新後の履歴)
    """
    client = _get_genai_client()
    model_id = get_model_name()
    tools = _select_tools(tool_mode)
    request = _build_tool_request(client, model_id, system_instruction, tools)

    # contentsリストをコピーして操作する
    local_history = list(contents)

    for round_num in range(MAX_TOOL_CALL_ROUNDS + 1):
        logger.info(f"GenAIリクエスト送信 (ラウンド {round_num + 1}, モデル: {model_id})")
        result = _run_tool_round(local_history, tool_mode, request)
        if result is not None:
            return result

    # ループ上限到達: ツールなしで最終応答を取得（集めた情報を活かす）
    final_request: dict[str, Any] = {
        **request,
        "config": types.GenerateContentConfig(
            system_instruction=system_instruction,
            thinking_config=get_main_thinking_config(),
        ),
    }
    return _request_final_answer(local_history, final_request)
