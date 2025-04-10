import logging


def setup_logger(name: str = "sphene", level: int = logging.INFO) -> logging.Logger:
    """アプリケーション用のロガーをセットアップする

    Args:
        name: ロガー名
        level: ロギングレベル

    Returns:
        logging.Logger: 設定されたロガーインスタンス
    """
    # ロギングの基本設定
    logging.basicConfig(
        level=level, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    return logging.getLogger(name)


# デフォルトのロガーインスタンスを作成
logger = setup_logger()
