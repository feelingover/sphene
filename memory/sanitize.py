"""LLM出力を記憶ストアへ保存する前のサニタイズ処理

LLMが抽出した値はプロンプトへ再注入されるため、型・長さを検証し、
改行や制御文字を除去して間接プロンプトインジェクションの影響を抑える。
"""

import re
import unicodedata
from typing import Any

# 改行・タブなどの空白類は1つの空白にまとめる
_WHITESPACE_RE = re.compile(r"\s+")


def sanitize_llm_text(value: Any, max_length: int) -> str | None:
    """LLMが返した文字列を保存用に正規化する。

    Args:
        value: LLMが返した値（文字列以外は不正として扱う）
        max_length: 許容する最大文字数（超過分は切り詰める）

    Returns:
        正規化済みの文字列。文字列以外・空文字の場合は None。
    """
    if not isinstance(value, str):
        return None
    collapsed = _WHITESPACE_RE.sub(" ", value)
    # 制御文字・書式文字（ゼロ幅文字や双方向制御など）を除去する
    cleaned = "".join(
        ch for ch in collapsed if unicodedata.category(ch) not in ("Cc", "Cf")
    ).strip()
    if not cleaned:
        return None
    return cleaned[:max_length]


def sanitize_llm_text_list(
    values: Any, max_length: int, max_items: int
) -> list[str]:
    """LLMが返した文字列リストを保存用に正規化する。

    Args:
        values: LLMが返した値（リスト以外は空リストとして扱う）
        max_length: 各要素の最大文字数
        max_items: 返す最大件数

    Returns:
        正規化済みの文字列リスト（不正な要素と重複は除外）。
    """
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for value in values:
        text = sanitize_llm_text(value, max_length)
        if text and text not in result:
            result.append(text)
        if len(result) >= max_items:
            break
    return result
