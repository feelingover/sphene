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
                "ジョブ名やアイテムレベル(IL)の条件が含まれる場合は、"
                "対応するパラメータを使って絞り込み検索を行うこと。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "検索するアイテム名（日本語）。名前で絞らない場合は空文字列を指定",
                    },
                    "class_job": {
                        "type": "string",
                        "description": (
                            "装備可能ジョブで絞り込む場合のジョブ名。"
                            "日本語名（例: 竜騎士、ナイト）または英語略称（例: DRG, PLD）で指定"
                        ),
                    },
                    "ilvl_min": {
                        "type": "integer",
                        "description": "アイテムレベル（IL）の下限値（この値以上）",
                    },
                    "ilvl_max": {
                        "type": "integer",
                        "description": "アイテムレベル（IL）の上限値（この値以下）",
                    },
                },
                "required": [],
            },
        },
    }
]

# ツール名と実行関数のマッピング
TOOL_FUNCTIONS: dict[str, Callable[..., str]] = {
    "search_item": search_item,
}
