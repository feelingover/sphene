import asyncio

import config
from ai.client import _get_genai_client, get_model_name
from log_utils.logger import logger

PREVIEW_LENGTH = 30


def truncate_text(text: str, max_length: int = PREVIEW_LENGTH) -> str:
    if not text:
        return ""
    return text[:max_length] + "..." if len(text) > max_length else text


def split_message(text: str, max_length: int = 1900) -> list[str]:
    if len(text) <= max_length:
        return [text]
    chunks = []
    curr_text = text
    while curr_text:
        if len(curr_text) <= max_length:
            chunks.append(curr_text)
            break
        split_index = curr_text.rfind("\n", 0, max_length)
        if split_index == -1:
            split_index = max_length
        chunks.append(curr_text[:split_index])
        if curr_text[split_index] == "\n":
             curr_text = curr_text[split_index + 1:]
        else:
             curr_text = curr_text[split_index:]
    return chunks


async def translate_text(text: str, target_language: str = "english") -> str | None:
    """Google Gen AI SDK を使用した翻訳"""
    language_configs = {
        "english": "あなたは翻訳者です。与えられたテキストを英語に翻訳してください。",
        "japanese": "あなたは翻訳者です。与えられたテキストを日本語に翻訳してください。",
    }

    if target_language not in language_configs:
        return None

    try:
        def _sync_translate():
            client = _get_genai_client()
            model_id = get_model_name()
            prompt = f"{language_configs[target_language]}\n\nText: {text}"
            return client.models.generate_content(model=model_id, contents=prompt)

        result = await asyncio.to_thread(_sync_translate)
        return result.text
    except Exception as e:
        logger.error(f"翻訳エラー: {e}")
        return None


async def translate_to_english(text: str) -> str | None:
    return await translate_text(text, "english")


async def translate_to_japanese(text: str) -> str | None:
    return await translate_text(text, "japanese")
