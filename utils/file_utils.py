"""ファイル操作ユーティリティ"""

import json
import os
import stat
import tempfile
from typing import Any

# 新規ファイル作成時のデフォルト権限（umask 適用前）
_DEFAULT_FILE_MODE = 0o666


def _resolve_target_mode(file_path: str) -> int:
    """置き換え後のファイルに付与する権限を決める

    既存ファイルがあればその権限を維持し、なければ通常の open() と同じく
    umask を適用したデフォルト権限を返す。

    Args:
        file_path: 書き込み先のファイルパス

    Returns:
        int: 付与する権限ビット
    """
    try:
        return stat.S_IMODE(os.stat(file_path).st_mode)
    except FileNotFoundError:
        umask = os.umask(0)
        os.umask(umask)
        return _DEFAULT_FILE_MODE & ~umask


def _fsync_directory(directory: str) -> None:
    """ディレクトリエントリ（rename 結果）をディスクに永続化する

    Windows などディレクトリを open できない環境では何もしない。

    Args:
        directory: fsync 対象のディレクトリ
    """
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_json(file_path: str, data: dict[str, Any], *, ensure_ascii: bool = False) -> None:
    """JSON をアトミックに書き込む（一時ファイル + fsync + os.replace）

    - 一時ファイルに書き込んだあと flush/fsync してから置き換えるため、
      電源断などで空ファイルや途中までのファイルが残らない
    - 書き込み・置き換えのどこで失敗しても一時ファイルは削除される
    - 既存ファイルの権限を維持する（新規作成時は umask 準拠）

    Args:
        file_path: 書き込み先のファイルパス
        data: JSON として書き込むデータ
        ensure_ascii: ASCII エスケープを強制するか（デフォルト: False）

    Raises:
        Exception: 書き込みまたは置換に失敗した場合
    """
    parent = os.path.dirname(file_path) or "."
    os.makedirs(parent, exist_ok=True)
    mode = _resolve_target_mode(file_path)

    fd, temp_name = tempfile.mkstemp(dir=parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tf:
            json.dump(data, tf, ensure_ascii=ensure_ascii, indent=2)
            tf.flush()
            os.fsync(tf.fileno())
        os.chmod(temp_name, mode)
        os.replace(temp_name, file_path)
    except BaseException:
        try:
            os.remove(temp_name)
        except FileNotFoundError:
            pass
        raise
    _fsync_directory(parent)
