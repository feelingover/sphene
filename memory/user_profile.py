"""ユーザープロファイル: 交流回数・関係性レベル・直近話題の記録"""

import json
import os
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

import config
from log_utils.logger import logger
from memory.backoff import new_storage_load_backoff
from memory.errors import StorageLoadError, log_storage_load_failure
from memory.sanitize import sanitize_llm_text, sanitize_llm_text_list
from utils.file_utils import local_storage_path
from utils.keyed_lock import KeyedLock

# 反省会LLMの抽出値はプロンプトへ再注入されるため、フィールドごとに長さを制限する
_MAX_NICKNAME_LENGTH = 32
_MAX_TAG_LENGTH = 30
_MAX_FACT_LENGTH = 100
_MAX_NOTE_LENGTH = 200
_MAX_SHORT_LENGTH = 30
_ALLOWED_TONES = frozenset({"カジュアル", "フォーマル"})


@dataclass
class UserProfile:
    """ユーザーのプロファイル情報"""

    user_id: int
    display_name: str
    # プロファイルはギルド単位で分離する（0 はギルド未指定の旧形式）
    guild_id: int = 0
    interaction_count: int = 0
    mentioned_bot_count: int = 0
    channels_active: list[int] = field(default_factory=list)
    last_interaction: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_topic: list[str] = field(default_factory=list)

    # 追加フィールド (Phase 3B)
    schema_version: int = 1
    tags: list[str] = field(default_factory=list)
    personality_notes: str = ""
    last_conversation_summary: str = ""
    preferred_tone: str | None = None
    notable_facts: list[str] = field(default_factory=list)
    emotional_state_last: str | None = None
    nickname: str | None = None

    @property
    def familiarity_level(self) -> str:
        """interaction_count の閾値から関係性レベルを自動算出する"""
        if self.interaction_count < config.FAMILIARITY_THRESHOLD_ACQUAINTANCE:
            return "stranger"
        elif self.interaction_count < config.FAMILIARITY_THRESHOLD_REGULAR:
            return "acquaintance"
        elif self.interaction_count < config.FAMILIARITY_THRESHOLD_CLOSE:
            return "regular"
        return "close"

    def format_for_injection(self) -> str:
        """LLM注入用のフォーマット済み文字列を返す（後方互換性のために残す）"""
        return "\n\n".join(filter(None, [
            self.format_for_familiarity(),
            self.format_for_context(),
            self.format_for_persona(),
        ]))

    def format_for_familiarity(self) -> str:
        """関係性・基本情報の注入用"""
        if self.interaction_count == 0:
            return ""
        name = self.nickname or self.display_name
        parts = [f"【{name}さんについて】"]
        parts.append(f"関係性: {self.familiarity_level}（{self.interaction_count}回のやりとり）")
        return "\n".join(parts)

    def format_for_context(self) -> str:
        """会話文脈（前回要約・直近話題）の注入用"""
        parts = []
        if self.last_conversation_summary:
            parts.append(f"前回の会話要約: {self.last_conversation_summary}")
        if self.last_topic:
            parts.append(f"直近の話題: {', '.join(self.last_topic)}")
        return "\n".join(parts)

    def format_for_persona(self) -> str:
        """ユーザー人物像（tags・notable_facts・personality_notes）の注入用"""
        parts = []
        if self.tags:
            parts.append(f"タグ: {', '.join(self.tags)}")
        if self.notable_facts:
            parts.append("記憶事実:\n" + "\n".join(f"- {f}" for f in self.notable_facts))
        if self.personality_notes:
            parts.append(f"性格メモ: {self.personality_notes}")
        if self.preferred_tone:
            parts.append(f"好みのトーン: {self.preferred_tone}")
        if self.emotional_state_last:
            parts.append(f"直近の感情状態: {self.emotional_state_last}")
        return "\n".join(parts)

    def snapshot(self) -> "UserProfile":
        """リストフィールドまで複製したコピーを返す（保存・読み取り時のスナップショット用）"""
        return replace(
            self,
            channels_active=list(self.channels_active),
            last_topic=list(self.last_topic),
            tags=list(self.tags),
            notable_facts=list(self.notable_facts),
        )

    def to_dict(self) -> dict:
        """シリアライゼーション用の辞書を返す"""
        return {
            "user_id": self.user_id,
            "guild_id": self.guild_id,
            "display_name": self.display_name,
            "interaction_count": self.interaction_count,
            "mentioned_bot_count": self.mentioned_bot_count,
            "channels_active": self.channels_active,
            "last_interaction": self.last_interaction.isoformat(),
            "last_topic": self.last_topic,
            "schema_version": self.schema_version,
            "tags": self.tags,
            "personality_notes": self.personality_notes,
            "last_conversation_summary": self.last_conversation_summary,
            "preferred_tone": self.preferred_tone,
            "notable_facts": self.notable_facts,
            "emotional_state_last": self.emotional_state_last,
            "nickname": self.nickname,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UserProfile":
        """辞書からUserProfileを復元する"""
        last_interaction = data.get("last_interaction")
        if isinstance(last_interaction, str):
            last_interaction = datetime.fromisoformat(last_interaction)
        elif last_interaction is None:
            last_interaction = datetime.now(timezone.utc)

        return cls(
            user_id=data["user_id"],
            guild_id=data.get("guild_id", 0),
            display_name=data.get("display_name", ""),
            interaction_count=data.get("interaction_count", 0),
            mentioned_bot_count=data.get("mentioned_bot_count", 0),
            channels_active=data.get("channels_active", []),
            last_interaction=last_interaction,
            last_topic=data.get("last_topic", []),
            schema_version=data.get("schema_version", 1),
            tags=data.get("tags", []),
            personality_notes=data.get("personality_notes", ""),
            last_conversation_summary=data.get("last_conversation_summary", ""),
            preferred_tone=data.get("preferred_tone"),
            notable_facts=data.get("notable_facts", []),
            emotional_state_last=data.get("emotional_state_last"),
            nickname=data.get("nickname"),
        )


ProfileKey = tuple[int, int]
"""プロファイルのキー: (guild_id, user_id)"""


class UserProfileStore:
    """ユーザープロファイルの永続化ストア

    プロファイルは (guild_id, user_id) 単位で保持する。あるギルドで抽出した
    事実や性格メモが、別ギルドでの応答に注入されないようにするため。
    """

    def __init__(self) -> None:
        self._profiles: dict[ProfileKey, UserProfile] = {}
        # 永続化先と差分があるプロファイル（persist_all はここに含まれるものだけ書き込む）
        self._dirty: set[ProfileKey] = set()
        # 読み込みに失敗したプロファイルの再読み込み間隔（ロック内で操作する）
        self._load_backoff = new_storage_load_backoff()
        # イベントループとワーカースレッド（反省会・定期永続化）から並行アクセスされる
        self._lock = threading.Lock()
        # プロファイル単位の保存ロック（スナップショット取得から書き込み完了まで保持する）。
        # 並行した persist_all で古い内容の書き込みが後勝ちするのを防ぐ。
        # 取得順は必ず保存ロック → self._lock とする。
        # ロックは _profiles と同じだけ増える。_profiles に追い出し処理を入れるときは一緒に掃除する。
        self._save_locks: KeyedLock[ProfileKey] = KeyedLock()

    def get_profile(
        self, guild_id: int, user_id: int, display_name: str = ""
    ) -> UserProfile:
        """ユーザープロファイルを取得する（なければ永続化先から読み込み or 新規作成）

        永続化先の読み込みでブロックするため、イベントループからは
        ``asyncio.to_thread`` 経由で呼ぶこと（キャッシュ済みなら即時に返る）。

        戻り値は ``self._lock`` 内で取ったスナップショットのため、ワーカースレッドでの
        書き換えと並行しても、ある時点の一貫した状態を読める。スナップショットを
        書き換えてもキャッシュには反映されない（更新は ``record_message`` 等を使う）。

        Args:
            guild_id: ギルドID
            user_id: DiscordユーザーID
            display_name: 新規作成時の表示名

        Returns:
            プロファイルのスナップショット
        """
        profile = self._get_or_load_profile(guild_id, user_id, display_name)
        with self._lock:
            return profile.snapshot()

    def get_cached_profile(self, guild_id: int, user_id: int) -> UserProfile | None:
        """キャッシュ済みプロファイルのスナップショットを返す（I/O は行わない）"""
        with self._lock:
            profile = self._profiles.get((guild_id, user_id))
            return profile.snapshot() if profile is not None else None

    def _get_or_load_profile(
        self, guild_id: int, user_id: int, display_name: str
    ) -> UserProfile:
        """キャッシュ上の生のプロファイルを返す（なければ読み込み or 新規作成）

        戻り値の読み書きは必ず ``self._lock`` 内で行うこと。

        Args:
            guild_id: ギルドID
            user_id: DiscordユーザーID
            display_name: 新規作成時の表示名

        Returns:
            キャッシュ上のプロファイル（読み込み失敗時は未キャッシュの一時プロファイル）
        """
        key = (guild_id, user_id)
        with self._lock:
            cached = self._profiles.get(key)
            blocked = cached is None and self._load_backoff.is_blocked(key)
        if cached is not None:
            return cached
        if blocked:
            # 読み込み失敗直後は I/O を繰り返さず、一時プロファイルを返す
            return UserProfile(user_id=user_id, display_name=display_name, guild_id=guild_id)

        # ロック外で I/O を行い、取得後に先着を優先して登録する
        try:
            profile = self._load_profile(guild_id, user_id)
            if profile is None:
                profile = self._new_profile(guild_id, user_id, display_name)
        except StorageLoadError:
            # 一時的なプロファイルを返すが、キャッシュしない。persist_all は
            # キャッシュにあるものだけを保存するため、既存データは上書きされない
            with self._lock:
                failures = self._load_backoff.record_failure(key)
            log_storage_load_failure(
                f"プロファイルの読み込みに失敗したため一時プロファイルを使用します: "
                f"guild_id={guild_id}, user_id={user_id}",
                failures,
            )
            return UserProfile(user_id=user_id, display_name=display_name, guild_id=guild_id)
        with self._lock:
            self._load_backoff.reset(key)
            return self._profiles.setdefault(key, profile)

    def record_message(
        self, guild_id: int, user_id: int, channel_id: int, display_name: str
    ) -> None:
        """メッセージ受信時にプロファイルを更新する

        Args:
            guild_id: ギルドID
            user_id: DiscordユーザーID
            channel_id: メッセージが投稿されたチャンネルID
            display_name: ユーザーの表示名
        """
        # 読み込みは I/O を伴うことがあるのでロック外で呼ぶ
        profile = self._get_or_load_profile(guild_id, user_id, display_name)
        with self._lock:
            profile.interaction_count += 1
            profile.display_name = display_name
            profile.last_interaction = datetime.now(timezone.utc)
            channels = [c for c in profile.channels_active if c != channel_id]
            channels.append(channel_id)
            profile.channels_active = channels[-config.CHANNELS_ACTIVE_LIMIT:]
            self._dirty.add((guild_id, user_id))

    def record_bot_mention(self, guild_id: int, user_id: int) -> None:
        """ボットへのメンション時にカウンタを更新する

        Args:
            guild_id: ギルドID
            user_id: DiscordユーザーID
        """
        key = (guild_id, user_id)
        with self._lock:
            profile = self._profiles.get(key)
            if profile:
                profile.mentioned_bot_count += 1
                self._dirty.add(key)

    def update_last_topic(
        self, guild_id: int, user_id: int, topic_keywords: list[str]
    ) -> None:
        """応答生成後に直近の話題を更新する

        Args:
            guild_id: ギルドID
            user_id: DiscordユーザーID
            topic_keywords: チャンネルコンテキストから取得した話題キーワード
        """
        if not topic_keywords:
            return
        key = (guild_id, user_id)
        with self._lock:
            profile = self._profiles.get(key)
            if profile:
                profile.last_topic = list(topic_keywords)
                self._dirty.add(key)

    def update_from_reflection(
        self, guild_id: int, user_id: int, extracted: dict
    ) -> None:
        """反省会LLM抽出結果でUserProfileを更新する

        Args:
            guild_id: 反省会の対象チャンネルが属するギルドID
            user_id: DiscordユーザーID
            extracted: LLMが抽出した辞書（tags, notable_facts, personality_notes 等）
        """
        # 検証・正規化はロック外で済ませ、反映だけをロック内で行う
        tags = sanitize_llm_text_list(
            extracted.get("tags"), _MAX_TAG_LENGTH, config.USER_PROFILE_TAGS_LIMIT
        )
        facts = sanitize_llm_text_list(
            extracted.get("notable_facts"),
            _MAX_FACT_LENGTH,
            config.USER_PROFILE_FACTS_LIMIT,
        )
        scalars = _sanitize_reflection_scalars(extracted)
        key = (guild_id, user_id)
        with self._lock:
            profile = self._profiles.get(key)
            if not profile:
                return
            profile.tags = _merge_unique(
                profile.tags, tags, config.USER_PROFILE_TAGS_LIMIT
            )
            profile.notable_facts = _merge_unique(
                profile.notable_facts, facts, config.USER_PROFILE_FACTS_LIMIT
            )
            for name, value in scalars.items():
                setattr(profile, name, value)
            self._dirty.add(key)
        if "nickname" in scalars:
            _log_nickname_update(guild_id, user_id, scalars["nickname"])

    def update_nickname(self, guild_id: int, user_id: int, nickname: str) -> None:
        """ユーザーのニックネームを更新する

        Args:
            guild_id: ギルドID
            user_id: DiscordユーザーID
            nickname: 設定するニックネーム
        """
        key = (guild_id, user_id)
        with self._lock:
            profile = self._profiles.get(key)
            if not profile:
                return
            profile.nickname = nickname
            self._dirty.add(key)
        _log_nickname_update(guild_id, user_id, nickname)

    def persist_all(self) -> None:
        """変更のあったプロファイルだけを永続化する（定期タスク・反省会からワーカースレッドで呼ばれる）

        書き込みに失敗したプロファイルは次回の persist_all で再試行する。
        """
        with self._lock:
            targets = list(self._dirty)
        results = [self._persist_profile_serialized(key) for key in targets]
        attempted = [ok for ok in results if ok is not None]
        if attempted:
            logger.debug(
                f"ユーザープロファイル永続化: {sum(attempted)}/{len(attempted)}件"
            )

    def _persist_profile_serialized(self, key: ProfileKey) -> bool | None:
        """プロファイルの保存ロックを保持したまま dirty を取り出し、書き込む

        同じプロファイルの保存は直列化されるため、古い内容による上書きが起きない。

        Args:
            key: (guild_id, user_id)

        Returns:
            書き込みの成否。書き込みを行わなかった場合は None
        """
        with self._save_locks.get(key):
            with self._lock:
                # 待機中に別スレッドが保存を済ませていれば何もしない
                if key not in self._dirty:
                    return None
                self._dirty.discard(key)
                # キャッシュにないキー（読み込み失敗中の一時プロファイル）は保存しない
                profile = self._profiles.get(key)
                # 書き換えと排他にするため、スナップショットはロック内で取る
                snapshot = profile.snapshot() if profile is not None else None
            if snapshot is None:
                return None

            if self._save_profile(snapshot):
                return True
            with self._lock:
                self._dirty.add(key)
            return False

    def _save_profile(self, profile: UserProfile) -> bool:
        """設定された永続化先にプロファイルを書き込む

        Returns:
            書き込みに成功した（または永続化しない設定の）場合True
        """
        storage_type = config.STORAGE_TYPE
        if storage_type == "local":
            return self._save_to_local(profile)
        if storage_type == "firestore":
            return self._save_to_firestore(profile)
        return True

    def _new_profile(
        self, guild_id: int, user_id: int, display_name: str
    ) -> UserProfile:
        """新規プロファイルを作成する

        ギルド分離前の旧プロファイル（user_id 単位）がある場合は、交流回数などの
        カウンタだけを引き継ぐ。事実・性格メモ等は他ギルド由来の可能性があるため
        引き継がない。

        Args:
            guild_id: ギルドID
            user_id: DiscordユーザーID
            display_name: 表示名

        Returns:
            新規プロファイル
        """
        profile = UserProfile(user_id=user_id, display_name=display_name, guild_id=guild_id)
        legacy = self._load_legacy_profile(user_id)
        if legacy is not None:
            profile.interaction_count = legacy.interaction_count
            profile.mentioned_bot_count = legacy.mentioned_bot_count
            profile.display_name = display_name or legacy.display_name
            logger.info(
                f"旧プロファイルからカウンタを引き継ぎ: guild_id={guild_id}, user_id={user_id}"
            )
        return profile

    def _load_profile(self, guild_id: int, user_id: int) -> "UserProfile | None":
        """永続化先からギルド単位のプロファイルを読み込む"""
        storage_type = config.STORAGE_TYPE
        if storage_type == "local":
            return self._load_from_local(_local_path(guild_id, user_id), guild_id, user_id)
        elif storage_type == "firestore":
            return self._load_from_firestore(_doc_id(guild_id, user_id), guild_id, user_id)
        return None

    def _load_legacy_profile(self, user_id: int) -> "UserProfile | None":
        """ギルド分離前の旧形式（user_id 単位）のプロファイルを読み込む"""
        storage_type = config.STORAGE_TYPE
        if storage_type == "local":
            return self._load_from_local(local_storage_path(f"user_profile.{user_id}.json"), 0, user_id)
        elif storage_type == "firestore":
            return self._load_from_firestore(str(user_id), 0, user_id)
        return None

    def _load_from_local(
        self, file_path: str, guild_id: int, user_id: int
    ) -> "UserProfile | None":
        """ローカルファイルからプロファイルを読み込む"""
        try:
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["user_id"] = user_id
                data["guild_id"] = guild_id
                return UserProfile.from_dict(data)
        except Exception as e:
            raise StorageLoadError(
                f"ユーザープロファイルのローカル読み込みに失敗: {file_path}"
            ) from e
        return None

    def _save_to_local(self, profile: "UserProfile") -> bool:
        """ローカルファイルにアトミック書き込み"""
        from utils.file_utils import atomic_write_json

        file_path = _local_path(profile.guild_id, profile.user_id)
        try:
            atomic_write_json(file_path, profile.to_dict())
            return True
        except Exception as e:
            logger.error(
                f"ユーザープロファイルのローカル保存エラー: {e}", exc_info=True
            )
            return False

    def _load_from_firestore(
        self, doc_id: str, guild_id: int, user_id: int
    ) -> "UserProfile | None":
        """Firestoreからプロファイルを読み込む"""
        try:
            from utils.firestore_client import get_firestore_client

            db = get_firestore_client()
            doc = (
                db.collection(config.FIRESTORE_COLLECTION_USER_PROFILES)
                .document(doc_id)
                .get()
            )
            if doc.exists:  # type: ignore[union-attr]
                data = doc.to_dict()  # type: ignore[union-attr]
                if data is not None:
                    data["user_id"] = user_id
                    data["guild_id"] = guild_id
                    return UserProfile.from_dict(data)
        except Exception as e:
            raise StorageLoadError(
                f"Firestoreからのプロファイル読み込みに失敗: doc_id={doc_id}"
            ) from e
        return None

    def _save_to_firestore(self, profile: "UserProfile") -> bool:
        """Firestoreにプロファイルを保存する"""
        try:
            from utils.firestore_client import get_firestore_client

            db = get_firestore_client()
            db.collection(config.FIRESTORE_COLLECTION_USER_PROFILES).document(
                _doc_id(profile.guild_id, profile.user_id)
            ).set(profile.to_dict())
            return True
        except Exception as e:
            logger.error(
                f"Firestoreへのプロファイル保存エラー: {e}", exc_info=True
            )
            return False


def _merge_unique(current: list[str], additions: list[str], limit: int) -> list[str]:
    """重複を除いて追記し、末尾 limit 件に切り詰めた新しいリストを返す"""
    merged = list(current)
    for item in additions:
        if item not in merged:
            merged.append(item)
    return merged[-limit:]


def _sanitize_reflection_scalars(extracted: dict) -> dict[str, str]:
    """反省会抽出結果のうち単一値のフィールドを検証し、反映すべき値だけを返す

    Args:
        extracted: LLMが抽出した辞書

    Returns:
        {UserProfile のフィールド名: 値}（無効・空の値は含まない）
    """
    values: dict[str, str | None] = {
        "personality_notes": sanitize_llm_text(
            extracted.get("personality_notes"), _MAX_NOTE_LENGTH
        ),
        "last_conversation_summary": sanitize_llm_text(
            extracted.get("last_conversation_summary"), _MAX_NOTE_LENGTH
        ),
        "emotional_state_last": sanitize_llm_text(
            extracted.get("emotional_state_last"), _MAX_SHORT_LENGTH
        ),
        "nickname": sanitize_llm_text(extracted.get("nickname"), _MAX_NICKNAME_LENGTH),
    }
    result = {name: value for name, value in values.items() if value is not None}
    tone = sanitize_llm_text(extracted.get("preferred_tone"), _MAX_SHORT_LENGTH)
    if tone is not None and tone in _ALLOWED_TONES:
        result["preferred_tone"] = tone
    return result


def _log_nickname_update(guild_id: int, user_id: int, nickname: str) -> None:
    """ニックネーム更新をログに残す"""
    logger.info(
        f"ニックネーム更新: guild_id={guild_id}, user_id={user_id}, "
        f"nickname={nickname!r}"
    )


def _doc_id(guild_id: int, user_id: int) -> str:
    """ギルド単位プロファイルの Firestore ドキュメントID"""
    return f"{guild_id}_{user_id}"


def _local_path(guild_id: int, user_id: int) -> str:
    """ギルド単位プロファイルのローカル保存パス"""
    return local_storage_path(f"user_profile.{guild_id}.{user_id}.json")


# シングルトン
_store: UserProfileStore | None = None
_store_lock = threading.Lock()


def get_user_profile_store() -> UserProfileStore:
    """UserProfileStoreのシングルトンインスタンスを取得する"""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = UserProfileStore()
                logger.info(
                    f"UserProfileStore初期化: storage_type={config.STORAGE_TYPE}"
                )
    return _store
