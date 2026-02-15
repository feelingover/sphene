import base64
import json
import logging
import time
import traceback
import urllib.parse
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from google.genai import types
from google.api_core import exceptions as google_exceptions

from ai.client import _get_genai_client, get_model_name
from config import (
    GEMINI_MODEL,
    SYSTEM_PROMPT_FILENAME,
    SYSTEM_PROMPT_PATH,
    ENABLE_GOOGLE_SEARCH_GROUNDING,
)
from ai.tools import get_tools, TOOL_FUNCTIONS
from log_utils.logger import logger

# 定数の定義
MAX_CONVERSATION_AGE_MINUTES = 30
MAX_CONVERSATION_TURNS = 10
MAX_TOOL_CALL_ROUNDS = 3
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5MB
IMAGE_REQUEST_TIMEOUT = (3, 5)  # (connect, read)
ALLOWED_IMAGE_DOMAINS = {"cdn.discordapp.com", "media.discordapp.net"}

def truncate_text(text: str, max_length: int = 30) -> str:
    """テキストを切り詰める"""
    if not text:
        return ""
    return text[:max_length] + "..." if len(text) > max_length else text

# プロンプトのキャッシュ
_prompt_cache: dict[str, str] = {}

def _load_prompt_from_local(fail_on_error: bool = False) -> str | None:
    prompt_path = Path(SYSTEM_PROMPT_PATH)
    try:
        prompt_content = prompt_path.read_text(encoding="utf-8").strip()
        return prompt_content if prompt_content else None
    except Exception as e:
        if fail_on_error:
            raise RuntimeError(f"システムプロンプトの読み込みに失敗しました: {e}") from e
        return None

def _get_default_prompt() -> str:
    return "あなたは役立つAIアシスタントです。"

def load_system_prompt(force_reload: bool = False, fail_on_error: bool = False) -> str:
    if SYSTEM_PROMPT_FILENAME in _prompt_cache and not force_reload:
        return _prompt_cache[SYSTEM_PROMPT_FILENAME]
    prompt_content = _load_prompt_from_local(fail_on_error)
    if not prompt_content:
        prompt_content = _get_default_prompt()
    _prompt_cache[SYSTEM_PROMPT_FILENAME] = prompt_content
    return prompt_content

def _execute_tool_calls(tool_calls: list[types.FunctionCall]) -> list[types.Part]:
    """共通のツール実行ロジック"""
    results: list[types.Part] = []
    for call in tool_calls:
        function_name = call.name
        logger.info(f"ツール呼び出し: {function_name}")
        func = TOOL_FUNCTIONS.get(function_name)
        if func is None:
            result_content = {"error": f"未知の関数: {function_name}"}
        else:
            try:
                arguments = call.args
                result_content = func(**arguments)
            except Exception as e:
                logger.error(f"ツール実行エラー: {function_name}: {e}", exc_info=True)
                result_content = {"error": "ツールの実行中にエラーが発生しました"}

        if isinstance(result_content, str):
            try:
                result_dict = json.loads(result_content)
            except:
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
    if "404" in str(error):
        return f"ごめんね、指定されたAIモデル「{GEMINI_MODEL}」が見つからないか、このリージョンでは使えないみたい…😢"
    if "429" in str(error):
        return "ごめんね、今ちょっとAIが混み合ってるみたい…💦 少し時間を置いてからもう一度話しかけてみてね！"
    logger.error(f"APIエラー: {error}", exc_info=True)
    return "ごめん！AIとの通信中にエラーが発生しちゃった...😢"

def _call_genai_with_tools(
    contents: list[types.Content],
    system_instruction: str,
) -> tuple[bool, str, list[types.Content]]:
    """ツール呼び出しループを含むGenAI呼び出し (共通ロジック)"""
    client = _get_genai_client()
    model_id = get_model_name()
    
    # ツール設定
    tools = get_tools()
    if ENABLE_GOOGLE_SEARCH_GROUNDING:
        tools.append(types.Tool(google_search_retrieval=types.GoogleSearchRetrieval()))

    # contentsリストをコピーして操作する
    local_history = list(contents)

    for round_num in range(MAX_TOOL_CALL_ROUNDS + 1):
        logger.info(f"GenAIリクエスト送信 (ラウンド {round_num + 1}, モデル: {model_id})")
        
        try:
            response = client.models.generate_content(
                model=model_id,
                contents=local_history,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    tools=tools,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True), # 手動ループ
                ),
            )
        except Exception as e:
            return False, _handle_api_error(e), local_history

        if not response.candidates:
            return False, "AIからの応答が空だったよ…🤔", local_history

        resp_content = response.candidates[0].content
        local_history.append(resp_content)

        # ツール呼び出しがあるか確認
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

    return False, "処理が複雑すぎて諦めちゃった…😢", local_history

class Sphene:
    """AIチャットボットの会話管理クラス (google-genai版)"""

    def __init__(self, system_setting: str) -> None:
        self.system_prompt = system_setting
        self.history: list[types.Content] = []
        self.last_interaction: datetime | None = datetime.now()
        logger.info("Spheneインスタンスを初期化 (Google Gen AI SDK)")

    def is_expired(self) -> bool:
        if self.last_interaction is None:
            return False
        expiry_time = self.last_interaction + timedelta(minutes=MAX_CONVERSATION_AGE_MINUTES)
        return datetime.now() > expiry_time

    def update_interaction_time(self) -> None:
        self.last_interaction = datetime.now()

    def trim_conversation_history(self) -> None:
        if len(self.history) <= (MAX_CONVERSATION_TURNS * 2):
            return
        recent_history = self.history[-(MAX_CONVERSATION_TURNS * 2) :]
        start_idx = 0
        for i, content in enumerate(recent_history):
            if content.role == "user":
                start_idx = i
                break
        self.history = recent_history[start_idx:]

    def input_message(self, input_text: str | None, image_urls: list[str] | None = None) -> str | None:
        if not isinstance(input_text, str) or not input_text.strip():
            return None

        try:
            self.update_interaction_time()
            parts = [types.Part.from_text(text=input_text)]
            
            if image_urls:
                for url in image_urls:
                    try:
                        parsed = urllib.parse.urlparse(url)
                        if parsed.hostname not in ALLOWED_IMAGE_DOMAINS:
                            logger.warning(f"許可されていないドメインの画像をスキップ: {url}")
                            continue

                        with requests.get(url, timeout=IMAGE_REQUEST_TIMEOUT, stream=True) as resp:
                            resp.raise_for_status()

                            content_type = resp.headers.get("Content-Type", "")
                            if not content_type.startswith("image/"):
                                logger.warning(f"画像以外のContent-Typeを検出: {url} ({content_type})")
                                continue

                            content_length = resp.headers.get("Content-Length")
                            try:
                                if content_length and int(content_length) > MAX_IMAGE_BYTES:
                                    logger.warning(f"画像サイズ超過でスキップ: {url} ({content_length} bytes)")
                                    continue
                            except (ValueError, TypeError):
                                logger.warning(f"不正なContent-Length: {url} ({content_length})")

                            data = bytearray()
                            for chunk in resp.iter_content(chunk_size=64 * 1024):
                                if not chunk:
                                    continue
                                data.extend(chunk)
                                if len(data) > MAX_IMAGE_BYTES:
                                    logger.warning(f"画像サイズ上限超過で中断: {url} ({len(data)} bytes)")
                                    data = bytearray()
                                    break

                            if not data:
                                continue

                            parts.append(
                                types.Part.from_bytes(
                                    data=bytes(data),
                                    mime_type=content_type,
                                )
                            )
                    except Exception as e:
                        logger.error(f"画像読み込み失敗: {url} - {e}")

            self.history.append(types.Content(role="user", parts=parts))
            
            # 共通ロジックで呼び出し
            success, response, updated_history = _call_genai_with_tools(
                contents=self.history,
                system_instruction=self.system_prompt
            )
            
            # 履歴を更新
            self.history = updated_history
            
            if success:
                self.trim_conversation_history()
            return response
        except Exception as e:
            logger.critical(f"input_messageエラー: {e}", exc_info=True)
            return "予期せぬエラーが発生しちゃった...😢"

def generate_contextual_response(channel_context: str, trigger_message: str, system_prompt: str | None = None) -> str | None:
    try:
        if system_prompt is None:
            system_prompt = load_system_prompt()
        
        # ツールを積極的に使うように指示を追加！
        instruction = (
            f"{system_prompt}\n\n"
            f"--- チャンネルの直近の会話 ---\n{channel_context}\n---\n"
            f"自然に会話に参加してね。もし知らないことや最新の情報が必要なら、積極的にツールを使って調べてね！"
        )
        
        # 1-shot のコンテンツを作成
        contents = [types.Content(role="user", parts=[types.Part.from_text(text=trigger_message)])]
        
        # 共通ロジックで呼び出し（ツールも使えるようになる！）
        success, response, _ = _call_genai_with_tools(
            contents=contents,
            system_instruction=instruction
        )
        
        return response if success else None
    except Exception as e:
        logger.error(f"コンテキスト応答生成エラー: {e}", exc_info=True)
        return None

def reload_system_prompt(fail_on_error: bool = False) -> bool:
    """システムプロンプトを強制的に再読み込みする"""
    try:
        load_system_prompt(force_reload=True, fail_on_error=fail_on_error)
        return True
    except Exception as e:
        logger.error(f"プロンプト再読み込みエラー: {e}", exc_info=True)
        if fail_on_error:
            raise
        return False

# ユーザーごとの会話インスタンスを保持する辞書
user_conversations: defaultdict[str, Sphene] = defaultdict(
    lambda: Sphene(system_setting=load_system_prompt())
)

def cleanup_expired_conversations() -> int:
    """期限切れの会話をメモリから削除する"""
    expired_ids = [
        user_id for user_id, api in user_conversations.items() if api.is_expired()
    ]
    for user_id in expired_ids:
        del user_conversations[user_id]

    if expired_ids:
        logger.info(f"期限切れの会話をクリーンアップしました: {len(expired_ids)}件")
    return len(expired_ids)
