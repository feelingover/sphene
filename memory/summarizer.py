"""ローリング要約エンジン: チャンネル会話の要約を非同期で生成"""

import asyncio
import json

from google.genai import types

import config
from ai.client import _get_genai_client, get_model_name
from log_utils.logger import logger
from memory.channel_context import ChannelContext, get_channel_context_store
from memory.short_term import ChannelMessage

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


class Summarizer:
    """チャンネル会話の要約を非同期で生成する"""

    def __init__(self) -> None:
        self._running: set[int] = set()

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

        if channel_id in self._running:
            logger.debug(f"要約が既に実行中: channel_id={channel_id}")
            return

        logger.info(
            f"要約トリガー: channel_id={channel_id}, "
            f"count={ctx.message_count_since_update}"
        )
        asyncio.ensure_future(self._run_summarize(channel_id, ctx, recent_messages))

    async def _run_summarize(
        self,
        channel_id: int,
        context: ChannelContext,
        messages: list[ChannelMessage],
    ) -> None:
        """要約の実行本体（非同期ラッパー）"""
        self._running.add(channel_id)
        try:
            result = await asyncio.to_thread(
                self._call_summarize_llm, context, messages
            )
            if result:
                self._apply_result(context, result, messages)
                store = get_channel_context_store()
                store.save_context(context)
                logger.info(
                    f"要約完了: channel_id={channel_id}, "
                    f"summary={result.get('summary', '')[:50]}"
                )
            else:
                logger.warning(f"要約結果が空: channel_id={channel_id}")
        except Exception as e:
            logger.error(f"要約実行エラー: channel_id={channel_id}: {e}", exc_info=True)
        finally:
            self._running.discard(channel_id)

    def _call_summarize_llm(
        self, context: ChannelContext, messages: list[ChannelMessage]
    ) -> dict | None:
        """LLMを呼び出して要約を生成する（同期）"""
        client = _get_genai_client()
        model_name = config.SUMMARIZE_MODEL or get_model_name()

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
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    response_mime_type="application/json",
                ),
            )

            content = response.text
            if not content:
                return None

            result = json.loads(content)
            return result
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

        context.summary = result.get("summary", context.summary)
        context.mood = result.get("mood", context.mood)
        context.topic_keywords = result.get(
            "topic_keywords", context.topic_keywords
        )
        context.active_users = _extract_active_users(messages)
        context.last_updated = datetime.now(timezone.utc)
        context.message_count_since_update = 0


def _format_messages_for_summary(messages: list[ChannelMessage]) -> str:
    """メッセージを要約用にフォーマットする"""
    if not messages:
        return ""
    lines = []
    for msg in messages:
        role = "[BOT]" if msg.is_bot else ""
        lines.append(f"{msg.author_name}{role}: {msg.content}")
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
