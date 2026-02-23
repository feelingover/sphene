"""反省会エンジン: 会話ログからLLMで事実を抽出し、ファクトストアに保存する"""

import asyncio
import json
import threading
import uuid
from datetime import datetime, timezone
from html import escape

from google.genai import types

import config
from ai.client import get_genai_client, get_model_name
from ai.api import generate_content_with_retry as _generate_content_with_retry
from log_utils.logger import logger
from memory.short_term import ChannelMessage

REFLECTION_PROMPT = """\
あなたはDiscordチャンネルの会話から重要な事実を抽出するAIです。
以下の会話ログを読んで、後で参照できる重要な事実をJSON配列で返してください。

--- 会話ログ ---
{messages}
---

以下のJSON形式で回答してください（重要な事実がなければ空配列 [] を返す）:
[{{"content": "事実の内容（1-2文）", "keywords": ["kw1", "kw2"], "source_user_ids": [12345], "shareable": true}}]

shareable=true にする基準: 後でチャンネルが再活性化した時に話題として振りやすい興味深い事実
"""


def _format_messages_for_reflection(messages: list[ChannelMessage]) -> str:
    """メッセージを反省会プロンプト用にフォーマットする（XMLタグでプロンプトインジェクション対策）"""
    lines = []
    for msg in messages:
        role = " bot=\"true\"" if msg.is_bot else ""
        # ユーザー入力を XML タグで囲み、属性値をエスケープ
        safe_name = escape(msg.author_name, quote=True)
        lines.append(
            f"<message user=\"{safe_name}\" id=\"{msg.author_id}\"{role}>"
            f"{escape(msg.content)}"
            f"</message>"
        )
    return "\n".join(lines)


class ReflectionEngine:
    """会話ログからファクトを抽出する反省会エンジン"""

    def __init__(self) -> None:
        self._running: set[int] = set()
        self._lock = threading.Lock()

    def maybe_reflect(
        self, channel_id: int, recent_messages: list[ChannelMessage]
    ) -> None:
        """反省会トリガー判定と非同期実行（fire-and-forget）

        Args:
            channel_id: チャンネルID
            recent_messages: 対象メッセージリスト
        """
        if len(recent_messages) < config.REFLECTION_MIN_MESSAGES:
            logger.debug(
                f"反省会スキップ（メッセージ不足）: channel_id={channel_id}, "
                f"count={len(recent_messages)}, min={config.REFLECTION_MIN_MESSAGES}"
            )
            return

        with self._lock:
            if channel_id in self._running:
                logger.debug(f"反省会が既に実行中: channel_id={channel_id}")
                return
            self._running.add(channel_id)

        logger.info(
            f"反省会トリガー: channel_id={channel_id}, count={len(recent_messages)}"
        )
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._run_reflect(channel_id, recent_messages))
        except RuntimeError:
            logger.warning(f"反省会: 実行中のevent loopがありません channel_id={channel_id}")
            with self._lock:
                self._running.discard(channel_id)

    async def _run_reflect(
        self, channel_id: int, messages: list[ChannelMessage]
    ) -> None:
        """asyncio.to_thread で _call_reflection_llm を実行し、結果を _apply_facts に渡す"""
        try:
            raw_facts = await asyncio.to_thread(self._call_reflection_llm, messages)
            if raw_facts is not None:
                self._apply_facts(channel_id, raw_facts, messages)
                logger.info(
                    f"反省会完了: channel_id={channel_id}, "
                    f"facts={len(raw_facts)}"
                )
            else:
                logger.warning(f"反省会結果が空: channel_id={channel_id}")
        except Exception as e:
            logger.error(
                f"反省会実行エラー: channel_id={channel_id}: {e}", exc_info=True
            )
        finally:
            with self._lock:
                self._running.discard(channel_id)

    def _call_reflection_llm(
        self, messages: list[ChannelMessage]
    ) -> list[dict] | None:
        """Gemini を同期呼び出し。JSON配列を返す。失敗時は None"""
        client = get_genai_client()
        model_name = config.REFLECTION_MODEL or get_model_name()

        messages_text = _format_messages_for_reflection(messages)
        if not messages_text:
            return None

        prompt = REFLECTION_PROMPT.format(messages=messages_text)

        try:
            response = _generate_content_with_retry(
                client=client,
                model=model_name,
                contents=[
                    types.Content(
                        role="user", parts=[types.Part.from_text(text=prompt)]
                    )
                ],
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    response_mime_type="application/json",
                ),
            )

            content = response.text
            if not content:
                return None

            result = json.loads(content)
            if not isinstance(result, list):
                logger.warning(f"反省会LLMが非配列を返した: {type(result)}")
                return None
            return result
        except json.JSONDecodeError as e:
            logger.warning(f"反省会LLM JSONパースエラー: {e}")
            return None
        except Exception as e:
            logger.warning(f"反省会LLM呼び出し失敗: {e}")
            return None

    def _apply_facts(
        self,
        channel_id: int,
        raw_facts: list[dict],
        messages: list[ChannelMessage],
    ) -> None:
        """LLM結果をFactオブジェクトに変換しFactStore.add_fact()で保存。
        ファクト保存が成功した場合のみ buffer.mark_reflected(channel_id) を呼ぶ"""
        from memory.fact_store import Fact, get_fact_store
        from memory.short_term import get_channel_buffer

        store = get_fact_store()
        now = datetime.now(timezone.utc)
        saved_count = 0

        for item in raw_facts:
            if not isinstance(item, dict):
                continue
            content = item.get("content", "").strip()
            if not content:
                continue

            fact = Fact(
                fact_id=str(uuid.uuid4()),
                channel_id=channel_id,
                content=content,
                keywords=item.get("keywords", []),
                source_user_ids=[
                    int(uid) for uid in item.get("source_user_ids", [])
                    if str(uid).isdigit()
                ],
                created_at=now,
                shareable=bool(item.get("shareable", False)),
            )
            store.add_fact(fact)
            saved_count += 1

        # saved_count > 0: ファクトが1件以上保存された場合
        # len(raw_facts) == 0: LLMが空配列を返した場合 = 抽出すべき事実がなかった正常終了
        # どちらの場合もカウンタをリセットして次のサイクルを開始する
        # （LLMが永続的に空を返す場合でも、ループせず次のトリガーまで待機できる）
        if saved_count > 0 or len(raw_facts) == 0:
            get_channel_buffer().mark_reflected(channel_id)


# シングルトン
_reflection_engine: ReflectionEngine | None = None


def get_reflection_engine() -> ReflectionEngine:
    """ReflectionEngineのシングルトンインスタンスを取得する"""
    global _reflection_engine
    if _reflection_engine is None:
        _reflection_engine = ReflectionEngine()
        logger.info("ReflectionEngine初期化完了")
    return _reflection_engine
