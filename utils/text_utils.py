from typing import Optional

import config
from ai.client import client as aiclient
from log_utils.logger import logger

# 定数の定義
PREVIEW_LENGTH = 30  # プレビュー表示時の文字数上限


def truncate_text(text: str, max_length: int = PREVIEW_LENGTH) -> str:
    """テキストを指定された長さに切り詰めて表示用のプレビューを作成する

    Args:
        text: 元のテキスト
        max_length: 最大長さ

    Returns:
        str: 切り詰められたテキスト（長い場合は...付き）
    """
    if not text:
        return ""
    return text[:max_length] + "..." if len(text) > max_length else text


async def translate_to_english(text: str) -> Optional[str]:
    """テキストを英語に翻訳する

    Args:
        text: 翻訳するテキスト

    Returns:
        str: 翻訳されたテキスト、エラー時はNone
    """
    try:
        logger.info(f"英語翻訳リクエスト: {truncate_text(text)}")

        # OpenAI APIで翻訳実行
        result = aiclient.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "あなたは翻訳者です。与えられたテキストを英語に翻訳してください。",
                },
                {"role": "user", "content": text},
            ],
        )

        translated_text = result.choices[0].message.content
        if translated_text:
            logger.info(f"翻訳結果: {truncate_text(translated_text)}")
            return translated_text
        else:
            logger.warning("翻訳APIからの応答が空でした")
            return None
    except Exception as e:
        logger.error(f"翻訳処理でエラーが発生: {str(e)}", exc_info=True)
        return None
