"""ファイル操作ユーティリティ"""

import json
import os
import tempfile
from typing import Any


def atomic_write_json(file_path: str, data: dict[str, Any], *, ensure_ascii: bool = False) -> None:
    """JSON をアトミックに書き込む（NamedTemporaryFile + os.replace）

    Args:
        file_path: 書き込み先のファイルパス
        data: JSON として書き込むデータ
        ensure_ascii: ASCII エスケープを強制するか（デフォルト: False）

    Raises:
        Exception: 書き込みまたは置換に失敗した場合
    """
    parent = os.path.dirname(file_path) or "."
    os.makedirs(parent, exist_ok=True)
    temp_dir = parent
    with tempfile.NamedTemporaryFile(
        "w", dir=temp_dir, delete=False, encoding="utf-8", suffix=".tmp"
    ) as tf:
        json.dump(data, tf, ensure_ascii=ensure_ascii, indent=2)
        temp_name = tf.name
    try:
        os.replace(temp_name, file_path)
    except Exception:
        if os.path.exists(temp_name):
            os.remove(temp_name)
        raise
