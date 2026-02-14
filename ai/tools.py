"""OpenAI Function Calling ツール定義

LLMが使用できるツール（関数）の定義を集約するモジュール。
新しいツールを追加する場合は、TOOL_DEFINITIONSリストに追加し、
TOOL_FUNCTIONS辞書に対応する実行関数を登録する。
"""

from typing import Callable

from openai.types.chat import ChatCompletionToolParam

from xivapi.client import search_action, search_game_content, search_item, search_recipe

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
                        "description": "アイテムレベル（IL）の下限値。不明な場合はパラメータ自体を含めないこと（0を指定しない）",
                    },
                    "ilvl_max": {
                        "type": "integer",
                        "description": "アイテムレベル（IL）の上限値。不明な場合はパラメータ自体を含めないこと（0を指定しない）",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_action",
            "description": (
                "FF14のアクション（スキル）情報を検索する。"
                "ユーザーの発言にFF14のスキル名やアクション名が含まれる場合に使用する。"
                "「竜騎士のスキル一覧」「ミダレセツゲッカってどんなスキル？」等の質問に対応する。"
                "ジョブ名や習得レベルの条件が含まれる場合は、"
                "対応するパラメータを使って絞り込み検索を行うこと。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "検索するアクション名（日本語）。名前で絞らない場合は空文字列を指定",
                    },
                    "class_job": {
                        "type": "string",
                        "description": (
                            "ジョブで絞り込む場合のジョブ名。"
                            "日本語名（例: 竜騎士、ナイト）または英語略称（例: DRG, PLD）で指定"
                        ),
                    },
                    "level_min": {
                        "type": "integer",
                        "description": "習得レベルの下限値。不明な場合はパラメータ自体を含めないこと（0を指定しない）",
                    },
                    "level_max": {
                        "type": "integer",
                        "description": "習得レベルの上限値。不明な場合はパラメータ自体を含めないこと（0を指定しない）",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_recipe",
            "description": (
                "FF14の製作レシピを検索する。"
                "ユーザーが「〇〇のレシピ」「レベル90の木工レシピ」等と尋ねた場合に使用する。"
                "クラフタージョブ名やレシピレベルの条件が含まれる場合は、"
                "対応するパラメータを使って絞り込み検索を行うこと。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "検索する完成品名（日本語）。名前で絞らない場合は空文字列を指定",
                    },
                    "craft_type": {
                        "type": "string",
                        "description": (
                            "クラフタージョブで絞り込む場合のジョブ名。"
                            "日本語名（例: 鍛冶師、木工師）または英語名（例: Smithing, Carpenter）で指定"
                        ),
                    },
                    "level_min": {
                        "type": "integer",
                        "description": "レシピレベルの下限値（この値以上）",
                    },
                    "level_max": {
                        "type": "integer",
                        "description": "レシピレベルの上限値（この値以下）",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_game_content",
            "description": (
                "FF14のゲームコンテンツを検索する。"
                "クエスト、アチーブメント、F.A.T.E.、マウント、ミニオン、ステータス（バフ/デバフ）を検索できる。"
                "categoryパラメータで検索対象を指定すること（必須）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "検索する名前（日本語）。名前で絞らない場合は空文字列を指定",
                    },
                    "category": {
                        "type": "string",
                        "enum": ["Quest", "Achievement", "Fate", "Mount", "Minion", "Status"],
                        "description": "検索対象のカテゴリ（必須）",
                    },
                    "level_min": {
                        "type": "integer",
                        "description": "レベルの下限値（Quest, Fateのみ有効）",
                    },
                    "level_max": {
                        "type": "integer",
                        "description": "レベルの上限値（Quest, Fateのみ有効）",
                    },
                },
                "required": ["category"],
            },
        },
    },
]

# ツール名と実行関数のマッピング
TOOL_FUNCTIONS: dict[str, Callable[..., str]] = {
    "search_item": search_item,
    "search_action": search_action,
    "search_recipe": search_recipe,
    "search_game_content": search_game_content,
}
