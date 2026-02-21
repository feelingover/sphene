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
    if config.LOG_FORMAT == "json":
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
    return logging.getLogger(name)


# デフォルトのロガーインスタンスを作成
logger = setup_logger()
