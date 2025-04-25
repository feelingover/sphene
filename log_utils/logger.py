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


def setup_logger(name: str = "sphene") -> logging.Logger:
    """アプリケーション用のロガーをセットアップする

    Args:
        name: ロガー名

    Returns:
        logging.Logger: 設定されたロガーインスタンス
    """
    # 環境変数からログレベルを取得
    log_level = get_log_level(config.LOG_LEVEL)

    # ロギングの基本設定
    logging.basicConfig(
        level=log_level, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    return logging.getLogger(name)


# デフォルトのロガーインスタンスを作成
logger = setup_logger()
