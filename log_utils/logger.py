import logging

import config


def get_log_level(level_name: str) -> int:
    """文字列のログレベル名をloggingモジュールの定数に変換する

    Args:
        level_name: ログレベル名（"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"）

    Returns:
        int: loggingモジュールのログレベル定数
    """
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    return level_map.get(level_name.upper(), logging.INFO)


def _create_formatter() -> logging.Formatter:
    """ログフォーマッターを生成する。

    LOG_FORMAT=json の場合は Google Cloud Logging 向け JSON フォーマッター、
    それ以外は人間が読みやすいテキストフォーマッターを返す。

    Returns:
        logging.Formatter: 設定されたフォーマッターインスタンス
    """
    if config.LOG_FORMAT.strip().lower() == "json":
        from datetime import datetime, timezone

        from pythonjsonlogger.json import JsonFormatter

        class _GCLJsonFormatter(JsonFormatter):
            def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
                return datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="seconds")

        return _GCLJsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            rename_fields={
                "asctime": "time",
                "levelname": "severity",
                "name": "logger",
            },
        )
    return logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")


# サードパーティライブラリの最低ログレベル。LOG_LEVEL=DEBUG でもこれより詳細には出さない
# （HTTP のリクエスト/レスポンスや Gateway のペイロードがログに流れるのを防ぐ）
_THIRD_PARTY_MIN_LEVELS: dict[str, int] = {
    "discord": logging.INFO,
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
    "urllib3": logging.WARNING,
    "google": logging.WARNING,
    "grpc": logging.WARNING,
}


def _configure_third_party_loggers(app_level: int) -> None:
    """サードパーティロガーのレベルを、アプリのレベルと最低レベルの厳しい方に揃える

    Args:
        app_level: アプリケーションのログレベル
    """
    for name, min_level in _THIRD_PARTY_MIN_LEVELS.items():
        logging.getLogger(name).setLevel(max(app_level, min_level))


def setup_logger(name: str = "sphene") -> logging.Logger:
    """アプリケーション用のロガーをセットアップする

    Args:
        name: ロガー名

    Returns:
        logging.Logger: 設定されたロガーインスタンス
    """
    log_level = get_log_level(config.LOG_LEVEL)

    handler = logging.StreamHandler()
    handler.setFormatter(_create_formatter())

    logging.basicConfig(level=log_level, handlers=[handler])
    _configure_third_party_loggers(log_level)
    return logging.getLogger(name)


# デフォルトのロガーインスタンスを作成
logger = setup_logger(config.INSTANCE_NAME)
