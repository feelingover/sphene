from openai import OpenAI

import config
from log_utils.logger import logger


# OpenAIクライアントの初期化
def create_client() -> OpenAI:
    """OpenAIのクライアントインスタンスを作成する

    Returns:
        OpenAI: OpenAIのクライアントインスタンス

    Raises:
        RuntimeError: クライアント初期化時にエラーが発生した場合
    """
    logger.info("OpenAIクライアントを初期化しています")
    try:
        return OpenAI(api_key=config.OPENAI_API_KEY)
    except Exception as e:
        error_msg = f"OpenAIクライアントの初期化に失敗しました: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise RuntimeError(error_msg) from e


# グローバルなクライアントインスタンス
client = create_client()
