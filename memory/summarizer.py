"""ローリング要約エンジン: チャンネル会話の要約を非同期で生成"""

import asyncio
import json
import threading
from html import escape

from google.genai import types

import config
from ai.client import _get_genai_client, get_light_thinking_config, get_model_name
from ai.api import generate_content_with_retry as _generate_content_with_retry
from log_utils.logger import logger
from memory.backoff import FailureBackoff
from memory.channel_context import ChannelContext, get_channel_context_store
from memory.sanitize import sanitize_llm_text, sanitize_llm_text_list
from memory.short_term import ChannelMessage
from utils.background_tasks import track_background_task

SUMMARIZE_PROMPT = """\
あなたはDiscordチャンネルの会話を要約するAIです。
以下の会話ログを読んで、JSON形式で要約してください。

{previous_context}

--- 会話ログ ---
{messages}
---

以下のJSON形式で回答してください:
{{"summary": "会話の要約（2-3文）", "mood": "場の雰囲気（一言）", "topic_keywords": ["話題1", "話題2"]}}
"""

# 要約はsystem_instructionに注入されるため、長さを制限する
_MAX_SUMMARY_LENGTH = 500
_MAX_MOOD_LENGTH = 50
_MAX_KEYWORD_LENGTH = 30
_MAX_KEYWORDS = 10


def _parse_summary_result(raw: object) -> dict | None:
    """要約LLMの出力を検証・サニタイズする

    要約はsystem_instructionに注入されるため、型・長さを検証し改行や制御文字を除去する。
    単一要素の配列で包まれた出力は中身を取り出す。

    Args:
        raw: json.loadsした要約LLMの出力

    Returns:
        {"summary": str, "mood": str | None, "topic_keywords": list[str] | None}。
        要約本文が得られない場合はNone。mood / topic_keywords がNoneの場合は前回値を維持する
    """
    if isinstance(raw, list) and len(raw) == 1:
        raw = raw[0]
    if not isinstance(raw, dict):
        logger.warning(f"要約LLMが非オブジェクトを返した: {type(raw)}")
        return None
    summary = sanitize_llm_text(raw.get("summary"), _MAX_SUMMARY_LENGTH)
    if summary is None:
        logger.warning("要約LLMの出力に有効な summary がない")
        return None
    keywords = raw.get("topic_keywords")
    return {
        "summary": summary,
        "mood": sanitize_llm_text(raw.get("mood"), _MAX_MOOD_LENGTH),
        "topic_keywords": (
            sanitize_llm_text_list(keywords, _MAX_KEYWORD_LENGTH, _MAX_KEYWORDS)
            if isinstance(keywords, list)
            else None
        ),
    }


class Summarizer:
    """チャンネル会話の要約を非同期で生成する"""

    def __init__(self) -> None:
        self._running: set[int] = set()
        self._running_lock = threading.Lock()
        self._backoff = FailureBackoff(
            config.MEMORY_LLM_BACKOFF_BASE_SECONDS, config.MEMORY_LLM_BACKOFF_MAX_SECONDS
        )

    def maybe_summarize(
        self, channel_id: int, recent_messages: list[ChannelMessage]
    ) -> None:
        """要約トリガー判定と非同期実行

        Args:
            channel_id: チャンネルID
            recent_messages: 直近メッセージリスト
        """
        store = get_channel_context_store()
        ctx = store.get_context(channel_id)

        if not ctx.should_summarize():
            return

        if self._backoff.is_blocked(channel_id):
            logger.debug(f"要約スキップ（失敗後のバックオフ中）: channel_id={channel_id}")
            return

        with self._running_lock:
            if channel_id in self._running:
                logger.debug(f"要約が既に実行中: channel_id={channel_id}")
                return
            # create_task の前に追加することで、次のイベントループ反復で
            # maybe_summarize が再度呼ばれても二重スケジュールされない
            self._running.add(channel_id)

        logger.info(
            f"要約トリガー: channel_id={channel_id}, "
            f"count={ctx.message_count_since_update}"
        )
        track_background_task(asyncio.create_task(
            self._run_summarize(channel_id, ctx, recent_messages),
            name=f"summarize_{channel_id}",
        ))

    async def _run_summarize(
        self,
        channel_id: int,
        context: ChannelContext,
        messages: list[ChannelMessage],
    ) -> None:
        """要約の実行本体（非同期ラッパー）"""
        try:
            result = await asyncio.to_thread(
                self._call_summarize_llm, context, messages
            )
            if result:
                self._apply_result(context, result, messages)
                store = get_channel_context_store()
                await asyncio.to_thread(store.save_context, context)
                self._backoff.reset(channel_id)
                logger.info(
                    f"要約完了: channel_id={channel_id}, summary={result.get('summary', '')[:50]}"
                )
            else:
                failures = self._backoff.record_failure(channel_id)
                logger.warning(
                    f"要約結果が空（バックオフ）: channel_id={channel_id}, 連続失敗={failures}"
                )
        except Exception as e:
            self._backoff.record_failure(channel_id)
            logger.error(f"要約実行エラー: channel_id={channel_id}: {e}", exc_info=True)
        finally:
            with self._running_lock:
                self._running.discard(channel_id)

    def _call_summarize_llm(
        self, context: ChannelContext, messages: list[ChannelMessage]
    ) -> dict | None:
        """LLMを呼び出して要約を生成する（同期）"""
        client = _get_genai_client()
        model_name = get_model_name()

        messages_text = _format_messages_for_summary(messages)
        if not messages_text:
            return None

        previous_context = ""
        if context.summary:
            previous_context = f"前回の要約: {context.summary}"

        prompt = SUMMARIZE_PROMPT.format(
            previous_context=previous_context,
            messages=messages_text,
        )

        try:
            response = _generate_content_with_retry(
                client=client,
                model=model_name,
                contents=[types.Content(role="user", parts=[types.Part.from_text(text=prompt)])],
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    thinking_config=get_light_thinking_config(),
                    response_mime_type="application/json",
                ),
            )

            content = response.text
            if not content:
                return None

            return _parse_summary_result(json.loads(content))
        except Exception as e:
            logger.warning(f"要約LLM呼び出し失敗: {e}")
            return None

    def _apply_result(
        self,
        context: ChannelContext,
        result: dict,
        messages: list[ChannelMessage],
    ) -> None:
        """要約結果をContextに適用してカウンタをリセットする"""
        from datetime import datetime, timezone

        if result.get("summary") is not None:
            context.summary = result["summary"]
        if result.get("mood") is not None:
            context.mood = result["mood"]
        if result.get("topic_keywords") is not None:
            context.topic_keywords = result["topic_keywords"]
        context.active_users = _extract_active_users(messages)
        context.last_updated = datetime.now(timezone.utc)
        context.message_count_since_update = 0


def _format_messages_for_summary(messages: list[ChannelMessage]) -> str:
    """メッセージを要約用にフォーマットする（XMLタグでプロンプトインジェクション対策）"""
    if not messages:
        return ""
    lines = []
    for msg in messages:
        role = ' bot="true"' if msg.is_bot else ""
        safe_name = escape(msg.author_name, quote=True)
        lines.append(
            f'<message user="{safe_name}"{role}>'
            f'{escape(msg.content)}'
            f'</message>'
        )
    return "\n".join(lines)


def _extract_active_users(messages: list[ChannelMessage]) -> list[str]:
    """メッセージリストからユニーク非botユーザー名を出現順で抽出する"""
    seen: set[str] = set()
    users: list[str] = []
    for msg in messages:
        if not msg.is_bot and msg.author_name not in seen:
            seen.add(msg.author_name)
            users.append(msg.author_name)
    return users


# シングルトン
_summarizer: Summarizer | None = None


def get_summarizer() -> Summarizer:
    """Summarizerのシングルトンインスタンスを取得する"""
    global _summarizer
    if _summarizer is None:
        _summarizer = Summarizer()
        logger.info("Summarizer初期化完了")
    return _summarizer
