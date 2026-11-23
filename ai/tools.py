"""Google Gen AI SDK ツール定義

LLMが使用できるツール（関数）の定義を集約するモジュール。
新しいSDK (google-genai) に対応。
"""

from typing import Any, Callable
from google.genai import types

from xivapi.client import (
    CRAFT_TYPE_MAPPING,
    GAME_CONTENT_CATEGORIES,
    search_action,
    search_game_content,
    search_item,
    search_recipe,
)

# クラフタージョブ名は日本語名・英語名のどちらでも解決できる
_CRAFT_TYPE_ENUM: list[str] = [*CRAFT_TYPE_MAPPING.keys(), *CRAFT_TYPE_MAPPING.values()]

# ツール定義リスト（OpenAI互換形式を維持しつつ、後で変換する）
TOOL_DEFINITIONS_RAW: list[dict[str, Any]] = [
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
                "craft_type": {
                    "type": "STRING",
                    "enum": _CRAFT_TYPE_ENUM,
                    "description": "クラフタージョブ名",
                },
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
                    "enum": list(GAME_CONTENT_CATEGORIES.keys()),
                    "description": "検索カテゴリ",
                },
                "level_min": {
                    "type": "INTEGER",
                    "description": "レベル下限（Quest / Fate のみ有効）",
                },
                "level_max": {
                    "type": "INTEGER",
                    "description": "レベル上限（Quest / Fate のみ有効）",
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


def _to_schema(params: dict[str, Any]) -> types.Schema:
    """生のパラメータ定義をSDKのSchemaに変換する (enumも引き継ぐ)"""
    return types.Schema(
        type=params["type"],
        properties={
            k: types.Schema(
                type=v["type"],
                description=v.get("description", ""),
                enum=v.get("enum"),
            )
            for k, v in params["properties"].items()
        },
        required=params.get("required", []),
    )


def get_tools() -> list[types.Tool]:
    """Google Gen AI SDK形式のツールリストを取得する"""
    function_declarations = [
        types.FunctionDeclaration(
            name=tool["name"],
            description=tool["description"],
            parameters=_to_schema(tool["parameters"]),
        )
        for tool in TOOL_DEFINITIONS_RAW
    ]
    return [types.Tool(function_declarations=function_declarations)]
