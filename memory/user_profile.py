"""ユーザープロファイル: 交流回数・関係性レベル・直近話題の記録"""

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone

import config
from log_utils.logger import logger


@dataclass
class UserProfile:
    """ユーザーのプロファイル情報"""

    user_id: int
    display_name: str
    interaction_count: int = 0
    mentioned_bot_count: int = 0
    channels_active: list[int] = field(default_factory=list)
    last_interaction: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_topic: list[str] = field(default_factory=list)

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
        """LLM注入用のフォーマット済み文字列を返す"""
        if self.interaction_count == 0:
            return ""
        parts = [f"【{self.display_name}さんについて】"]
        parts.append(f"関係性: {self.familiarity_level}（{self.interaction_count}回のやりとり）")
        if self.last_topic:
            parts.append(f"直近の話題: {', '.join(self.last_topic)}")
        return "\n".join(parts)

    def to_dict(self) -> dict:
        """シリアライゼーション用の辞書を返す"""
        return {
            "user_id": self.user_id,
            "display_name": self.display_name,
            "interaction_count": self.interaction_count,
            "mentioned_bot_count": self.mentioned_bot_count,
            "channels_active": self.channels_active,
            "last_interaction": self.last_interaction.isoformat(),
            "last_topic": self.last_topic,
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
            display_name=data.get("display_name", ""),
            interaction_count=data.get("interaction_count", 0),
            mentioned_bot_count=data.get("mentioned_bot_count", 0),
            channels_active=data.get("channels_active", []),
            last_interaction=last_interaction,
            last_topic=data.get("last_topic", []),
        )


class UserProfileStore:
    """ユーザープロファイルの永続化ストア"""

    def __init__(self) -> None:
        self._profiles: dict[int, UserProfile] = {}

    def get_profile(self, user_id: int, display_name: str = "") -> UserProfile:
        """ユーザープロファイルを取得する（なければ新規作成 or 永続化先から読み込み）"""
        if user_id in self._profiles:
            return self._profiles[user_id]

        # 永続化先からの読み込みを試行
        profile = self._load_profile(user_id)
        if profile is None:
            profile = UserProfile(user_id=user_id, display_name=display_name)
        self._profiles[user_id] = profile
        return profile

    def record_message(self, user_id: int, channel_id: int, display_name: str) -> None:
        """メッセージ受信時にプロファイルを更新する

        Args:
            user_id: DiscordユーザーID
            channel_id: メッセージが投稿されたチャンネルID
            display_name: ユーザーの表示名
        """
        profile = self.get_profile(user_id, display_name)
        profile.interaction_count += 1
        profile.display_name = display_name
        profile.last_interaction = datetime.now(timezone.utc)
        if channel_id not in profile.channels_active:
            profile.channels_active.append(channel_id)

    def record_bot_mention(self, user_id: int) -> None:
        """ボットへのメンション時にカウンタを更新する

        Args:
            user_id: DiscordユーザーID
        """
        if user_id in self._profiles:
            self._profiles[user_id].mentioned_bot_count += 1

    def update_last_topic(self, user_id: int, topic_keywords: list[str]) -> None:
        """応答生成後に直近の話題を更新する

        Args:
            user_id: DiscordユーザーID
            topic_keywords: チャンネルコンテキストから取得した話題キーワード
        """
        if user_id in self._profiles and topic_keywords:
            self._profiles[user_id].last_topic = list(topic_keywords)

    def persist_all(self) -> None:
        """全プロファイルを永続化する（定期タスクから呼ばれる）"""
        storage_type = config.STORAGE_TYPE

        for profile in self._profiles.values():
            if storage_type == "local":
                self._save_to_local(profile)
            elif storage_type == "firestore":
                self._save_to_firestore(profile)

    def _load_profile(self, user_id: int) -> "UserProfile | None":
        """永続化先からプロファイルを読み込む"""
        storage_type = config.STORAGE_TYPE

        if storage_type == "local":
            return self._load_from_local(user_id)
        elif storage_type == "firestore":
            return self._load_from_firestore(user_id)
        return None

    def _load_from_local(self, user_id: int) -> "UserProfile | None":
        """ローカルファイルからプロファイルを読み込む"""
        file_path = f"storage/user_profile.{user_id}.json"
        try:
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return UserProfile.from_dict(data)
        except Exception as e:
            logger.error(f"ユーザープロファイル読み込みエラー: {e}", exc_info=True)
        return None

    def _save_to_local(self, profile: "UserProfile") -> None:
        """ローカルファイルにアトミック書き込み"""
        file_path = f"storage/user_profile.{profile.user_id}.json"
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            temp_dir = os.path.dirname(file_path)
            with tempfile.NamedTemporaryFile(
                "w", dir=temp_dir, delete=False, encoding="utf-8", suffix=".tmp"
            ) as tf:
                json.dump(profile.to_dict(), tf, ensure_ascii=False, indent=2)
                temp_name = tf.name
            try:
                os.replace(temp_name, file_path)
            except Exception:
                if os.path.exists(temp_name):
                    os.remove(temp_name)
                raise
        except Exception as e:
            logger.error(
                f"ユーザープロファイルのローカル保存エラー: {e}", exc_info=True
            )

    def _load_from_firestore(self, user_id: int) -> "UserProfile | None":
        """Firestoreからプロファイルを読み込む"""
        try:
            from utils.firestore_client import get_firestore_client

            db = get_firestore_client()
            doc = (
                db.collection(config.FIRESTORE_COLLECTION_USER_PROFILES)
                .document(str(user_id))
                .get()
            )
            if doc.exists:  # type: ignore[union-attr]
                data = doc.to_dict()  # type: ignore[union-attr]
                if data is not None:
                    data["user_id"] = user_id
                    return UserProfile.from_dict(data)
        except Exception as e:
            logger.error(
                f"Firestoreからのプロファイル読み込みエラー: {e}", exc_info=True
            )
        return None

    def _save_to_firestore(self, profile: "UserProfile") -> None:
        """Firestoreにプロファイルを保存する"""
        try:
            from utils.firestore_client import get_firestore_client

            db = get_firestore_client()
            db.collection(config.FIRESTORE_COLLECTION_USER_PROFILES).document(
                str(profile.user_id)
            ).set(profile.to_dict())
        except Exception as e:
            logger.error(
                f"Firestoreへのプロファイル保存エラー: {e}", exc_info=True
            )


# シングルトン
_store: UserProfileStore | None = None


def get_user_profile_store() -> UserProfileStore:
    """UserProfileStoreのシングルトンインスタンスを取得する"""
    global _store
    if _store is None:
        _store = UserProfileStore()
        logger.info(
            f"UserProfileStore初期化: storage_type={config.STORAGE_TYPE}"
        )
    return _store
