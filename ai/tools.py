"""Google Gen AI SDK ツール定義

LLMが使用できるツール（関数）の定義を集約するモジュール。
新しいSDK (google-genai) に対応。
"""

from typing import Callable
from google.genai import types

from xivapi.client import search_action, search_game_content, search_item, search_recipe

# ツール定義リスト（OpenAI互換形式を維持しつつ、後で変換する）
TOOL_DEFINITIONS_RAW = [
    {
        "name": "search_item",
        "description": (
            "FF14のアイテム情報を検索する。"
            "ユーザーの発言にFF14のインゲームアイテム名らしきものが含まれる場合に使用する。"
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "検索するアイテム名（日本語）"},
                "class_job": {"type": "STRING", "description": "ジョブ名（例: 竜騎士、DRG）"},
                "ilvl_min": {"type": "INTEGER", "description": "IL下限"},
                "ilvl_max": {"type": "INTEGER", "description": "IL上限"},
            },
        },
    },
    {
        "name": "search_action",
        "description": "FF14のアクション（スキル）情報を検索する。",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "検索するアクション名"},
                "class_job": {"type": "STRING", "description": "ジョブ名"},
                "level_min": {"type": "INTEGER", "description": "習得レベル下限"},
                "level_max": {"type": "INTEGER", "description": "習得レベル上限"},
            },
        },
    },
    {
        "name": "search_recipe",
        "description": "FF14の製作レシピを検索する。",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "完成品名"},
                "craft_type": {"type": "STRING", "description": "クラフタージョブ名"},
                "level_min": {"type": "INTEGER", "description": "レシピレベル下限"},
                "level_max": {"type": "INTEGER", "description": "レシピレベル上限"},
            },
        },
    },
    {
        "name": "search_game_content",
        "description": "FF14のゲームコンテンツ（クエスト、マウント等）を検索する。",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "検索する名前"},
                "category": {
                    "type": "STRING",
                    "enum": ["Quest", "Achievement", "Fate", "Mount", "Minion", "Status"],
                    "description": "検索カテゴリ",
                },
            },
            "required": ["category"],
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


def get_tools() -> list[types.Tool]:
    """Google Gen AI SDK形式のツールリストを取得する"""
    function_declarations = []
    for tool in TOOL_DEFINITIONS_RAW:
        # types.FunctionDeclaration を使用
        # パラメータの形式を SDK の期待するものに調整
        params = tool["parameters"]
        
        # SDK の Schema に変換
        schema = types.Schema(
            type=params["type"],
            properties={
                k: types.Schema(type=v["type"], description=v.get("description", ""))
                for k, v in params["properties"].items()
            },
            required=params.get("required", []),
        )

        function_declarations.append(
            types.FunctionDeclaration(
                name=tool["name"],
                description=tool["description"],
                parameters=schema,
            )
        )
    
    return [types.Tool(function_declarations=function_declarations)]
