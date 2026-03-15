import asyncio
import urllib.parse
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import requests
from google.genai import types

from ai.client import _get_genai_client, get_model_name
from ai.api import (
    generate_content_with_retry as _generate_content_with_retry,
    call_genai_with_tools as _call_genai_with_tools,
    _execute_tool_calls,
    _handle_api_error,
)
from ai.router import detect_tool_mode
from config import (
    SYSTEM_PROMPT_FILENAME,
    SYSTEM_PROMPT_PATH,
)
from log_utils.logger import logger
from utils.text_utils import truncate_text

# 定数の定義
MAX_CONVERSATION_AGE_MINUTES = 30
MAX_CONVERSATION_TURNS = 10
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5MB
IMAGE_REQUEST_TIMEOUT = (3, 5)  # (connect, read)
ALLOWED_IMAGE_DOMAINS = {"cdn.discordapp.com", "media.discordapp.net"}
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

TOOL_USAGE_INSTRUCTION = (
    "FF14のゲームデータ（アイテム、製作レシピ、スキル・アクション、クエスト、マウント、ミニオン等）に関する質問は、"
    "自分の学習データに頼らず必ずツールを使って最新データを取得すること。"
    "雑談・挨拶・一般知識など、ゲームデータ検索が不要な場合はツールを使わなくてよい。"
)

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

class Sphene:
    """AIチャットボットの会話管理クラス (google-genai版)"""

    def __init__(self, system_setting: str) -> None:
        self.system_prompt = system_setting
        self.history: list[types.Content] = []
        self.last_interaction: datetime | None = datetime.now()
        self._lock = asyncio.Lock()
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

    def input_message(
        self,
        input_text: str | None,
        author_name: str = "User",
        image_urls: list[str] | None = None,
        channel_context: str | None = None,
        channel_summary: str | None = None,
        user_profile: str = "",
        relevant_facts: str = "",
    ) -> str | None:
        if not isinstance(input_text, str) or not input_text.strip():
            return None

        try:
            self.update_interaction_time()
            
            # 発言者を明示して履歴に追加
            text_with_author = f"{author_name}: {input_text}"
            parts = [types.Part.from_text(text=text_with_author)]
            
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
                            if content_type.split(";")[0].strip() not in ALLOWED_IMAGE_TYPES:
                                logger.warning(f"許可されていないContent-Typeを検出: {url} ({content_type})")
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
            
            # チャンネルのコンテキスト情報を構築
            context_section = ""
            if channel_context:
                context_section += f"\n\n--- チャンネルの直近の会話 ---\n{channel_context}\n---"
            if channel_summary:
                context_section += f"\n\n{channel_summary}"
            if user_profile:
                context_section += f"\n\n{user_profile}"
            if relevant_facts:
                context_section += f"\n\n{relevant_facts}"

            # ツール使用を促す指示とコンテキストを統合
            instruction = f"{self.system_prompt}{context_section}\n\n{TOOL_USAGE_INSTRUCTION}"

            # Router LLMで使用ツールを判定
            tool_mode = detect_tool_mode(input_text, context=channel_context)
            logger.info(f"Router判定結果: tool_mode={tool_mode}")

            # 共通ロジックで呼び出し
            success, response, updated_history = _call_genai_with_tools(
                contents=self.history,
                system_instruction=instruction,
                tool_mode=tool_mode,
            )
            
            # 履歴を更新
            self.history = updated_history
            
            if success:
                self.trim_conversation_history()
            return response
        except Exception as e:
            logger.critical(f"input_messageエラー: {e}", exc_info=True)
            return "予期せぬエラーが発生しちゃった...😢"
    async def async_input_message(
        self,
        input_text: str | None,
        author_name: str = "User",
        image_urls: list[str] | None = None,
        channel_context: str | None = None,
        channel_summary: str | None = None,
        user_profile: str = "",
        relevant_facts: str = "",
    ) -> str | None:
        """スレッドセーフな非同期ラッパー。

        同一チャンネルへの並行呼び出しを Lock で直列化してから
        asyncio.to_thread に渡す。これにより self.history の競合書き込みを防ぐ。
        """
        async with self._lock:
            return await asyncio.to_thread(
                self.input_message,
                input_text=input_text,
                author_name=author_name,
                image_urls=image_urls,
                channel_context=channel_context,
                channel_summary=channel_summary,
                user_profile=user_profile,
                relevant_facts=relevant_facts,
            )


def generate_short_ack(channel_context: str, trigger_message: str) -> str | None:
    """軽量な相槌を生成する

    Args:
        channel_context: チャンネルの直近会話コンテキスト
        trigger_message: トリガーメッセージ

    Returns:
        相槌テキスト、またはエラー時None
    """
    try:
        client = _get_genai_client()
        model_id = get_model_name()
        system_prompt = load_system_prompt()

        instruction = (
            f"{system_prompt}\n\n"
            f"以下の会話の流れを読んで、短い自然な相槌を返してね。\n"
            f"必ず1〜2文以内に収めること。長い説明・解説・提案は絶対に不要。感情や共感を少し込めるだけでOK。\n\n"
            f"--- チャンネルの直近の会話 ---\n{channel_context}\n---"
        )

        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=trigger_message)],
            )
        ]

        response = _generate_content_with_retry(
            client=client,
            model=model_id,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=instruction,
                max_output_tokens=1000,
            ),
        )

        candidate = response.candidates[0] if response.candidates else None
        if candidate and candidate.content and candidate.content.parts:
            text_parts = [
                p.text
                for p in candidate.content.parts
                if p.text and not getattr(p, "thought", False)
            ]
            if text_parts:
                result = "".join(text_parts)
                logger.debug(f"相槌生成: {result}")
                return result
        finish_reason = candidate.finish_reason if candidate else "no_candidate"
        logger.warning(
            "相槌生成: 有効なテキストパーツが得られませんでした (finish_reason=%s)",
            finish_reason,
        )
        return None
    except Exception as e:
        logger.error(f"相槌生成エラー: {e}", exc_info=True)
        return None


# チャンネルごとの会話インスタンスを保持する辞書
channel_conversations: defaultdict[str, Sphene] = defaultdict(
    lambda: Sphene(system_setting=load_system_prompt())
)

def cleanup_expired_conversations() -> int:
    """期限切れの会話をメモリから削除する"""
    expired_ids = [
        channel_id for channel_id, api in channel_conversations.items() if api.is_expired()
    ]
    for channel_id in expired_ids:
        del channel_conversations[channel_id]

    if expired_ids:
        logger.info(f"期限切れの会話をクリーンアップしました: {len(expired_ids)}件")
    return len(expired_ids)
