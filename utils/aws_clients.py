import boto3
from botocore.client import BaseClient

from log_utils.logger import logger

_s3_client: BaseClient | None = None


def get_s3_client() -> BaseClient:
    """
    シングルトンなS3クライアントインスタンスを取得する

    Returns:
        BaseClient: boto3 S3クライアントインスタンス
    """
    global _s3_client
    if _s3_client is None:
        logger.info("boto3 S3クライアントを初期化しています")
        try:
            _s3_client = boto3.client("s3")
            logger.info("boto3 S3クライアントの初期化に成功")
        except Exception as e:
            logger.critical(
                f"boto3 S3クライアントの初期化に失敗: {str(e)}", exc_info=True
            )
            # ここでエラーを再raiseするか、Noneを返すか、あるいは
            # アプリケーションの要件に応じて処理を決める必要がある。
            # 今回はエラーをraiseして、起動時などに検知できるようにする。
            raise RuntimeError(f"Failed to initialize S3 client: {str(e)}") from e
    return _s3_client
