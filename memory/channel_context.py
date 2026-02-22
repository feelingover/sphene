"""チャンネルコンテキスト: ローリング要約によるチャンネルの雰囲気把握"""

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone

import config
from log_utils.logger import logger


@dataclass
class ChannelContext:
    """チャンネルのコンテキスト情報"""

    channel_id: int
    summary: str = ""
    mood: str = ""
    topic_keywords: list[str] = field(default_factory=list)
    active_users: list[str] = field(default_factory=list)
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    message_count_since_update: int = 0

    def increment_message_count(self) -> None:
        """メッセージカウンタをインクリメントする"""
        self.message_count_since_update += 1

    def should_summarize_by_count(self) -> bool:
        """メッセージ数によるトリガー判定"""
        return self.message_count_since_update >= config.SUMMARIZE_EVERY_N_MESSAGES

    def should_summarize_by_time(self) -> bool:
        """時間経過によるトリガー判定（メッセージが1件以上ある場合のみ）"""
        if self.message_count_since_update == 0:
            return False
        now = datetime.now(timezone.utc)
        elapsed_minutes = (now - self.last_updated).total_seconds() / 60
        return elapsed_minutes >= config.SUMMARIZE_EVERY_N_MINUTES

    def should_summarize(self) -> bool:
        """要約すべきかの判定（カウントまたは時間のハイブリッド）"""
        return self.should_summarize_by_count() or self.should_summarize_by_time()

    def format_for_injection(self) -> str:
        """LLM注入用のフォーマット済み文字列を返す"""
        if not self.summary:
            return ""
        parts = [f"【チャンネルの状況】\n{self.summary}"]
        if self.mood:
            parts.append(f"雰囲気: {self.mood}")
        if self.topic_keywords:
            parts.append(f"話題: {', '.join(self.topic_keywords)}")
        if self.active_users:
            parts.append(f"参加者: {', '.join(self.active_users)}")
        return "\n".join(parts)

    def to_dict(self) -> dict:
        """シリアライゼーション用の辞書を返す"""
        return {
            "channel_id": self.channel_id,
            "summary": self.summary,
            "mood": self.mood,
            "topic_keywords": self.topic_keywords,
            "active_users": self.active_users,
            "last_updated": self.last_updated.isoformat(),
            "message_count_since_update": self.message_count_since_update,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ChannelContext":
        """辞書からChannelContextを復元する"""
        last_updated = data.get("last_updated")
        if isinstance(last_updated, str):
            last_updated = datetime.fromisoformat(last_updated)
        elif last_updated is None:
            last_updated = datetime.now(timezone.utc)

        return cls(
            channel_id=data["channel_id"],
            summary=data.get("summary", ""),
            mood=data.get("mood", ""),
            topic_keywords=data.get("topic_keywords", []),
            active_users=data.get("active_users", []),
            last_updated=last_updated,
            message_count_since_update=data.get("message_count_since_update", 0),
        )


class ChannelContextStore:
    """チャンネルコンテキストの永続化ストア"""

    def __init__(self) -> None:
        self._contexts: dict[int, ChannelContext] = {}

    def get_context(self, channel_id: int) -> ChannelContext:
        """チャンネルコンテキストを取得する（なければ新規作成）"""
        if channel_id in self._contexts:
            return self._contexts[channel_id]

        # 永続化先からの読み込みを試行
        ctx = self._load_context(channel_id)
        if ctx is None:
            ctx = ChannelContext(channel_id=channel_id)
        self._contexts[channel_id] = ctx
        return ctx

    def save_context(self, context: ChannelContext) -> None:
        """コンテキストを永続化する"""
        self._contexts[context.channel_id] = context
        storage_type = config.STORAGE_TYPE

        if storage_type == "local":
            self._save_to_local(context)
        elif storage_type == "firestore":
            self._save_to_firestore(context)

    def _load_context(self, channel_id: int) -> ChannelContext | None:
        """永続化先からコンテキストを読み込む"""
        storage_type = config.STORAGE_TYPE

        if storage_type == "local":
            return self._load_from_local(channel_id)
        elif storage_type == "firestore":
            return self._load_from_firestore(channel_id)
        return None

    def _load_from_local(self, channel_id: int) -> ChannelContext | None:
        """ローカルファイルからコンテキストを読み込む"""
        file_path = f"storage/channel_context.{channel_id}.json"
        try:
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return ChannelContext.from_dict(data)
        except Exception as e:
            logger.error(f"チャンネルコンテキスト読み込みエラー: {e}", exc_info=True)
        return None

    def _save_to_local(self, context: ChannelContext) -> None:
        """ローカルファイルにアトミック書き込み"""
        file_path = f"storage/channel_context.{context.channel_id}.json"
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            temp_dir = os.path.dirname(file_path)
            with tempfile.NamedTemporaryFile(
                "w", dir=temp_dir, delete=False, encoding="utf-8", suffix=".tmp"
            ) as tf:
                json.dump(context.to_dict(), tf, ensure_ascii=False, indent=2)
                temp_name = tf.name
            try:
                os.replace(temp_name, file_path)
            except Exception:
                if os.path.exists(temp_name):
                    os.remove(temp_name)
                raise
        except Exception as e:
            logger.error(
                f"チャンネルコンテキストのローカル保存エラー: {e}", exc_info=True
            )

    def _load_from_firestore(self, channel_id: int) -> ChannelContext | None:
        """Firestoreからコンテキストを読み込む"""
        try:
            from utils.firestore_client import get_firestore_client

            db = get_firestore_client()
            doc = (
                db.collection(config.FIRESTORE_COLLECTION_CHANNEL_CONTEXTS)
                .document(str(channel_id))
                .get()
            )
            if doc.exists:  # type: ignore[union-attr]
                data = doc.to_dict()  # type: ignore[union-attr]
                if data is not None:
                    data["channel_id"] = channel_id
                    return ChannelContext.from_dict(data)
        except Exception as e:
            logger.error(
                f"Firestoreからのコンテキスト読み込みエラー: {e}", exc_info=True
            )
        return None

    def _save_to_firestore(self, context: ChannelContext) -> None:
        """Firestoreにコンテキストを保存する"""
        try:
            from utils.firestore_client import get_firestore_client

            db = get_firestore_client()
            db.collection(config.FIRESTORE_COLLECTION_CHANNEL_CONTEXTS).document(
                str(context.channel_id)
            ).set(context.to_dict())
        except Exception as e:
            logger.error(
                f"Firestoreへのコンテキスト保存エラー: {e}", exc_info=True
            )


# シングルトン
_store: ChannelContextStore | None = None


def get_channel_context_store() -> ChannelContextStore:
    """ChannelContextStoreのシングルトンインスタンスを取得する"""
    global _store
    if _store is None:
        _store = ChannelContextStore()
        logger.info(
            f"ChannelContextStore初期化: storage_type={config.STORAGE_TYPE}"
        )
    return _store
