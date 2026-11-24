"""自発会話の担当インスタンスを管理する登録簿（issue #104）

「チャンネル → 担当インスタンス（INSTANCE_NAME）」を、インスタンス間で共有する
ストアに記録する。1チャンネルを担当できるのは1インスタンスだけにするためのもの。

- firestore: ``PROACTIVE_REGISTRY_COLLECTION`` の共有コレクション。
  インスタンス間で共有するのが目的なので ``FIRESTORE_NAMESPACE`` は付けない。
  登録・削除は transaction で行う
- local: ローカルの JSON ファイル（``PROACTIVE_REGISTRY_FILE``）。同じホストの中でだけ有効
"""

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol

from google.cloud import firestore

import config
from log_utils.logger import logger
from utils.file_utils import atomic_write_json, local_storage_path
from utils.firestore_client import get_firestore_client

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows では排他しない（本番は Linux 想定）
    fcntl = None  # type: ignore[assignment]

_DEFAULT_REGISTRY_FILENAME = "proactive_channel_registry.json"


class ClaimStatus(Enum):
    """登録簿への登録（claim）の結果"""

    CLAIMED = "claimed"  # 新しく担当になった
    ALREADY_OWNED = "already_owned"  # すでに自分が担当している
    OWNED_BY_OTHER = "owned_by_other"  # 別のインスタンスが担当している


@dataclass(frozen=True)
class ClaimResult:
    """claim の結果

    Attributes:
        status: 登録の結果
        owner: 処理後の担当インスタンス名（OWNED_BY_OTHER のときは担当中の別インスタンス）
    """

    status: ClaimStatus
    owner: str


class ProactiveRegistry(Protocol):
    """担当インスタンスの登録簿のインターフェース"""

    def claim(self, channel_id: int | str, instance: str) -> ClaimResult:
        """チャンネルの担当として登録する（自分がすでに担当なら冪等に成功）"""
        ...

    def release(self, channel_id: int | str, instance: str) -> bool:
        """自分が担当している場合だけ登録を削除する。削除したら True"""
        ...

    def get_owner(self, channel_id: int | str) -> str | None:
        """チャンネルの担当インスタンス名を返す（未登録なら None）"""
        ...


def _now_iso() -> str:
    """現在時刻（UTC）を ISO8601 文字列で返す"""
    return datetime.now(timezone.utc).isoformat()


def _owner_of(entry: Any) -> str | None:
    """登録簿のエントリから担当インスタンス名を取り出す

    Args:
        entry: 登録簿のエントリ（dict を想定）

    Returns:
        担当インスタンス名。取り出せない場合は None
    """
    if isinstance(entry, dict):
        owner = entry.get("instance")
        if isinstance(owner, str) and owner:
            return owner
    return None


def _decide_claim(current_owner: str | None, instance: str) -> ClaimResult:
    """現在の担当者から claim の結果を決める

    Args:
        current_owner: 現在の担当インスタンス名（未登録なら None）
        instance: 登録しようとしているインスタンス名

    Returns:
        claim の結果
    """
    if current_owner is None:
        return ClaimResult(ClaimStatus.CLAIMED, instance)
    if current_owner == instance:
        return ClaimResult(ClaimStatus.ALREADY_OWNED, instance)
    return ClaimResult(ClaimStatus.OWNED_BY_OTHER, current_owner)


class LocalProactiveRegistry:
    """ローカルの JSON ファイルで管理する登録簿（同じホストの中でだけ有効）

    ロックファイルに flock をかけてから読み込み・更新・保存を行う。flock はオープンした
    ファイル記述ごとにかかるため、同じホストのプロセス間・同じプロセスのスレッド間の
    どちらでも排他される（インスタンスを使い回す必要はない）。
    """

    def __init__(self, file_path: str) -> None:
        """初期化

        Args:
            file_path: 登録簿の JSON ファイルのパス
        """
        self.file_path = file_path

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """スレッド間・プロセス間で登録簿の操作を flock で排他する

        os.replace で登録簿の inode が入れ替わってもロックが外れないよう、別ファイルにかける。
        """
        if fcntl is None:  # pragma: no cover
            yield
            return
        parent = os.path.dirname(self.file_path) or "."
        os.makedirs(parent, exist_ok=True)
        with open(f"{self.file_path}.lock", "a", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _read(self) -> dict[str, Any]:
        """登録簿を読み込む。ファイルがなければ空の登録簿を返す

        Returns:
            {channel_id: {"instance": ..., "claimed_at": ...}} の dict

        Raises:
            ValueError: ファイルの中身が登録簿の形式でない場合（壊れたファイルは上書きしない）
        """
        if not os.path.exists(self.file_path):
            return {}
        with open(self.file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        channels = data.get("channels") if isinstance(data, dict) else None
        if not isinstance(channels, dict):
            raise ValueError(f"自発会話の登録簿の形式が不正です: {self.file_path}")
        return channels

    def _write(self, channels: dict[str, Any]) -> None:
        """登録簿をアトミックに保存する

        Args:
            channels: 保存する登録簿
        """
        atomic_write_json(self.file_path, {"channels": channels})

    def claim(self, channel_id: int | str, instance: str) -> ClaimResult:
        """チャンネルの担当として登録する（自分がすでに担当なら冪等に成功）

        Args:
            channel_id: チャンネルID
            instance: 担当になるインスタンス名

        Returns:
            claim の結果
        """
        key = str(channel_id)
        with self._locked():
            channels = self._read()
            result = _decide_claim(_owner_of(channels.get(key)), instance)
            if result.status is ClaimStatus.CLAIMED:
                channels[key] = {"instance": instance, "claimed_at": _now_iso()}
                self._write(channels)
        return result

    def release(self, channel_id: int | str, instance: str) -> bool:
        """自分が担当している場合だけ登録を削除する

        Args:
            channel_id: チャンネルID
            instance: 削除を要求するインスタンス名

        Returns:
            登録を削除した場合 True（未登録・別インスタンスが担当中なら False）
        """
        key = str(channel_id)
        with self._locked():
            channels = self._read()
            if _owner_of(channels.get(key)) != instance:
                return False
            del channels[key]
            self._write(channels)
        return True

    def get_owner(self, channel_id: int | str) -> str | None:
        """チャンネルの担当インスタンス名を返す

        Args:
            channel_id: チャンネルID

        Returns:
            担当インスタンス名。未登録なら None
        """
        with self._locked():
            return _owner_of(self._read().get(str(channel_id)))


@firestore.transactional
def _claim_in_transaction(
    transaction: firestore.Transaction, ref: Any, instance: str
) -> ClaimResult:
    """transaction の中で担当者を確認し、未登録なら登録する"""
    snapshot = ref.get(transaction=transaction)
    current = _owner_of(snapshot.to_dict()) if snapshot.exists else None
    result = _decide_claim(current, instance)
    if result.status is ClaimStatus.CLAIMED:
        transaction.set(ref, {"instance": instance, "claimed_at": _now_iso()})
    return result


@firestore.transactional
def _release_in_transaction(
    transaction: firestore.Transaction, ref: Any, instance: str
) -> bool:
    """transaction の中で担当者を確認し、自分が担当なら削除する"""
    snapshot = ref.get(transaction=transaction)
    if not snapshot.exists or _owner_of(snapshot.to_dict()) != instance:
        return False
    transaction.delete(ref)
    return True


class FirestoreProactiveRegistry:
    """Firestore の共有コレクションで管理する登録簿（FIRESTORE_NAMESPACE は付けない）"""

    def __init__(self, collection_name: str) -> None:
        """初期化

        Args:
            collection_name: 共有コレクション名
        """
        self.collection_name = collection_name

    def _ref(self, channel_id: int | str) -> Any:
        """チャンネルのドキュメント参照を返す"""
        db = get_firestore_client()
        return db.collection(self.collection_name).document(str(channel_id))

    def claim(self, channel_id: int | str, instance: str) -> ClaimResult:
        """チャンネルの担当として登録する（transaction で二重登録を防ぐ）

        Args:
            channel_id: チャンネルID
            instance: 担当になるインスタンス名

        Returns:
            claim の結果
        """
        transaction = get_firestore_client().transaction()
        return _claim_in_transaction(transaction, self._ref(channel_id), instance)

    def release(self, channel_id: int | str, instance: str) -> bool:
        """自分が担当している場合だけ登録を削除する

        Args:
            channel_id: チャンネルID
            instance: 削除を要求するインスタンス名

        Returns:
            登録を削除した場合 True（未登録・別インスタンスが担当中なら False）
        """
        transaction = get_firestore_client().transaction()
        return _release_in_transaction(transaction, self._ref(channel_id), instance)

    def get_owner(self, channel_id: int | str) -> str | None:
        """チャンネルの担当インスタンス名を返す

        Args:
            channel_id: チャンネルID

        Returns:
            担当インスタンス名。未登録なら None
        """
        snapshot = self._ref(channel_id).get()
        if not snapshot.exists:
            return None
        return _owner_of(snapshot.to_dict())


def registry_file_path() -> str:
    """local バックエンドの登録簿ファイルのパスを返す

    ``PROACTIVE_REGISTRY_FILE`` が未設定なら ``LOCAL_STORAGE_DIR`` 配下の既定ファイルを使う。

    Returns:
        登録簿ファイルのパス
    """
    return config.PROACTIVE_REGISTRY_FILE or local_storage_path(_DEFAULT_REGISTRY_FILENAME)


def get_proactive_registry() -> ProactiveRegistry:
    """``STORAGE_TYPE`` に応じた登録簿を返す

    Returns:
        firestore なら共有コレクション、それ以外はローカルファイルの登録簿
    """
    if config.STORAGE_TYPE == "firestore":
        return FirestoreProactiveRegistry(config.PROACTIVE_REGISTRY_COLLECTION)
    path = registry_file_path()
    logger.debug(f"自発会話の登録簿（local）: {path}")
    return LocalProactiveRegistry(path)
