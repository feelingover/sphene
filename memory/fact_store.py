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
    embedding: list[float] | None = None
    access_count: int = 0
    last_accessed_at: datetime | None = None

    def decay_factor(self, half_life_days: int) -> float:
        """経過日数から指数減衰係数を返す（半減期でスコアが0.5になる）"""
        now = datetime.now(timezone.utc)
        created = self.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        elapsed_days = (now - created).total_seconds() / 86400
        return math.pow(0.5, elapsed_days / half_life_days)

    def effective_relevance_score(self, half_life_days: int, access_boost_weight: float = 0.1) -> float:
        """時間減衰 + 参照頻度ブーストを組み合わせたスコア（クリーンアップ閾値判定用）

        Args:
            half_life_days: 半減期（日）
            access_boost_weight: 参照頻度ブーストの重み係数

        Returns:
            0.0〜1.0のスコア。頻繁に参照されたファクトほど高くなる。
        """
        time_decay = self.decay_factor(half_life_days)
        access_boost = math.log1p(self.access_count) * access_boost_weight
        return min(1.0, time_decay + access_boost)

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
            "embedding": self.embedding,
            "access_count": self.access_count,
            "last_accessed_at": self.last_accessed_at.isoformat() if self.last_accessed_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Fact":
        """辞書からFactを復元する"""
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif created_at is None:
            created_at = datetime.now(timezone.utc)

        last_accessed_at = data.get("last_accessed_at")
        if isinstance(last_accessed_at, str):
            last_accessed_at = datetime.fromisoformat(last_accessed_at)
        else:
            last_accessed_at = None

        return cls(
            fact_id=data.get("fact_id", str(uuid.uuid4())),
            channel_id=data["channel_id"],
            content=data.get("content", ""),
            keywords=data.get("keywords", []),
            source_user_ids=data.get("source_user_ids", []),
            created_at=created_at,
            shareable=data.get("shareable", False),
            embedding=data.get("embedding", None),
            access_count=data.get("access_count", 0),
            last_accessed_at=last_accessed_at,
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


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """2つのベクトルのコサイン類似度を返す"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def extract_keywords(text: str) -> list[str]:
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
        query_embedding: list[float] | None = None,
    ) -> list[Fact]:
        """Jaccard × decay_factor でランキングして返す。VECTOR_SEARCH_ENABLED 時はハイブリッド検索。

        Args:
            channel_id: 検索対象チャンネルID
            keywords: 検索キーワードリスト
            user_ids: このユーザーIDに関連するファクトをブースト（任意）
            limit: 返す最大件数
            query_embedding: クエリのEmbeddingベクトル（ハイブリッド検索用、任意）
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

            if config.VECTOR_SEARCH_ENABLED and query_embedding and fact.embedding:
                cosine = max(0.0, _cosine_similarity(query_embedding, fact.embedding))
                jaccard = _jaccard_similarity(query_set, set(fact.keywords))
                alpha = config.HYBRID_ALPHA
                score = (alpha * cosine + (1 - alpha) * jaccard) * decay
            else:
                score = _jaccard_similarity(query_set, set(fact.keywords)) * decay

            # user_id ブースト
            if user_ids and any(uid in fact.source_user_ids for uid in user_ids):
                score *= config.FACT_USER_BOOST_FACTOR

            if score > 0:
                scored.append((score, fact))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = [f for _, f in scored[:limit]]

        # ヒットしたファクトの参照頻度を更新（ロック内でアトミックに更新）
        now = datetime.now(timezone.utc)
        with self._lock:
            for fact in results:
                fact.access_count += 1
                fact.last_accessed_at = now

        return results

    def get_shareable_facts(self, channel_id: int) -> list[Fact]:
        """shareable=True のファクトを decay_factor 降順で返す"""
        self._load_channel(channel_id)
        with self._lock:
            facts = list(self._facts.get(channel_id, []))
        half_life = config.FACT_DECAY_HALF_LIFE_DAYS
        shareable = [f for f in facts if f.shareable]
        shareable.sort(key=lambda f: f.decay_factor(half_life), reverse=True)
        return shareable

    def persist_channel(self, channel_id: int) -> None:
        """特定のチャンネルを永続化する"""
        with self._lock:
            if channel_id not in self._facts:
                return
            facts = list(self._facts[channel_id])

        storage_type = config.STORAGE_TYPE
        if storage_type == "local":
            self._save_to_local(channel_id, facts)
        elif storage_type == "firestore":
            self._save_to_firestore(channel_id, facts)

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

        2段階ロックパターンを使用する:
        1. ロック取得 → 既ロード済みなら即リターン（高速パス）
        2. ロック解放後に I/O を実行してロック保持時間を最小化
        3. ロックを再取得して _loaded_channels と _facts を更新
        複数スレッドが同時に未ロードのチャンネルに到達した場合、I/O が複数回
        実行される可能性があるが、同一データの書き込みなので安全（べき等）。
        ロック取得済みのスレッドが先に完了した場合、後発スレッドは最終チェックで
        スキップするため、途中で追加されたファクトが上書きされることはない。
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

    def cleanup_low_relevance_facts(self) -> dict[int, int]:
        """全チャンネルで effective_relevance_score が閾値以下のファクトを削除する。

        Returns:
            {channel_id: 削除数} の辞書（削除が発生したチャンネルのみ含む）
        """
        threshold = config.FACT_STORE_CLEANUP_THRESHOLD
        half_life = config.FACT_DECAY_HALF_LIFE_DAYS
        access_boost_weight = config.FACT_ACCESS_BOOST_WEIGHT
        removed_counts: dict[int, int] = {}

        with self._lock:
            channel_ids = list(self._facts.keys())

        for channel_id in channel_ids:
            with self._lock:
                facts = list(self._facts.get(channel_id, []))

            remove: list[tuple[float, Fact]] = []
            for fact in facts:
                score = fact.effective_relevance_score(half_life, access_boost_weight)
                if score < threshold:
                    remove.append((score, fact))

            if not remove:
                continue

            self._archive_facts(channel_id, remove)

            # fact_id 差分削除: 読み取り後に追加された新ファクトを失わないよう
            # keep リストではなく remove_ids で絞り込む
            remove_ids = {f.fact_id for _, f in remove}
            with self._lock:
                remaining = [f for f in self._facts.get(channel_id, []) if f.fact_id not in remove_ids]
                self._facts[channel_id] = remaining

            self.persist_channel(channel_id)
            removed_counts[channel_id] = len(remove)
            logger.info(
                f"ファクト忘却クリーンアップ: channel_id={channel_id}, "
                f"削除数={len(remove)}, 残存={len(remaining)}, threshold={threshold}"
            )

        return removed_counts

    def _archive_facts(self, channel_id: int, scored_facts: list[tuple[float, Fact]]) -> None:
        """削除ファクトをアーカイブする。

        常にログ出力を行い、FACT_STORE_ARCHIVE_ENABLED=true の場合は
        ストレージにも書き出す。

        Args:
            channel_id: チャンネルID
            scored_facts: (effective_relevance_score, fact) のペアリスト
        """
        for score, fact in scored_facts:
            logger.info(
                f"ファクト削除: channel_id={channel_id}, fact_id={fact.fact_id}, "
                f"score={score:.4f}, access_count={fact.access_count}, "
                f"content={fact.content[:50]!r}"
            )

        if not config.FACT_STORE_ARCHIVE_ENABLED:
            return

        facts = [f for _, f in scored_facts]
        storage_type = config.STORAGE_TYPE
        if storage_type == "local":
            self._append_to_local_archive(channel_id, facts)
        elif storage_type == "firestore":
            self._append_to_firestore_archive(channel_id, facts)

    def _append_to_local_archive(self, channel_id: int, facts: list[Fact]) -> None:
        """ローカルアーカイブファイルにファクトを追記する"""
        from utils.file_utils import atomic_write_json

        file_path = f"storage/facts_archive.{channel_id}.json"
        try:
            existing: list[dict] = []
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                existing = data.get("archived_facts", [])

            archived_at = datetime.now(timezone.utc).isoformat()
            for fact in facts:
                entry = fact.to_dict()
                entry["archived_at"] = archived_at
                existing.append(entry)

            # 上限を超えた分は古い順に切り捨て
            max_entries = config.FACT_ARCHIVE_MAX_ENTRIES
            if len(existing) > max_entries:
                existing = existing[-max_entries:]

            atomic_write_json(file_path, {"channel_id": channel_id, "archived_facts": existing})
        except Exception as e:
            logger.error(f"ファクトローカルアーカイブエラー: {e}", exc_info=True)

    def _append_to_firestore_archive(self, channel_id: int, facts: list[Fact]) -> None:
        """Firestoreアーカイブコレクションにファクトを追加する"""
        try:
            from utils.firestore_client import get_firestore_client

            db = get_firestore_client()
            doc_ref = db.collection(config.FIRESTORE_COLLECTION_FACTS_ARCHIVE).document(
                str(channel_id)
            )
            doc = doc_ref.get()
            existing: list[dict] = []
            if doc.exists:  # type: ignore[union-attr]
                data = doc.to_dict()  # type: ignore[union-attr]
                if data:
                    existing = data.get("archived_facts", [])

            archived_at = datetime.now(timezone.utc).isoformat()
            for fact in facts:
                entry = fact.to_dict()
                entry["archived_at"] = archived_at
                existing.append(entry)

            # Firestore ドキュメント上限（1MB）対策: 古い順に切り捨て
            max_entries = config.FACT_ARCHIVE_MAX_ENTRIES
            if len(existing) > max_entries:
                existing = existing[-max_entries:]

            doc_ref.set({"channel_id": channel_id, "archived_facts": existing})
        except Exception as e:
            logger.error(f"ファクトFirestoreアーカイブエラー: {e}", exc_info=True)


# シングルトン
_fact_store: FactStore | None = None
_fact_store_lock = threading.Lock()


def get_fact_store() -> FactStore:
    """FactStoreのシングルトンインスタンスを取得する"""
    global _fact_store
    if _fact_store is None:
        with _fact_store_lock:
            if _fact_store is None:
                _fact_store = FactStore()
                logger.info(f"FactStore初期化: storage_type={config.STORAGE_TYPE}")
    return _fact_store
