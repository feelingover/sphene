"""ファクトストア: LLM抽出ファクトのキーワード検索・永続化"""

import json
import math
import os
import re
import threading
import unicodedata
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import config
from log_utils.logger import logger
from memory.backoff import new_storage_load_backoff
from memory.errors import StorageLoadError, log_storage_load_failure
from utils.file_utils import local_storage_path
from utils.keyed_lock import KeyedLock

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

    def snapshot(self) -> "Fact":
        """保存時のスナップショット用コピーを返す

        search で書き換わる access_count / last_accessed_at を固定するためのもの。
        keywords などのリストは作成後に書き換えないため共有する。
        """
        return replace(self)

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


_NORMALIZE_STRIP_RE = re.compile(r"[\s\W_]+")


def _normalize_fact_content(text: str) -> str:
    """重複判定用にファクト本文を正規化する（NFKC・小文字化・空白/記号除去）"""
    return _NORMALIZE_STRIP_RE.sub("", unicodedata.normalize("NFKC", text).lower())


def _find_duplicate(fact: Fact, existing: list[Fact]) -> Fact | None:
    """既存ファクトの中から重複するものを返す

    正規化した本文が一致するか、両方にEmbeddingがありコサイン類似度が
    FACT_DEDUP_SIMILARITY_THRESHOLD 以上なら重複とみなす。

    Args:
        fact: 判定対象のファクト
        existing: 同じチャンネルの既存ファクト

    Returns:
        重複している既存ファクト。なければ None。
    """
    normalized = _normalize_fact_content(fact.content)
    threshold = config.FACT_DEDUP_SIMILARITY_THRESHOLD
    for other in existing:
        if normalized and normalized == _normalize_fact_content(other.content):
            return other
        if (
            fact.embedding
            and other.embedding
            and len(fact.embedding) == len(other.embedding)
            and _cosine_similarity(fact.embedding, other.embedding) >= threshold
        ):
            return other
    return None


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
        # 永続化先と差分があるチャンネル（persist_all はここに含まれるものだけ書き込む）
        self._dirty: set[int] = set()
        # 読み込みに失敗したチャンネルの再読み込み間隔（ロック内で操作する）
        self._load_backoff = new_storage_load_backoff()
        self._lock = threading.Lock()
        # チャンネル単位の保存ロック（スナップショット取得から書き込み完了まで保持する）。
        # 古いスナップショットの書き込みが新しいものより後に完了して上書きするのを防ぐ。
        # 取得順は必ず保存ロック → self._lock とする。
        self._save_locks: KeyedLock[int] = KeyedLock()

    def add_fact(self, fact: Fact) -> bool:
        """ファクトを追加する。上限超過時はdecay_factor最小のものを削除

        既存ファクトと内容が重複する場合は追加しない。

        Args:
            fact: 追加するファクト

        Returns:
            追加した場合は True、重複のためスキップした場合は False
        """
        self._load_channel(fact.channel_id)
        with self._lock:
            facts = self._facts.setdefault(fact.channel_id, [])
            duplicate = _find_duplicate(fact, facts)
            if duplicate is not None:
                logger.debug(
                    f"重複ファクトをスキップ: channel_id={fact.channel_id}, "
                    f"existing={duplicate.fact_id}"
                )
                return False
            facts.append(fact)
            self._dirty.add(fact.channel_id)

            max_facts = config.FACT_STORE_MAX_FACTS_PER_CHANNEL
            if len(facts) > max_facts:
                # decay_factor 最小のものを削除
                half_life = config.FACT_DECAY_HALF_LIFE_DAYS
                facts.sort(key=lambda f: f.decay_factor(half_life))
                self._facts[fact.channel_id] = facts[len(facts) - max_facts:]
                logger.debug(
                    f"ファクト上限超過により古いファクトを削除: channel_id={fact.channel_id}"
                )
        return True

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
            if results:
                # 参照頻度は忘却スコアに使うため永続化対象にする
                self._dirty.add(channel_id)

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
        """特定のチャンネルを永続化する（変更の有無にかかわらず書き込む）

        永続化先から読み込めていないチャンネルは、既存データを上書きしないよう書き込まない
        （dirty のまま残し、ロード成功後に保存する）。
        """
        self._persist_channel_serialized(channel_id, only_if_dirty=False)

    def persist_all(self) -> None:
        """変更のあったチャンネルだけを永続化する（クリーンアップタスクから呼ばれる）

        書き込みに失敗したチャンネルは次回の persist_all で再試行する。
        """
        with self._lock:
            # 未ロードのチャンネルは既存データを上書きしないよう dirty に残して保存を見送る
            targets = [cid for cid in self._dirty if cid in self._loaded_channels]
        results = [self._persist_channel_serialized(cid, only_if_dirty=True) for cid in targets]
        attempted = [ok for ok in results if ok is not None]
        if attempted:
            logger.debug(f"ファクト永続化: {sum(attempted)}/{len(attempted)}チャンネル")

    def _persist_channel_serialized(self, channel_id: int, only_if_dirty: bool) -> bool | None:
        """チャンネルの保存ロックを保持したままスナップショットを取り、書き込む

        同じチャンネルの保存は直列化されるため、後から取ったスナップショットが
        必ず後に書き込まれる（古い内容による上書きが起きない）。

        Args:
            channel_id: チャンネルID
            only_if_dirty: True の場合、dirty でなければ書き込まない
                （待機中に別スレッドが保存を済ませたケース）

        Returns:
            書き込みの成否。書き込みを行わなかった場合は None
        """
        with self._save_locks.get(channel_id):
            with self._lock:
                if only_if_dirty and channel_id not in self._dirty:
                    return None
                if channel_id not in self._loaded_channels:
                    return None
                if channel_id not in self._facts:
                    # 書き込む内容がないので dirty も外す（ファクト追加時に再び立つ）
                    self._dirty.discard(channel_id)
                    return None
                # search による access_count 等の書き換えと排他にするため、ロック内で複製する
                facts = [f.snapshot() for f in self._facts[channel_id]]
                self._dirty.discard(channel_id)

            if self._save_channel(channel_id, facts):
                return True
            with self._lock:
                self._dirty.add(channel_id)
            return False

    def _save_channel(self, channel_id: int, facts: list[Fact]) -> bool:
        """設定された永続化先にチャンネルのファクトを書き込む

        Returns:
            書き込みに成功した（または永続化しない設定の）場合True
        """
        storage_type = config.STORAGE_TYPE
        if storage_type == "local":
            return self._save_to_local(channel_id, facts)
        if storage_type == "firestore":
            return self._save_to_firestore(channel_id, facts)
        return True

    def ensure_loaded(self, channel_id: int) -> None:
        """チャンネルのファクトを永続化先から読み込み済みにする（I/Oを伴う）

        Args:
            channel_id: チャンネルID
        """
        self._load_channel(channel_id)

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
        読み込みに失敗したチャンネルは、バックオフ期間中は I/O を行わず未ロードのまま扱う。
        """
        with self._lock:
            if channel_id in self._loaded_channels:
                return
            if self._load_backoff.is_blocked(channel_id):
                # 失敗直後は I/O を繰り返さず、未ロードのまま扱う
                return

        try:
            facts = self._read_channel(channel_id)
        except StorageLoadError:
            # ロード済みにしないことで、バックオフ明けのアクセスで再試行する
            with self._lock:
                failures = self._load_backoff.record_failure(channel_id)
            log_storage_load_failure(
                f"ファクトの読み込みに失敗したため未ロードのまま扱います: channel_id={channel_id}",
                failures,
            )
            return

        with self._lock:
            self._load_backoff.reset(channel_id)
            # 別スレッドが先にロードを完了していた場合はスキップ
            if channel_id not in self._loaded_channels:
                if facts is not None:
                    self._facts[channel_id] = _merge_pending_facts(
                        facts, self._facts.get(channel_id, [])
                    )
                self._loaded_channels.add(channel_id)

    def _read_channel(self, channel_id: int) -> list[Fact] | None:
        """永続化先からチャンネルのファクトを読み込む

        Returns:
            ファクトのリスト。データが存在しなければ None。

        Raises:
            StorageLoadError: 読み込みに失敗した場合
        """
        storage_type = config.STORAGE_TYPE
        if storage_type == "local":
            return self._load_from_local(channel_id)
        if storage_type == "firestore":
            return self._load_from_firestore(channel_id)
        return None

    def _save_to_local(self, channel_id: int, facts: list[Fact]) -> bool:
        """ローカルファイルにアトミック書き込み"""
        from utils.file_utils import atomic_write_json

        file_path = local_storage_path(f"facts.{channel_id}.json")
        try:
            data = {
                "channel_id": channel_id,
                "facts": [f.to_dict() for f in facts],
            }
            atomic_write_json(file_path, data)
            return True
        except Exception as e:
            logger.error(f"ファクトのローカル保存エラー: {e}", exc_info=True)
            return False

    def _load_from_local(self, channel_id: int) -> list[Fact] | None:
        """ローカルファイルからファクトを読み込む"""
        file_path = local_storage_path(f"facts.{channel_id}.json")
        try:
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return [Fact.from_dict(item) for item in data.get("facts", [])]
        except Exception as e:
            raise StorageLoadError(f"ファクトのローカル読み込みに失敗: {file_path}") from e
        return None

    def _save_to_firestore(self, channel_id: int, facts: list[Fact]) -> bool:
        """Firestoreにファクトを保存する（1MiB上限を超える分は関連度の低い順に除外）"""
        try:
            from utils.firestore_client import get_firestore_client

            db = get_firestore_client()
            data = {
                "channel_id": channel_id,
                "facts": _fit_facts_to_document(channel_id, facts),
            }
            db.collection(config.FIRESTORE_COLLECTION_FACTS).document(
                str(channel_id)
            ).set(data)
            return True
        except Exception as e:
            logger.error(f"ファクトのFirestore保存エラー: {e}", exc_info=True)
            return False

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
            raise StorageLoadError(
                f"ファクトのFirestore読み込みに失敗: channel_id={channel_id}"
            ) from e
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
                # スコア計算・アーカイブ中に search が access_count を書き換えないよう複製する
                facts = [f.snapshot() for f in self._facts.get(channel_id, [])]

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

        file_path = local_storage_path(f"facts_archive.{channel_id}.json")
        try:
            existing: list[dict] = []
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                existing = data.get("archived_facts", [])

            existing.extend(_to_archive_entries(facts))

            existing = _trim_archive_entries(existing, size_limited=False)

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

            existing.extend(_to_archive_entries(facts))

            # Firestore ドキュメント上限（1MiB）対策: 件数とサイズの両方で古い順に切り捨て
            existing = _trim_archive_entries(existing, size_limited=True)

            doc_ref.set({"channel_id": channel_id, "archived_facts": existing})
        except Exception as e:
            logger.error(f"ファクトFirestoreアーカイブエラー: {e}", exc_info=True)


def _merge_pending_facts(loaded: list[Fact], pending: list[Fact]) -> list[Fact]:
    """読み込んだファクトに、未ロード中に追加されたファクトをマージする

    読み込みに失敗している間に追加されたファクトを、ロード成功時に捨てないための処理。
    既存と重複するものは追加せず、上限を超えた分は decay_factor の低いものから削る。

    Args:
        loaded: 永続化先から読み込んだファクト
        pending: 未ロード中にメモリ上へ追加されたファクト

    Returns:
        マージ後のファクトリスト
    """
    merged = list(loaded)
    for fact in pending:
        if _find_duplicate(fact, merged) is None:
            merged.append(fact)
    max_facts = config.FACT_STORE_MAX_FACTS_PER_CHANNEL
    if len(merged) > max_facts:
        half_life = config.FACT_DECAY_HALF_LIFE_DAYS
        merged.sort(key=lambda f: f.decay_factor(half_life))
        merged = merged[len(merged) - max_facts:]
    return merged


def _fit_facts_to_document(channel_id: int, facts: list[Fact]) -> list[dict]:
    """Firestoreの1ドキュメントに収まるよう、関連度の低いファクトから除外して辞書化する

    メモリ上のファクトは変更しない（次回以降の保存でも同じ判定になる）。

    Args:
        channel_id: チャンネルID（ログ用）
        facts: 保存するファクト

    Returns:
        ドキュメントサイズ上限に収まるファクト辞書のリスト（元の順序を維持）
    """
    from utils.firestore_client import (
        FIRESTORE_SAFE_DOCUMENT_BYTES,
        estimate_document_size,
        estimate_value_size,
    )

    entries = [f.to_dict() for f in facts]
    base = estimate_document_size({"channel_id": channel_id, "facts": []})
    sizes = [estimate_value_size(e) for e in entries]
    total = base + sum(sizes)
    if total <= FIRESTORE_SAFE_DOCUMENT_BYTES:
        return entries

    half_life = config.FACT_DECAY_HALF_LIFE_DAYS
    weight = config.FACT_ACCESS_BOOST_WEIGHT
    by_relevance = sorted(
        range(len(facts)), key=lambda i: facts[i].effective_relevance_score(half_life, weight)
    )
    dropped: set[int] = set()
    for i in by_relevance:
        if total <= FIRESTORE_SAFE_DOCUMENT_BYTES:
            break
        dropped.add(i)
        total -= sizes[i]
    logger.warning(
        f"ファクトがFirestoreのドキュメント上限を超えるため関連度の低い{len(dropped)}件を保存対象から除外: "
        f"channel_id={channel_id}, 保存件数={len(entries) - len(dropped)}, 推定サイズ={total}B "
        "(FACT_STORE_MAX_FACTS_PER_CHANNEL の引き下げを検討してください)"
    )
    return [e for i, e in enumerate(entries) if i not in dropped]


def _to_archive_entries(facts: list[Fact]) -> list[dict]:
    """アーカイブ用の辞書に変換する（embeddingは保存しない）

    アーカイブは読み戻されず、embeddingはEMBEDDING_MODELに依存するため、
    必要になった時点で本文から再生成する。
    """
    archived_at = datetime.now(timezone.utc).isoformat()
    entries = []
    for fact in facts:
        entry = fact.to_dict()
        entry.pop("embedding", None)
        entry["archived_at"] = archived_at
        entries.append(entry)
    return entries


def _trim_archive_entries(entries: list[dict], size_limited: bool) -> list[dict]:
    """アーカイブを件数上限（と必要ならFirestoreのサイズ上限）に収まるよう古い順に切り捨てる

    既存アーカイブに残っているembeddingもここで除去する。

    Args:
        entries: 古い順のアーカイブ項目
        size_limited: Trueの場合、Firestoreのドキュメントサイズ上限でも切り捨てる

    Returns:
        切り捨て後のアーカイブ項目
    """
    from utils.firestore_client import (
        FIRESTORE_SAFE_DOCUMENT_BYTES,
        estimate_document_size,
        estimate_value_size,
    )

    trimmed = [{k: v for k, v in e.items() if k != "embedding"} for e in entries]
    max_entries = config.FACT_ARCHIVE_MAX_ENTRIES
    if len(trimmed) > max_entries:
        trimmed = trimmed[-max_entries:]
    if not size_limited:
        return trimmed

    sizes = [estimate_value_size(e) for e in trimmed]
    total = estimate_document_size({"channel_id": 0, "archived_facts": []}) + sum(sizes)
    start = 0
    while total > FIRESTORE_SAFE_DOCUMENT_BYTES and start < len(trimmed):
        total -= sizes[start]
        start += 1
    if start:
        logger.warning(f"ファクトアーカイブがドキュメント上限を超えるため古い{start}件を削除")
    return trimmed[start:]


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
