"""記憶ストア共通の例外定義"""

from log_utils.logger import logger


class StorageLoadError(Exception):
    """永続化先からの読み込みに失敗したことを表す例外

    「データが存在しない」（正常系、``None`` を返す）と区別するために使う。
    この例外を受けた呼び出し側は、空データでキャッシュしたり保存したりしてはならない。
    既存データを空で上書きしてしまうため。
    """


def log_storage_load_failure(message: str, failures: int) -> None:
    """読み込み失敗をログに出す（except 節の中で呼ぶこと）

    失敗が続くとログが traceback で埋まるため、traceback は連続失敗の初回だけ出す。

    Args:
        message: ログメッセージ
        failures: 連続失敗回数
    """
    logger.warning(f"{message}（連続{failures}回目）", exc_info=failures == 1)
