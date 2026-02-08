import asyncio

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


async def translate_text(text: str, target_language: str = "english") -> str | None:
    """テキストを指定された言語に翻訳する

    Args:
        text: 翻訳するテキスト
        target_language: 翻訳先の言語 ("english" または "japanese")

    Returns:
        str | None: 翻訳されたテキスト、エラー時はNone
    """
    language_configs = {
        "english": {
            "system_prompt": "あなたは翻訳者です。与えられたテキストを英語に翻訳してください。",
            "log_prefix": "英語",
        },
        "japanese": {
            "system_prompt": "あなたは翻訳者です。与えられたテキストを日本語に翻訳してください。",
            "log_prefix": "日本語",
        },
    }

    if target_language not in language_configs:
        logger.error(f"サポートされていない言語: {target_language}")
        return None

    config_data = language_configs[target_language]

    try:
        logger.info(f"{config_data['log_prefix']}翻訳リクエスト: {truncate_text(text)}")

        def _sync_translate():
            return aiclient.chat.completions.create(
                model=config.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": config_data["system_prompt"]},
                    {"role": "user", "content": text},
                ],
            )

        result = await asyncio.to_thread(_sync_translate)

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


async def translate_to_english(text: str) -> str | None:
    """テキストを英語に翻訳する

    Args:
        text: 翻訳するテキスト

    Returns:
        str | None: 翻訳されたテキスト、エラー時はNone
    """
    return await translate_text(text, "english")


async def translate_to_japanese(text: str) -> str | None:
    """テキストを日本語に翻訳する

    Args:
        text: 翻訳するテキスト

    Returns:
        str | None: 翻訳されたテキスト、エラー時はNone
    """
    return await translate_text(text, "japanese")
