"""utils/file_utils.py の単体テスト"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from utils.file_utils import atomic_write_json


class TestAtomicWriteJson:
    """atomic_write_json のテスト"""

    def test_writes_json_file(self, tmp_path: Path) -> None:
        """正常にJSONファイルが書き込まれる"""
        file_path = str(tmp_path / "output.json")
        data = {"key": "value", "number": 42}

        atomic_write_json(file_path, data)

        with open(file_path, encoding="utf-8") as f:
            result = json.load(f)
        assert result == data

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        """親ディレクトリが存在しない場合に自動作成される"""
        file_path = str(tmp_path / "subdir" / "nested" / "output.json")
        data = {"foo": "bar"}

        atomic_write_json(file_path, data)

        assert os.path.exists(file_path)
        with open(file_path, encoding="utf-8") as f:
            result = json.load(f)
        assert result == data

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        """既存ファイルを上書きできる"""
        file_path = str(tmp_path / "output.json")
        atomic_write_json(file_path, {"v": 1})
        atomic_write_json(file_path, {"v": 2})

        with open(file_path, encoding="utf-8") as f:
            result = json.load(f)
        assert result == {"v": 2}

    def test_no_partial_file_on_replace_failure(self, tmp_path: Path) -> None:
        """os.replace 失敗時にテンポラリファイルが削除される"""
        file_path = str(tmp_path / "output.json")
        data = {"key": "value"}

        with patch("os.replace", side_effect=OSError("replace failed")):
            with pytest.raises(OSError, match="replace failed"):
                atomic_write_json(file_path, data)

        # テンポラリファイル（.tmp）が残っていない
        tmp_files = [n for n in os.listdir(tmp_path) if n.endswith(".tmp")]
        assert tmp_files == []

    def test_path_without_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ディレクトリなしのパス（カレントディレクトリ）でも動作する"""
        monkeypatch.chdir(tmp_path)
        file_path = "plain_output.json"
        data = {"direct": True}

        atomic_write_json(file_path, data)

        with open(file_path, encoding="utf-8") as f:
            result = json.load(f)
        assert result == data

    def test_ensure_ascii_false_by_default(self, tmp_path: Path) -> None:
        """デフォルトで日本語がエスケープされない"""
        file_path = str(tmp_path / "output.json")
        data = {"name": "スフェーン"}

        atomic_write_json(file_path, data)

        raw = Path(file_path).read_text(encoding="utf-8")
        assert "スフェーン" in raw
        assert r"\u" not in raw

    def test_ensure_ascii_true_escapes_unicode(self, tmp_path: Path) -> None:
        """ensure_ascii=True で日本語がエスケープされる"""
        file_path = str(tmp_path / "output.json")
        data = {"name": "スフェーン"}

        atomic_write_json(file_path, data, ensure_ascii=True)

        raw = Path(file_path).read_text(encoding="utf-8")
        assert "スフェーン" not in raw
        assert r"\u" in raw

    def test_nested_dict(self, tmp_path: Path) -> None:
        """ネストされた辞書を正しく書き込める"""
        file_path = str(tmp_path / "nested.json")
        data: dict = {"outer": {"inner": [1, 2, 3], "flag": True}}

        atomic_write_json(file_path, data)

        with open(file_path, encoding="utf-8") as f:
            result = json.load(f)
        assert result == data


class TestAtomicWriteJsonDurability:
    """atomic_write_json の耐障害性（fsync・一時ファイル掃除・権限維持）"""

    def test_fsyncs_before_replace(self, tmp_path: Path) -> None:
        """置き換え前に一時ファイルを fsync する"""
        file_path = str(tmp_path / "output.json")
        calls: list[str] = []
        real_fsync = os.fsync
        real_replace = os.replace

        def _fsync(fd: int) -> None:
            calls.append("fsync")
            real_fsync(fd)

        def _replace(src: str, dst: str) -> None:
            calls.append("replace")
            real_replace(src, dst)

        with patch("os.fsync", side_effect=_fsync), patch("os.replace", side_effect=_replace):
            atomic_write_json(file_path, {"k": 1})

        assert calls.index("fsync") < calls.index("replace")

    def test_removes_temp_file_on_dump_failure(self, tmp_path: Path) -> None:
        """json.dump が失敗しても一時ファイルが残らず、既存ファイルも壊れない"""
        file_path = str(tmp_path / "output.json")
        atomic_write_json(file_path, {"v": 1})

        with pytest.raises(TypeError):
            atomic_write_json(file_path, {"bad": object()})

        assert [n for n in os.listdir(tmp_path) if n.endswith(".tmp")] == []
        with open(file_path, encoding="utf-8") as f:
            assert json.load(f) == {"v": 1}

    def test_removes_temp_file_on_fsync_failure(self, tmp_path: Path) -> None:
        """fsync が失敗しても一時ファイルが残らない"""
        file_path = str(tmp_path / "output.json")

        with patch("os.fsync", side_effect=OSError("fsync failed")):
            with pytest.raises(OSError, match="fsync failed"):
                atomic_write_json(file_path, {"k": 1})

        assert [n for n in os.listdir(tmp_path) if n.endswith(".tmp")] == []
        assert not os.path.exists(file_path)

    @pytest.mark.skipif(os.name == "nt", reason="POSIX パーミッション前提")
    def test_preserves_existing_file_mode(self, tmp_path: Path) -> None:
        """既存ファイルの権限が維持される"""
        file_path = tmp_path / "output.json"
        file_path.write_text("{}", encoding="utf-8")
        os.chmod(file_path, 0o640)

        atomic_write_json(str(file_path), {"v": 2})

        assert (os.stat(file_path).st_mode & 0o777) == 0o640

    @pytest.mark.skipif(os.name == "nt", reason="POSIX パーミッション前提")
    def test_new_file_follows_umask(self, tmp_path: Path) -> None:
        """新規作成時は mkstemp の 0600 ではなく umask 準拠の権限になる"""
        file_path = tmp_path / "output.json"
        old_umask = os.umask(0o022)
        try:
            atomic_write_json(str(file_path), {"v": 1})
        finally:
            os.umask(old_umask)

        assert (os.stat(file_path).st_mode & 0o777) == 0o644
