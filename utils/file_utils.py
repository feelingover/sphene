"""ファイル操作ユーティリティ"""

import json
import os
import secrets
import stat
from typing import Any, Optional

import config

# 一時ファイル名の衝突時に再試行する上限
_TEMP_CREATE_ATTEMPTS = 100


def local_storage_path(filename: str) -> str:
    """ローカルストレージ（LOCAL_STORAGE_DIR）配下のファイルパスを返す

    Args:
        filename: ファイル名

    Returns:
        str: LOCAL_STORAGE_DIR と結合したパス
    """
    return os.path.join(config.LOCAL_STORAGE_DIR, filename)


def _existing_mode(file_path: str) -> Optional[int]:
    """既存ファイルの権限ビットを返す（存在しなければ None）

    Args:
        file_path: 対象のファイルパス

    Returns:
        Optional[int]: 権限ビット。ファイルが存在しない場合は None
    """
    try:
        return stat.S_IMODE(os.stat(file_path).st_mode)
    except FileNotFoundError:
        return None


def _create_temp(parent: str) -> tuple[int, str]:
    """親ディレクトリに一時ファイルを排他作成する

    mode 0o666 で作成しカーネルに umask を適用させる。umask をプロセス全体で
    読み書きしないため、複数スレッドから並行に呼ばれても安全。

    Args:
        parent: 一時ファイルを作るディレクトリ

    Returns:
        tuple[int, str]: ファイルディスクリプタとパス

    Raises:
        FileExistsError: 名前の衝突が上限回数続いた場合
    """
    for _ in range(_TEMP_CREATE_ATTEMPTS):
        name = os.path.join(parent, f".{secrets.token_hex(8)}.tmp")
        try:
            return os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666), name
        except FileExistsError:
            continue
    raise FileExistsError(f"一時ファイル名の衝突が続きました: {parent}")


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
    mode = _existing_mode(file_path)

    fd, temp_name = _create_temp(parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tf:
            json.dump(data, tf, ensure_ascii=ensure_ascii, indent=2)
            tf.flush()
            os.fsync(tf.fileno())
        if mode is not None:
            os.chmod(temp_name, mode)
        os.replace(temp_name, file_path)
    except BaseException:
        try:
            os.remove(temp_name)
        except FileNotFoundError:
            pass
        raise
    _fsync_directory(parent)
