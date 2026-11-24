"""自発会話の担当インスタンス登録簿（utils/proactive_registry.py）のテスト"""

import json
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import config
from utils.proactive_registry import (
    ClaimResult,
    ClaimStatus,
    FirestoreProactiveRegistry,
    LocalProactiveRegistry,
    _claim_in_transaction,
    _release_in_transaction,
    get_proactive_registry,
    registry_file_path,
)


@pytest.fixture
def registry_path(tmp_path: Path) -> str:
    """登録簿ファイルのパス（tmp_path 配下）"""
    return str(tmp_path / "shared" / "registry.json")


class TestLocalRegistry:
    """ローカルファイルの登録簿"""

    def test_claim_new_channel(self, registry_path: str) -> None:
        reg = LocalProactiveRegistry(registry_path)
        assert reg.claim(100, "a") == ClaimResult(ClaimStatus.CLAIMED, "a")
        assert reg.get_owner(100) == "a"
        assert reg.get_owner("100") == "a"

    def test_claim_is_idempotent_for_owner(self, registry_path: str) -> None:
        reg = LocalProactiveRegistry(registry_path)
        reg.claim(100, "a")
        with open(registry_path, encoding="utf-8") as f:
            claimed_at = json.load(f)["channels"]["100"]["claimed_at"]
        assert reg.claim(100, "a") == ClaimResult(ClaimStatus.ALREADY_OWNED, "a")
        with open(registry_path, encoding="utf-8") as f:
            assert json.load(f)["channels"]["100"]["claimed_at"] == claimed_at

    def test_claim_rejected_when_owned_by_other(self, registry_path: str) -> None:
        LocalProactiveRegistry(registry_path).claim(100, "a")
        # 同じファイルを共有する別インスタンスから
        other = LocalProactiveRegistry(registry_path)
        assert other.claim(100, "b") == ClaimResult(ClaimStatus.OWNED_BY_OTHER, "a")
        assert other.get_owner(100) == "a"

    def test_release_only_by_owner(self, registry_path: str) -> None:
        reg = LocalProactiveRegistry(registry_path)
        reg.claim(100, "a")
        assert reg.release(100, "b") is False
        assert reg.get_owner(100) == "a"
        assert reg.release(100, "a") is True
        assert reg.get_owner(100) is None
        # 解除後は別インスタンスが担当になれる
        assert reg.claim(100, "b").status is ClaimStatus.CLAIMED

    def test_release_unregistered_channel(self, registry_path: str) -> None:
        reg = LocalProactiveRegistry(registry_path)
        assert reg.release(100, "a") is False
        assert reg.get_owner(100) is None

    def test_channels_are_independent(self, registry_path: str) -> None:
        reg = LocalProactiveRegistry(registry_path)
        reg.claim(100, "a")
        assert reg.claim(200, "b").status is ClaimStatus.CLAIMED
        assert reg.get_owner(100) == "a"
        assert reg.get_owner(200) == "b"

    def test_concurrent_claims_have_single_owner(self, registry_path: str) -> None:
        """別インスタンスが同時に claim しても担当になるのは1つだけ"""
        results: list[ClaimResult] = []
        barrier = threading.Barrier(8)

        def _claim(name: str) -> None:
            reg = LocalProactiveRegistry(registry_path)
            barrier.wait()
            results.append(reg.claim(100, name))

        threads = [threading.Thread(target=_claim, args=(f"bot{i}",)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        winners = [r for r in results if r.status is ClaimStatus.CLAIMED]
        assert len(winners) == 1
        owner = LocalProactiveRegistry(registry_path).get_owner(100)
        assert owner == winners[0].owner
        assert all(r.owner == owner for r in results)

    def test_corrupt_file_raises_and_is_not_overwritten(self, registry_path: str) -> None:
        Path(registry_path).parent.mkdir(parents=True)
        Path(registry_path).write_text('["broken"]', encoding="utf-8")
        reg = LocalProactiveRegistry(registry_path)
        with pytest.raises(ValueError):
            reg.claim(100, "a")
        with pytest.raises(ValueError):
            reg.release(100, "a")
        assert Path(registry_path).read_text(encoding="utf-8") == '["broken"]'

    def test_invalid_json_raises(self, registry_path: str) -> None:
        Path(registry_path).parent.mkdir(parents=True)
        Path(registry_path).write_text("{", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            LocalProactiveRegistry(registry_path).get_owner(100)

    def test_malformed_entry_is_treated_as_unowned(self, registry_path: str) -> None:
        Path(registry_path).parent.mkdir(parents=True)
        Path(registry_path).write_text(
            json.dumps({"channels": {"100": "a", "200": {"instance": ""}}}), encoding="utf-8"
        )
        reg = LocalProactiveRegistry(registry_path)
        assert reg.get_owner(100) is None
        assert reg.get_owner(200) is None


class TestRegistryFactory:
    """STORAGE_TYPE によるバックエンドの切り替え"""

    def test_local_default_path_under_storage_dir(self, tmp_path: Path) -> None:
        with patch("config.STORAGE_TYPE", "local"), patch(
            "config.LOCAL_STORAGE_DIR", str(tmp_path)
        ), patch("config.PROACTIVE_REGISTRY_FILE", ""):
            reg = get_proactive_registry()
        assert isinstance(reg, LocalProactiveRegistry)
        assert reg.file_path == str(tmp_path / "proactive_channel_registry.json")

    def test_local_path_from_env(self, tmp_path: Path) -> None:
        path = str(tmp_path / "custom.json")
        with patch("config.PROACTIVE_REGISTRY_FILE", path):
            assert registry_file_path() == path

    def test_firestore_uses_shared_collection(self) -> None:
        with patch("config.STORAGE_TYPE", "firestore"), patch(
            "config.PROACTIVE_REGISTRY_COLLECTION", "shared_registry"
        ):
            reg = get_proactive_registry()
        assert isinstance(reg, FirestoreProactiveRegistry)
        assert reg.collection_name == "shared_registry"

    def test_default_collection_has_no_namespace(self) -> None:
        assert config.PROACTIVE_REGISTRY_COLLECTION == "proactive_channel_registry"
        assert config.FIRESTORE_NAMESPACE not in config.PROACTIVE_REGISTRY_COLLECTION


def _snapshot(data: dict[str, Any] | None) -> MagicMock:
    """Firestore のドキュメントスナップショットのモック"""
    snap = MagicMock()
    snap.exists = data is not None
    snap.to_dict.return_value = data
    return snap


class TestFirestoreTransactionBodies:
    """transaction の中で実行する処理（デコレータを外して検証）"""

    def test_claim_sets_when_unowned(self) -> None:
        tx, ref = MagicMock(), MagicMock()
        ref.get.return_value = _snapshot(None)
        result = _claim_in_transaction.to_wrap(tx, ref, "a")
        assert result == ClaimResult(ClaimStatus.CLAIMED, "a")
        ref.get.assert_called_once_with(transaction=tx)
        tx.set.assert_called_once()
        assert tx.set.call_args.args[1]["instance"] == "a"

    def test_claim_idempotent_does_not_write(self) -> None:
        tx, ref = MagicMock(), MagicMock()
        ref.get.return_value = _snapshot({"instance": "a"})
        assert _claim_in_transaction.to_wrap(tx, ref, "a").status is ClaimStatus.ALREADY_OWNED
        tx.set.assert_not_called()

    def test_claim_rejected_when_owned_by_other(self) -> None:
        tx, ref = MagicMock(), MagicMock()
        ref.get.return_value = _snapshot({"instance": "a"})
        assert _claim_in_transaction.to_wrap(tx, ref, "b") == ClaimResult(
            ClaimStatus.OWNED_BY_OTHER, "a"
        )
        tx.set.assert_not_called()

    def test_release_by_owner_deletes(self) -> None:
        tx, ref = MagicMock(), MagicMock()
        ref.get.return_value = _snapshot({"instance": "a"})
        assert _release_in_transaction.to_wrap(tx, ref, "a") is True
        tx.delete.assert_called_once_with(ref)

    @pytest.mark.parametrize("data", [None, {"instance": "a"}])
    def test_release_by_non_owner_is_noop(self, data: dict[str, Any] | None) -> None:
        tx, ref = MagicMock(), MagicMock()
        ref.get.return_value = _snapshot(data)
        assert _release_in_transaction.to_wrap(tx, ref, "b") is False
        tx.delete.assert_not_called()


class TestFirestoreRegistry:
    """Firestore の登録簿（クライアントはモック）"""

    @pytest.fixture
    def db(self) -> Any:
        with patch("utils.proactive_registry.get_firestore_client") as get_client:
            yield get_client.return_value

    def test_claim_runs_in_transaction_on_shared_collection(self, db: MagicMock) -> None:
        reg = FirestoreProactiveRegistry("shared_registry")
        expected = ClaimResult(ClaimStatus.CLAIMED, "a")
        with patch(
            "utils.proactive_registry._claim_in_transaction", return_value=expected
        ) as claim_tx:
            assert reg.claim(100, "a") == expected
        db.collection.assert_called_with("shared_registry")
        db.collection.return_value.document.assert_called_with("100")
        claim_tx.assert_called_once_with(
            db.transaction.return_value, db.collection.return_value.document.return_value, "a"
        )

    def test_release_runs_in_transaction(self, db: MagicMock) -> None:
        reg = FirestoreProactiveRegistry("shared_registry")
        with patch(
            "utils.proactive_registry._release_in_transaction", return_value=True
        ) as release_tx:
            assert reg.release(100, "a") is True
        release_tx.assert_called_once_with(
            db.transaction.return_value, db.collection.return_value.document.return_value, "a"
        )

    def test_get_owner(self, db: MagicMock) -> None:
        doc = db.collection.return_value.document.return_value
        reg = FirestoreProactiveRegistry("shared_registry")
        doc.get.return_value = _snapshot({"instance": "a"})
        assert reg.get_owner(100) == "a"
        doc.get.return_value = _snapshot(None)
        assert reg.get_owner(100) is None

    def test_errors_propagate(self, db: MagicMock) -> None:
        db.transaction.side_effect = RuntimeError("down")
        with pytest.raises(RuntimeError):
            FirestoreProactiveRegistry("shared_registry").claim(100, "a")
