"""ユーザープロファイル: 交流回数・関係性レベル・直近話題の記録"""

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

import config
from log_utils.logger import logger
from memory.errors import StorageLoadError
from memory.sanitize import sanitize_llm_text, sanitize_llm_text_list

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
        # イベントループとワーカースレッド（反省会・定期永続化）から並行アクセスされる
        self._lock = threading.Lock()

    def _mark_dirty(self, guild_id: int, user_id: int) -> None:
        with self._lock:
            self._dirty.add((guild_id, user_id))

    def get_profile(
        self, guild_id: int, user_id: int, display_name: str = ""
    ) -> UserProfile:
        """ユーザープロファイルを取得する（なければ永続化先から読み込み or 新規作成）

        永続化先の読み込みでブロックするため、イベントループからは
        ``asyncio.to_thread`` 経由で呼ぶこと（キャッシュ済みなら即時に返る）。

        Args:
            guild_id: ギルドID
            user_id: DiscordユーザーID
            display_name: 新規作成時の表示名

        Returns:
            プロファイル
        """
        key = (guild_id, user_id)
        with self._lock:
            cached = self._profiles.get(key)
        if cached is not None:
            return cached

        # ロック外で I/O を行い、取得後に先着を優先して登録する
        try:
            profile = self._load_profile(guild_id, user_id)
            if profile is None:
                profile = self._new_profile(guild_id, user_id, display_name)
        except StorageLoadError:
            # 一時的なプロファイルを返すが、キャッシュしない。persist_all は
            # キャッシュにあるものだけを保存するため、既存データは上書きされない
            logger.warning(
                f"プロファイルの読み込みに失敗したため一時プロファイルを使用します: "
                f"guild_id={guild_id}, user_id={user_id}",
                exc_info=True,
            )
            return UserProfile(user_id=user_id, display_name=display_name, guild_id=guild_id)
        with self._lock:
            return self._profiles.setdefault(key, profile)

    def get_cached_profile(self, guild_id: int, user_id: int) -> UserProfile | None:
        """キャッシュ済みのプロファイルを返す（I/O は行わない）"""
        with self._lock:
            return self._profiles.get((guild_id, user_id))

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
        profile = self.get_profile(guild_id, user_id, display_name)
        profile.interaction_count += 1
        profile.display_name = display_name
        profile.last_interaction = datetime.now(timezone.utc)
        if channel_id in profile.channels_active:
            profile.channels_active.remove(channel_id)
        profile.channels_active.append(channel_id)
        limit = config.CHANNELS_ACTIVE_LIMIT
        if len(profile.channels_active) > limit:
            profile.channels_active = profile.channels_active[-limit:]
        self._mark_dirty(guild_id, user_id)

    def record_bot_mention(self, guild_id: int, user_id: int) -> None:
        """ボットへのメンション時にカウンタを更新する

        Args:
            guild_id: ギルドID
            user_id: DiscordユーザーID
        """
        profile = self.get_cached_profile(guild_id, user_id)
        if profile:
            profile.mentioned_bot_count += 1
            self._mark_dirty(guild_id, user_id)

    def update_last_topic(
        self, guild_id: int, user_id: int, topic_keywords: list[str]
    ) -> None:
        """応答生成後に直近の話題を更新する

        Args:
            guild_id: ギルドID
            user_id: DiscordユーザーID
            topic_keywords: チャンネルコンテキストから取得した話題キーワード
        """
        profile = self.get_cached_profile(guild_id, user_id)
        if profile and topic_keywords:
            profile.last_topic = list(topic_keywords)
            self._mark_dirty(guild_id, user_id)

    def update_from_reflection(
        self, guild_id: int, user_id: int, extracted: dict
    ) -> None:
        """反省会LLM抽出結果でUserProfileを更新する

        Args:
            guild_id: 反省会の対象チャンネルが属するギルドID
            user_id: DiscordユーザーID
            extracted: LLMが抽出した辞書（tags, notable_facts, personality_notes 等）
        """
        profile = self.get_cached_profile(guild_id, user_id)
        if not profile:
            return
        for tag in sanitize_llm_text_list(
            extracted.get("tags"), _MAX_TAG_LENGTH, config.USER_PROFILE_TAGS_LIMIT
        ):
            if tag not in profile.tags:
                profile.tags.append(tag)
        profile.tags = profile.tags[-config.USER_PROFILE_TAGS_LIMIT:]
        for fact in sanitize_llm_text_list(
            extracted.get("notable_facts"),
            _MAX_FACT_LENGTH,
            config.USER_PROFILE_FACTS_LIMIT,
        ):
            if fact not in profile.notable_facts:
                profile.notable_facts.append(fact)
        profile.notable_facts = profile.notable_facts[-config.USER_PROFILE_FACTS_LIMIT:]
        self._apply_reflection_scalars(profile, extracted)
        self._mark_dirty(guild_id, user_id)

    def _apply_reflection_scalars(self, profile: UserProfile, extracted: dict) -> None:
        """反省会抽出結果のうち単一値のフィールドを検証してプロファイルに反映する

        Args:
            profile: 更新対象のプロファイル
            extracted: LLMが抽出した辞書
        """
        notes = sanitize_llm_text(extracted.get("personality_notes"), _MAX_NOTE_LENGTH)
        if notes:
            profile.personality_notes = notes
        summary = sanitize_llm_text(
            extracted.get("last_conversation_summary"), _MAX_NOTE_LENGTH
        )
        if summary:
            profile.last_conversation_summary = summary
        tone = sanitize_llm_text(extracted.get("preferred_tone"), _MAX_SHORT_LENGTH)
        if tone in _ALLOWED_TONES:
            profile.preferred_tone = tone
        emotion = sanitize_llm_text(
            extracted.get("emotional_state_last"), _MAX_SHORT_LENGTH
        )
        if emotion:
            profile.emotional_state_last = emotion
        nickname = sanitize_llm_text(extracted.get("nickname"), _MAX_NICKNAME_LENGTH)
        if nickname:
            self.update_nickname(profile.guild_id, profile.user_id, nickname)

    def update_nickname(self, guild_id: int, user_id: int, nickname: str) -> None:
        """ユーザーのニックネームを更新する

        Args:
            guild_id: ギルドID
            user_id: DiscordユーザーID
            nickname: 設定するニックネーム
        """
        profile = self.get_cached_profile(guild_id, user_id)
        if profile:
            profile.nickname = nickname
            self._mark_dirty(guild_id, user_id)
            logger.info(
                f"ニックネーム更新: guild_id={guild_id}, user_id={user_id}, "
                f"nickname={nickname!r}"
            )

    def persist_all(self) -> None:
        """変更のあったプロファイルだけを永続化する（定期タスク・反省会からワーカースレッドで呼ばれる）

        書き込みに失敗したプロファイルは次回の persist_all で再試行する。
        """
        with self._lock:
            # キャッシュにないキー（読み込み失敗中の一時プロファイル）は保存しない
            dirty, self._dirty = self._dirty, set()
            snapshot = [(key, self._profiles[key]) for key in dirty if key in self._profiles]
        failed = {key for key, profile in snapshot if not self._save_profile(profile)}
        if failed:
            with self._lock:
                self._dirty |= failed
        if snapshot:
            logger.debug(
                f"ユーザープロファイル永続化: {len(snapshot) - len(failed)}/{len(snapshot)}件"
            )

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
            return self._load_from_local(f"storage/user_profile.{user_id}.json", 0, user_id)
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


def _doc_id(guild_id: int, user_id: int) -> str:
    """ギルド単位プロファイルの Firestore ドキュメントID"""
    return f"{guild_id}_{user_id}"


def _local_path(guild_id: int, user_id: int) -> str:
    """ギルド単位プロファイルのローカル保存パス"""
    return f"storage/user_profile.{guild_id}.{user_id}.json"


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
