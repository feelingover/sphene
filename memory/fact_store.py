"""ファクトストア: LLM抽出ファクトのキーワード検索・永続化"""

import json
import math
import os
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import config
from log_utils.logger import logger

# ひらがなストップワード（形態素解析なしの簡易除去）
_HIRAGANA_STOPWORDS: frozenset[str] = frozenset({
    "は", "が", "を", "に", "で", "と", "の", "も", "か", "な",
    "て", "た", "し", "い", "う", "え", "お", "ん", "ね", "よ",
    "れ", "ら", "り", "る", "す", "く", "き", "け", "こ", "さ",
    "あ", "わ", "や", "ゆ", "じ", "だ", "ど",
    "から", "まで", "より", "ので", "ても", "けど", "けれど",
    "という", "って", "ってる", "している", "した", "します",
    "この", "その", "あの", "どの", "これ", "それ", "あれ",
    "ここ", "そこ", "あそこ", "こと", "もの", "ため",
})


@dataclass
class Fact:
    """抽出されたファクトのデータクラス"""

    fact_id: str
    channel_id: int
    content: str
    keywords: list[str]
    source_user_ids: list[int]
    created_at: datetime
    shareable: bool = False

    def decay_factor(self, half_life_days: int) -> float:
        """経過日数から指数減衰係数を返す（半減期でスコアが0.5になる）"""
        now = datetime.now(timezone.utc)
        created = self.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        elapsed_days = (now - created).total_seconds() / 86400
        return math.pow(0.5, elapsed_days / half_life_days)

    def to_dict(self) -> dict:
        """シリアライゼーション用の辞書を返す"""
        return {
            "fact_id": self.fact_id,
            "channel_id": self.channel_id,
            "content": self.content,
            "keywords": self.keywords,
            "source_user_ids": self.source_user_ids,
            "created_at": self.created_at.isoformat(),
            "shareable": self.shareable,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Fact":
        """辞書からFactを復元する"""
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif created_at is None:
            created_at = datetime.now(timezone.utc)

        return cls(
            fact_id=data.get("fact_id", str(uuid.uuid4())),
            channel_id=data["channel_id"],
            content=data.get("content", ""),
            keywords=data.get("keywords", []),
            source_user_ids=data.get("source_user_ids", []),
            created_at=created_at,
            shareable=data.get("shareable", False),
        )


def _jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    """2つの集合のJaccard類似度を返す"""
    if not set_a and not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    if union == 0:
        return 0.0
    return intersection / union


def _extract_keywords(text: str) -> list[str]:
    """テキストからキーワードを抽出する（スペース/句読点区切り + 短文字除去 + ストップワード除去）"""
    # スペース・句読点・括弧などで分割
    tokens = re.split(r'[\s、。！？!?・「」『』【】（）(),.]+', text)
    result = []
    for token in tokens:
        token = token.strip()
        # 1文字以下は除去
        if len(token) <= 1:
            continue
        # ひらがなのみのトークンでストップワードなら除去
        if token in _HIRAGANA_STOPWORDS:
            continue
        result.append(token)
    return result


class FactStore:
    """チャンネルごとのファクト管理ストア"""

    def __init__(self) -> None:
        self._facts: dict[int, list[Fact]] = {}
        self._loaded_channels: set[int] = set()
        self._lock = threading.Lock()

    def add_fact(self, fact: Fact) -> None:
        """ファクトを追加する。上限超過時はdecay_factor最小のものを削除"""
        self._load_channel(fact.channel_id)
        with self._lock:
            facts = self._facts.setdefault(fact.channel_id, [])
            facts.append(fact)

            max_facts = config.FACT_STORE_MAX_FACTS_PER_CHANNEL
            if len(facts) > max_facts:
                # decay_factor 最小のものを削除
                half_life = config.FACT_DECAY_HALF_LIFE_DAYS
                facts.sort(key=lambda f: f.decay_factor(half_life))
                self._facts[fact.channel_id] = facts[len(facts) - max_facts:]
                logger.debug(
                    f"ファクト上限超過により古いファクトを削除: channel_id={fact.channel_id}"
                )

    def search(
        self,
        channel_id: int,
        keywords: list[str],
        user_ids: list[int] | None = None,
        limit: int = 5,
    ) -> list[Fact]:
        """Jaccard × decay_factor でランキングして返す

        Args:
            channel_id: 検索対象チャンネルID
            keywords: 検索キーワードリスト
            user_ids: このユーザーIDに関連するファクトをブースト（任意）
            limit: 返す最大件数
        """
        self._load_channel(channel_id)
        with self._lock:
            facts = list(self._facts.get(channel_id, []))
        if not facts:
            return []

        query_set = set(keywords)
        half_life = config.FACT_DECAY_HALF_LIFE_DAYS
        scored: list[tuple[float, Fact]] = []

        for fact in facts:
            decay = fact.decay_factor(half_life)
            if decay == 0:
                continue

            keyword_set = set(fact.keywords)
            jaccard = _jaccard_similarity(query_set, keyword_set)

            score = jaccard * decay

            # user_id ブースト
            if user_ids and any(uid in fact.source_user_ids for uid in user_ids):
                score *= 1.5

            if score > 0:
                scored.append((score, fact))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [f for _, f in scored[:limit]]

    def get_shareable_facts(self, channel_id: int) -> list[Fact]:
        """shareable=True のファクトを decay_factor 降順で返す"""
        self._load_channel(channel_id)
        with self._lock:
            facts = list(self._facts.get(channel_id, []))
        half_life = config.FACT_DECAY_HALF_LIFE_DAYS
        shareable = [f for f in facts if f.shareable]
        shareable.sort(key=lambda f: f.decay_factor(half_life), reverse=True)
        return shareable

    def persist_all(self) -> None:
        """全チャンネルを永続化する（クリーンアップタスクから呼ばれる）"""
        with self._lock:
            snapshot = {cid: list(facts) for cid, facts in self._facts.items()}
        storage_type = config.STORAGE_TYPE
        for channel_id, facts in snapshot.items():
            if storage_type == "local":
                self._save_to_local(channel_id, facts)
            elif storage_type == "firestore":
                self._save_to_firestore(channel_id, facts)

    def _load_channel(self, channel_id: int) -> None:
        """初回アクセス時に永続化先からファクトを遅延ロードする。

        ダブルチェックロッキングパターンを使用する:
        1. ロックなしで既ロード済みを確認（高速パス）
        2. I/O をロック外で実行してパフォーマンスを維持
        3. ロックを再取得して _loaded_channels と _facts を更新
        複数スレッドが同時に未ロードのチャンネルに到達した場合、I/O が複数回
        実行される可能性があるが、同一データの書き込みなので安全（べき等）。
        """
        with self._lock:
            if channel_id in self._loaded_channels:
                return

        storage_type = config.STORAGE_TYPE
        facts: list[Fact] | None = None

        if storage_type == "local":
            facts = self._load_from_local(channel_id)
        elif storage_type == "firestore":
            facts = self._load_from_firestore(channel_id)

        with self._lock:
            # 別スレッドが先にロードを完了していた場合はスキップ
            if channel_id not in self._loaded_channels:
                if facts is not None:
                    self._facts[channel_id] = facts
                self._loaded_channels.add(channel_id)

    def _save_to_local(self, channel_id: int, facts: list[Fact]) -> None:
        """ローカルファイルにアトミック書き込み"""
        from utils.file_utils import atomic_write_json

        file_path = f"storage/facts.{channel_id}.json"
        try:
            data = {
                "channel_id": channel_id,
                "facts": [f.to_dict() for f in facts],
            }
            atomic_write_json(file_path, data)
        except Exception as e:
            logger.error(f"ファクトのローカル保存エラー: {e}", exc_info=True)

    def _load_from_local(self, channel_id: int) -> list[Fact] | None:
        """ローカルファイルからファクトを読み込む"""
        file_path = f"storage/facts.{channel_id}.json"
        try:
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return [Fact.from_dict(item) for item in data.get("facts", [])]
        except Exception as e:
            logger.error(f"ファクトのローカル読み込みエラー: {e}", exc_info=True)
        return None

    def _save_to_firestore(self, channel_id: int, facts: list[Fact]) -> None:
        """Firestoreにファクトを保存する"""
        try:
            from utils.firestore_client import get_firestore_client

            db = get_firestore_client()
            data = {
                "channel_id": channel_id,
                "facts": [f.to_dict() for f in facts],
            }
            db.collection(config.FIRESTORE_COLLECTION_FACTS).document(
                str(channel_id)
            ).set(data)
        except Exception as e:
            logger.error(f"ファクトのFirestore保存エラー: {e}", exc_info=True)

    def _load_from_firestore(self, channel_id: int) -> list[Fact] | None:
        """Firestoreからファクトを読み込む"""
        try:
            from utils.firestore_client import get_firestore_client

            db = get_firestore_client()
            doc = (
                db.collection(config.FIRESTORE_COLLECTION_FACTS)
                .document(str(channel_id))
                .get()
            )
            if doc.exists:  # type: ignore[union-attr]
                data = doc.to_dict()  # type: ignore[union-attr]
                if data is not None:
                    return [Fact.from_dict(item) for item in data.get("facts", [])]
        except Exception as e:
            logger.error(f"ファクトのFirestore読み込みエラー: {e}", exc_info=True)
        return None


# シングルトン
_fact_store: FactStore | None = None


def get_fact_store() -> FactStore:
    """FactStoreのシングルトンインスタンスを取得する"""
    global _fact_store
    if _fact_store is None:
        _fact_store = FactStore()
        logger.info(f"FactStore初期化: storage_type={config.STORAGE_TYPE}")
    return _fact_store
