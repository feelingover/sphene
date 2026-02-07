"""OpenAI Function Calling ツール定義

LLMが使用できるツール（関数）の定義を集約するモジュール。
新しいツールを追加する場合は、TOOL_DEFINITIONSリストに追加し、
TOOL_FUNCTIONS辞書に対応する実行関数を登録する。
"""

from typing import Callable

from openai.types.chat import ChatCompletionToolParam

from xivapi.client import search_item

# ツール定義リスト
TOOL_DEFINITIONS: list[ChatCompletionToolParam] = [
    {
        "type": "function",
        "function": {
            "name": "search_item",
            "description": (
                "FF14のアイテム情報を検索する。"
                "ユーザーの発言にFF14のインゲームアイテム名らしきものが含まれる場合に使用する。"
                "一般的な単語（鉄、木材など）の場合は、FF14の文脈で話されている場合のみ使用すること。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "検索するアイテム名（日本語）",
                    }
                },
                "required": ["query"],
            },
        },
    }
]

# ツール名と実行関数のマッピング
TOOL_FUNCTIONS: dict[str, Callable[..., str]] = {
    "search_item": search_item,
}
