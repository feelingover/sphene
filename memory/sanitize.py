"""LLM出力を記憶ストアへ保存する前のサニタイズ処理

LLMが抽出した値はプロンプトへ再注入されるため、型・長さを検証し、
改行や制御文字を除去して間接プロンプトインジェクションの影響を抑える。
"""

import re
import unicodedata
from typing import Any

# 改行・タブなどの空白類は1つの空白にまとめる
_WHITESPACE_RE = re.compile(r"\s+")

_MAX_AUTHOR_NAME_LENGTH = 32
# 発言者・ロール表記の偽装に使える記号（NFKC正規化後に照合する）
# "Foo[BOT]" や "名前: 本文" の区切りを名前側で作らせない。
# NFKC で ［］：﹕︓ などは ASCII に寄るため、寄らない類似文字だけ追加で列挙する
_AUTHOR_NAME_SPOOF_RE = re.compile(
    r"[\[\]【】〔〕〖〗〘〙〚〛⟦⟧<>«»‹›:∶꞉˸ː]"
)


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


def safe_author_name(author_name: str) -> str:
    """発言者名をプロンプトに埋め込める形に正規化する（行・ロール表記の偽装対策）

    NFKC正規化のうえ、ロール表記（``[BOT]``）や ``名前: 本文`` の区切りを
    偽装できる括弧・コロン類を除去し、改行・制御文字をつぶして長さを制限する。
    プロンプト上で同じ人物が経路ごとに別名にならないよう、名前を埋め込む
    すべての箇所でこの関数を通すこと。

    Args:
        author_name: Discordの表示名

    Returns:
        正規化済みの名前。空になった場合は "ユーザー"。
    """
    name: object = author_name
    if isinstance(name, str):
        name = _AUTHOR_NAME_SPOOF_RE.sub("", unicodedata.normalize("NFKC", name))
    return sanitize_llm_text(name, _MAX_AUTHOR_NAME_LENGTH) or "ユーザー"
