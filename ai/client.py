from openai import OpenAI

import config
from log_utils.logger import logger


# OpenAIクライアントの初期化
def create_client() -> OpenAI:
    """OpenAIのクライアントインスタンスを作成する

    Returns:
        OpenAI: OpenAIのクライアントインスタンス
    """
    logger.info("OpenAIクライアントを初期化しています")
    return OpenAI(api_key=config.OPENAI_API_KEY)


# グローバルなクライアントインスタンス
client = create_client()
