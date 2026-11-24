"""反省会エンジン: 会話ログからLLMで事実を抽出し、ファクトストアに保存する"""

import asyncio
import json
import threading
import uuid
from datetime import datetime, timezone
from html import escape
from typing import Any

from google.genai import types

import config
from ai.client import get_genai_client, get_light_thinking_config, get_model_name
from ai.api import generate_content_with_retry as _generate_content_with_retry
from log_utils.logger import logger
from memory.backoff import FailureBackoff
from memory.fact_store import Fact
from memory.sanitize import safe_author_name, sanitize_llm_text, sanitize_llm_text_list
from memory.short_term import ChannelMessage
from utils.background_tasks import track_background_task

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

USER_PROFILE_REFLECTION_PROMPT = """\
あなたはDiscordの会話からユーザーの特性を抽出するAIです。
以下の会話ログを読み、登場した各ユーザーについて情報をJSON配列で返してください。

--- 会話ログ ---
{messages}
---

以下のJSON形式で回答してください（情報がなければ空配列 [] を返す）:
[{{
  "user_id": <数値>,
  "tags": ["ラベル1", "ラベル2"],
  "notable_facts": ["具体的な事実1", "具体的な事実2"],
  "personality_notes": "性格の特徴（1-2文）",
  "last_conversation_summary": "今回の会話の要約（1-2文）",
  "nickname": "ユーザーが呼んでほしいと言った名前（なければJSONのnull）",
  "preferred_tone": "カジュアル" または "フォーマル"（不明な場合はJSONのnull）,
  "emotional_state_last": "楽しそう" や "疲れ気味" など（不明な場合はJSONのnull）
}}]

抽出基準:
- tags: ラベル的・検索向き（"プログラマー", "猫好き" など）
- notable_facts: 具体的事実（"犬を飼っている", "東京在住" など）
- emotional_state_last: ざっくりした感情のみ（詳細な感情分析は行わない）
- ボットメッセージは対象外
"""


def _format_messages_for_reflection(messages: list[ChannelMessage]) -> str:
    """メッセージを反省会プロンプト用にフォーマットする（XMLタグでプロンプトインジェクション対策）"""
    lines = []
    for msg in messages:
        role = " bot=\"true\"" if msg.is_bot else ""
        # ユーザー入力を XML タグで囲み、属性値をエスケープ
        safe_name = escape(safe_author_name(msg.author_name), quote=True)
        lines.append(
            f"<message user=\"{safe_name}\" id=\"{msg.author_id}\"{role}>"
            f"{escape(msg.content)}"
            f"</message>"
        )
    return "\n".join(lines)


_MAX_FACT_CONTENT_LENGTH = 300
_MAX_FACT_KEYWORD_LENGTH = 30
_MAX_FACT_KEYWORDS = 10


def _parse_user_id(value: object) -> int | None:
    """LLMが返したユーザーIDを int に変換する（bool・不正値は None）"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _participant_ids(messages: list[ChannelMessage]) -> set[int]:
    """会話ログに登場した人間ユーザーのIDを返す（ボットは除外）"""
    return {msg.author_id for msg in messages if not msg.is_bot}


def _filter_source_ids(raw_ids: object, allowed_ids: set[int]) -> list[int]:
    """LLMが返した source_user_ids を会話の参加者だけに絞り、重複を除く

    会話内容で誘導された無関係なユーザーIDにファクトが紐づくと、
    そのユーザーの検索時にブーストがかかってしまうため除外する。
    """
    result: list[int] = []
    for value in raw_ids if isinstance(raw_ids, list) else []:
        uid = _parse_user_id(value)
        if uid is None or uid in result:
            continue
        if uid not in allowed_ids:
            logger.warning(f"会話に登場しないsource_user_idを除外: user_id={uid}")
            continue
        result.append(uid)
    return result


def _parse_fact_item(item: object, allowed_ids: set[int]) -> dict | None:
    """反省会LLMが返したファクト1件を検証・正規化する

    Args:
        item: JSON配列の1要素
        allowed_ids: source_user_ids として許可する会話参加者のID

    Returns:
        content / keywords / source_user_ids / shareable を持つ辞書。不正な場合は None。
    """
    if not isinstance(item, dict):
        return None
    content = sanitize_llm_text(item.get("content"), _MAX_FACT_CONTENT_LENGTH)
    if not content:
        return None
    source_ids = _filter_source_ids(item.get("source_user_ids"), allowed_ids)
    return {
        "content": content,
        "keywords": sanitize_llm_text_list(
            item.get("keywords"), _MAX_FACT_KEYWORD_LENGTH, _MAX_FACT_KEYWORDS
        ),
        "source_user_ids": source_ids,
        "shareable": item.get("shareable") is True,
    }


def _apply_user_profile_results(
    result: list, messages: list[ChannelMessage]
) -> int:
    """ユーザープロファイルLLMの結果を、会話に登場した人間ユーザーにだけ反映する

    LLMが返した user_id は会話ログ内の発言者と照合し、ログに登場しない
    ユーザー（他チャンネルのユーザーや、発言内容で誘導された任意のID）は無視する。
    プロファイルは会話が行われたギルドのものだけを更新する。

    Args:
        result: LLMが返したJSON配列
        messages: 反省会の対象メッセージ

    Returns:
        更新したプロファイル数
    """
    from memory.user_profile import get_user_profile_store

    guild_id = next((msg.guild_id for msg in messages if msg.guild_id is not None), None)
    if guild_id is None:
        logger.debug("ギルドIDが不明なためユーザープロファイル反省会をスキップ")
        return 0
    allowed_ids = _participant_ids(messages)
    store = get_user_profile_store()
    updated_count = 0
    for item in result:
        if not isinstance(item, dict):
            continue
        user_id = _parse_user_id(item.get("user_id"))
        if user_id is None:
            continue
        if user_id not in allowed_ids:
            logger.warning(
                f"会話に登場しないuser_idのプロファイル更新を拒否: user_id={user_id}"
            )
            continue
        store.update_from_reflection(guild_id, user_id, item)
        updated_count += 1
    return updated_count


class ReflectionEngine:
    """会話ログからファクトを抽出する反省会エンジン"""

    def __init__(self) -> None:
        self._running: set[int] = set()
        self._lock = threading.Lock()
        self._backoff = FailureBackoff(
            config.MEMORY_LLM_BACKOFF_BASE_SECONDS, config.MEMORY_LLM_BACKOFF_MAX_SECONDS
        )

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

        if self._backoff.is_blocked(channel_id):
            logger.debug(f"反省会スキップ（失敗後のバックオフ中）: channel_id={channel_id}")
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
            track_background_task(loop.create_task(
                self._run_reflect(channel_id, recent_messages),
                name=f"reflect_{channel_id}",
            ))
        except RuntimeError:
            logger.warning(f"反省会: 実行中のevent loopがありません channel_id={channel_id}")
            with self._lock:
                self._running.discard(channel_id)

    async def _run_reflect(
        self, channel_id: int, messages: list[ChannelMessage]
    ) -> None:
        """反省会LLMを実行してファクトを保存し、成否に応じてバックオフを更新する

        失敗（LLM呼び出し失敗・有効なファクトが0件）時はバックオフし、
        REFLECTION_MAX_FAILURES 回連続で失敗したメッセージ群は諦めてチェックポイントを進める。
        ユーザープロファイルの更新はチェックポイントが進んだ（メッセージ群の処理が
        確定した）場合のみ行い、再試行のたびに同じ会話で更新しないようにする。
        """
        try:
            raw_facts = await asyncio.to_thread(self._call_reflection_llm, messages)
            completed = raw_facts is not None and await self._apply_facts(
                channel_id, raw_facts, messages
            )
            if completed:
                self._backoff.reset(channel_id)
                logger.info(
                    f"反省会完了: channel_id={channel_id}, facts={len(raw_facts or [])}"
                )
            else:
                completed = self._handle_reflection_failure(channel_id, messages)

            if completed and config.LIVING_MEMORY_ENABLED:
                await asyncio.to_thread(self._call_user_profile_llm, messages)
        except Exception as e:
            logger.error(
                f"反省会実行エラー: channel_id={channel_id}: {e}", exc_info=True
            )
        finally:
            with self._lock:
                self._running.discard(channel_id)

    def _handle_reflection_failure(
        self, channel_id: int, messages: list[ChannelMessage]
    ) -> bool:
        """反省会の失敗を記録し、上限に達したらメッセージ群を諦める

        Returns:
            メッセージ群を諦めてチェックポイントを進めた場合True
        """
        from memory.short_term import get_channel_buffer

        failures = self._backoff.record_failure(channel_id)
        if failures < config.REFLECTION_MAX_FAILURES or not messages:
            logger.warning(
                f"反省会失敗（バックオフ）: channel_id={channel_id}, "
                f"連続失敗={failures}/{config.REFLECTION_MAX_FAILURES}"
            )
            return False

        logger.warning(
            f"反省会が{failures}回連続で失敗したため対象メッセージを破棄: "
            f"channel_id={channel_id}, messages={len(messages)}"
        )
        until = max(msg.timestamp for msg in messages)
        get_channel_buffer().mark_reflected(channel_id, until=until)
        self._backoff.reset(channel_id)
        return True

    def _call_reflection_llm(
        self, messages: list[ChannelMessage]
    ) -> list[dict] | None:
        """Gemini を同期呼び出し。JSON配列を返す。失敗時は None"""
        client = get_genai_client()
        model_name = get_model_name()

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
                    thinking_config=get_light_thinking_config(),
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
            logger.warning(f"反省会LLM JSONパースエラー: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.warning(f"反省会LLM呼び出し失敗: {e}", exc_info=True)
            return None

    async def _apply_facts(
        self,
        channel_id: int,
        raw_facts: list[dict],
        messages: list[ChannelMessage],
    ) -> bool:
        """LLM結果を検証してFactに変換し、FactStore.add_fact()で保存する

        有効なファクトを1件以上処理できた場合（重複でスキップした場合を含む）、
        またはLLMが空配列を返した場合に、処理したメッセージの最大タイムスタンプで
        チェックポイントを進める。

        Args:
            channel_id: チャンネルID
            raw_facts: LLMが返したJSON配列
            messages: 反省会の対象メッセージ

        Returns:
            チェックポイントを進めた（反省会として成功した）場合True。
            LLMが不正な要素しか返さなかった場合はFalse
        """
        from memory.short_term import get_channel_buffer

        allowed_ids = _participant_ids(messages)
        parsed = [
            item
            for item in (_parse_fact_item(raw, allowed_ids) for raw in raw_facts)
            if item
        ]

        saved_count = await self._save_facts(channel_id, parsed)

        logger.debug(
            f"ファクト反映: channel_id={channel_id}, valid={len(parsed)}, saved={saved_count}"
        )
        if not parsed and raw_facts:
            logger.warning(
                f"反省会LLMが有効なファクトを返さなかった: channel_id={channel_id}, "
                f"items={len(raw_facts)}"
            )
            return False
        if messages:
            until = max(msg.timestamp for msg in messages)
            get_channel_buffer().mark_reflected(channel_id, until=until)
        return True

    async def _save_facts(self, channel_id: int, parsed: list[dict[str, Any]]) -> int:
        """検証済みファクトに埋め込みを付けて FactStore に保存する

        1件以上保存できた場合はチャンネル単位で永続化する。

        Args:
            channel_id: チャンネルID
            parsed: _parse_fact_item で検証済みのファクト辞書リスト

        Returns:
            新規に保存できたファクト数（重複でスキップしたものは含まない）
        """
        from ai.client import generate_embedding
        from memory.fact_store import get_fact_store

        store = get_fact_store()
        now = datetime.now(timezone.utc)
        embeddings = await asyncio.gather(
            *[asyncio.to_thread(generate_embedding, item["content"]) for item in parsed]
        )

        saved_count = 0
        for item, embedding in zip(parsed, embeddings):
            fact = Fact(
                fact_id=str(uuid.uuid4()),
                channel_id=channel_id,
                content=item["content"],
                keywords=item["keywords"],
                source_user_ids=item["source_user_ids"],
                created_at=now,
                shareable=item["shareable"],
                embedding=embedding,
            )
            # 初回は永続化先からの読み込みが発生しうるためスレッドで実行する
            if await asyncio.to_thread(store.add_fact, fact):
                saved_count += 1

        if saved_count > 0:
            await asyncio.to_thread(store.persist_channel, channel_id)
        return saved_count

    def _call_user_profile_llm(self, messages: list[ChannelMessage]) -> None:
        """ユーザープロファイル専用LLMコール。会話からユーザー特性を抽出してストアに反映

        Args:
            messages: 対象メッセージリスト
        """
        from memory.user_profile import get_user_profile_store

        client = get_genai_client()
        model_name = get_model_name()

        messages_text = _format_messages_for_reflection(messages)
        if not messages_text:
            return

        prompt = USER_PROFILE_REFLECTION_PROMPT.format(messages=messages_text)

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
                    thinking_config=get_light_thinking_config(),
                    response_mime_type="application/json",
                ),
            )

            content = response.text
            if not content:
                return

            result = json.loads(content)
            if not isinstance(result, list):
                logger.warning(f"ユーザープロファイルLLMが非配列を返した: {type(result)}")
                return

            updated_count = _apply_user_profile_results(result, messages)
            if updated_count > 0:
                get_user_profile_store().persist_all()
            logger.info(f"ユーザープロファイル反省会完了: {updated_count}件処理")
        except json.JSONDecodeError as e:
            logger.warning(f"ユーザープロファイルLLM JSONパースエラー: {e}", exc_info=True)
        except Exception as e:
            logger.warning(f"ユーザープロファイルLLM呼び出し失敗: {e}", exc_info=True)


# シングルトン
_reflection_engine: ReflectionEngine | None = None
_reflection_engine_lock = threading.Lock()


def get_reflection_engine() -> ReflectionEngine:
    """ReflectionEngineのシングルトンインスタンスを取得する"""
    global _reflection_engine
    if _reflection_engine is None:
        with _reflection_engine_lock:
            if _reflection_engine is None:
                _reflection_engine = ReflectionEngine()
                logger.info("ReflectionEngine初期化完了")
    return _reflection_engine
