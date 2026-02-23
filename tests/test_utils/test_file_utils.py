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
        tmp_files = list(tmp_path.glob("*.tmp"))
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
        data = {"name": "アサヒ"}

        atomic_write_json(file_path, data)

        raw = Path(file_path).read_text(encoding="utf-8")
        assert "アサヒ" in raw
        assert r"\u" not in raw

    def test_ensure_ascii_true_escapes_unicode(self, tmp_path: Path) -> None:
        """ensure_ascii=True で日本語がエスケープされる"""
        file_path = str(tmp_path / "output.json")
        data = {"name": "アサヒ"}

        atomic_write_json(file_path, data, ensure_ascii=True)

        raw = Path(file_path).read_text(encoding="utf-8")
        assert "アサヒ" not in raw
        assert r"\u" in raw

    def test_nested_dict(self, tmp_path: Path) -> None:
        """ネストされた辞書を正しく書き込める"""
        file_path = str(tmp_path / "nested.json")
        data: dict = {"outer": {"inner": [1, 2, 3], "flag": True}}

        atomic_write_json(file_path, data)

        with open(file_path, encoding="utf-8") as f:
            result = json.load(f)
        assert result == data
