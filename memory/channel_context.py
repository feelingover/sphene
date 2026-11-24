"""チャンネルコンテキスト: ローリング要約によるチャンネルの雰囲気把握"""

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

import config
from log_utils.logger import logger
from memory.backoff import new_storage_load_backoff
from memory.cache_eviction import LruTracker
from memory.errors import StorageLoadError, log_storage_load_failure
from utils.file_utils import local_storage_path


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
    # 永続化先の読み込みに失敗した一時コンテキストなら True（シリアライズしない）。
    # 保存すると既存の要約を上書きしてしまうため、save_context はこれを拒否する
    load_failed: bool = field(default=False, compare=False, repr=False)
    # 永続化先と差分があれば True（persist_all は dirty なものだけ書き込む）
    dirty: bool = field(default=False, compare=False, repr=False)

    def increment_message_count(self) -> None:
        """メッセージカウンタをインクリメントする"""
        self.message_count_since_update += 1
        self.dirty = True

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
        # 読み込みに失敗したチャンネルの再読み込み間隔（ロック内で操作する）
        self._load_backoff = new_storage_load_backoff()
        # イベントループとワーカースレッドから並行アクセスされる
        self._lock = threading.Lock()
        # キャッシュ上限を超えたときの追い出し順（ロック内で操作する）
        self._lru: LruTracker[int] = LruTracker()
        # 保存処理中のチャンネルと並行数（書き込み完了前に追い出して古い内容を読み直さないため）
        self._saving: dict[int, int] = {}

    def get_all_contexts(self) -> dict[int, ChannelContext]:
        """全コンテキストのコピーを返す（スレッドセーフ）"""
        with self._lock:
            return dict(self._contexts)

    def get_context(self, channel_id: int) -> ChannelContext:
        """チャンネルコンテキストを取得する（なければ永続化先から読み込み or 新規作成）

        永続化先の読み込みでブロックするため、イベントループからは
        ``asyncio.to_thread`` 経由で呼ぶこと（キャッシュ済みなら即時に返る）。

        Args:
            channel_id: チャンネルID

        Returns:
            チャンネルコンテキスト
        """
        with self._lock:
            cached = self._contexts.get(channel_id)
            if cached is not None:
                self._lru.touch(channel_id)
            blocked = cached is None and self._load_backoff.is_blocked(channel_id)
        if cached is not None:
            return cached
        if blocked:
            # 読み込み失敗直後は I/O を繰り返さず、一時コンテキストを返す
            return ChannelContext(channel_id=channel_id, load_failed=True)

        # ロック外で I/O を行い、取得後に先着を優先して登録する
        try:
            ctx = self._load_context(channel_id)
        except StorageLoadError:
            # 一時コンテキストを返すが、キャッシュしない（バックオフ明けに再読み込みする）
            with self._lock:
                failures = self._load_backoff.record_failure(channel_id)
            log_storage_load_failure(
                f"チャンネルコンテキストの読み込みに失敗したため一時コンテキストを使用します: "
                f"channel_id={channel_id}",
                failures,
            )
            return ChannelContext(channel_id=channel_id, load_failed=True)
        if ctx is None:
            ctx = ChannelContext(channel_id=channel_id)
        with self._lock:
            self._load_backoff.reset(channel_id)
            self._lru.touch(channel_id)
            return self._contexts.setdefault(channel_id, ctx)

    def save_context(self, context: ChannelContext) -> bool:
        """コンテキストを永続化する（I/Oを伴うためワーカースレッドで呼ぶこと）

        読み込みに失敗した一時コンテキストは、既存の要約を上書きしないよう保存しない。

        Returns:
            保存に成功したら True（保存を見送った・失敗した場合は False）
        """
        if context.load_failed:
            logger.warning(
                f"読み込みに失敗したチャンネルコンテキストのため保存を見送りました: "
                f"channel_id={context.channel_id}"
            )
            return False
        channel_id = context.channel_id
        with self._lock:
            self._contexts[channel_id] = context
            self._lru.touch(channel_id)
            self._saving[channel_id] = self._saving.get(channel_id, 0) + 1
        try:
            return self._write_context(context)
        finally:
            with self._lock:
                self._finish_saving(channel_id)

    def _write_context(self, context: ChannelContext) -> bool:
        """dirty を落としてから永続化先へ書き込む（失敗時は dirty に戻す）"""
        # 書き込み前に落とすことで、書き込み中の更新を取りこぼさない（失敗時は戻す）
        context.dirty = False
        storage_type = config.STORAGE_TYPE

        saved = False
        if storage_type == "local":
            saved = self._save_to_local(context)
        elif storage_type == "firestore":
            saved = self._save_to_firestore(context)
        if not saved:
            context.dirty = True
        return saved

    def _finish_saving(self, channel_id: int) -> None:
        """保存中カウントを減らす（self._lock 内で呼ぶ）"""
        remaining = self._saving.get(channel_id, 0) - 1
        if remaining > 0:
            self._saving[channel_id] = remaining
        else:
            self._saving.pop(channel_id, None)
        self._lru.touch(channel_id)

    def prune(self) -> int:
        """キャッシュ上限を超えた分を、最終アクセスの古い順に追い出す（定期タスクから呼ぶ）

        未保存の変更（dirty）や要約待ちのメッセージカウントがあるもの、保存中のもの、
        最近アクセスされたものは追い出さない。追い出したコンテキストは次回の
        ``get_context`` で永続化先から読み直される。

        Returns:
            追い出したコンテキスト数
        """
        max_entries = config.CHANNEL_CONTEXT_CACHE_MAX_ENTRIES
        with self._lock:
            self._load_backoff.prune()
            candidates = self._lru.eviction_candidates(
                max_entries, config.MEMORY_CACHE_MIN_IDLE_SECONDS, self._is_pinned
            )
            for channel_id in candidates:
                self._contexts.pop(channel_id, None)
                self._lru.forget(channel_id)
        if candidates:
            logger.debug(
                f"チャンネルコンテキストをキャッシュから追い出しました: {len(candidates)}件 "
                f"(上限={max_entries})"
            )
        return len(candidates)

    def _is_pinned(self, channel_id: int) -> bool:
        """追い出してはいけないコンテキストか（self._lock 内で呼ぶ）"""
        if channel_id in self._saving:
            return True
        ctx = self._contexts.get(channel_id)
        # 要約待ちのカウントは時間ベース要約（get_all_contexts の走査）で消化させる
        return ctx is not None and (ctx.dirty or ctx.message_count_since_update > 0)

    def persist_all(self) -> int:
        """未保存の変更があるコンテキストだけを永続化する（終了時用）

        要約間のメッセージカウンタなど、未保存の状態を失わないために使う。
        1チャンネルの書き込み失敗で他チャンネルの保存を止めない。

        Returns:
            保存に失敗したコンテキスト数
        """
        failed = 0
        for context in self.get_all_contexts().values():
            if not context.dirty:
                continue
            try:
                saved = self.save_context(context)
            except Exception as e:
                saved = False
                logger.error(
                    f"チャンネルコンテキストの永続化に失敗しました: "
                    f"channel_id={context.channel_id}, error={str(e)}",
                    exc_info=True,
                )
            if not saved:
                failed += 1
        if failed:
            logger.warning(f"チャンネルコンテキストの永続化に失敗: {failed}件")
        return failed

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
        file_path = local_storage_path(f"channel_context.{channel_id}.json")
        try:
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return ChannelContext.from_dict(data)
        except Exception as e:
            raise StorageLoadError(
                f"チャンネルコンテキストのローカル読み込みに失敗: {file_path}"
            ) from e
        return None

    def _save_to_local(self, context: ChannelContext) -> bool:
        """ローカルファイルにアトミック書き込み（成功したら True）"""
        from utils.file_utils import atomic_write_json

        file_path = local_storage_path(f"channel_context.{context.channel_id}.json")
        try:
            atomic_write_json(file_path, context.to_dict())
            return True
        except Exception as e:
            logger.error(
                f"チャンネルコンテキストのローカル保存エラー: {e}", exc_info=True
            )
            return False

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
            raise StorageLoadError(
                f"Firestoreからのコンテキスト読み込みに失敗: channel_id={channel_id}"
            ) from e
        return None

    def _save_to_firestore(self, context: ChannelContext) -> bool:
        """Firestoreにコンテキストを保存する（成功したら True）"""
        try:
            from utils.firestore_client import get_firestore_client

            db = get_firestore_client()
            db.collection(config.FIRESTORE_COLLECTION_CHANNEL_CONTEXTS).document(
                str(context.channel_id)
            ).set(context.to_dict())
            return True
        except Exception as e:
            logger.error(
                f"Firestoreへのコンテキスト保存エラー: {e}", exc_info=True
            )
            return False


# シングルトン
_store: ChannelContextStore | None = None
_store_lock = threading.Lock()


def get_channel_context_store() -> ChannelContextStore:
    """ChannelContextStoreのシングルトンインスタンスを取得する"""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = ChannelContextStore()
                logger.info(
                    f"ChannelContextStore初期化: storage_type={config.STORAGE_TYPE}"
                )
    return _store
