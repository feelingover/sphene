"""XIVAPI v2 アイテム検索クライアント

XIVAPI v2 APIを使用してFF14のアイテム情報を検索する。
将来的に自前DBへの差し替えを見据えた設計。
"""

import json

import httpx

from log_utils.logger import logger

# 定数
XIVAPI_BASE_URL = "https://v2.xivapi.com/api"
XIVAPI_SEARCH_URL = f"{XIVAPI_BASE_URL}/search"
XIVAPI_ASSET_URL = f"{XIVAPI_BASE_URL}/asset"
XIVAPI_TIMEOUT_SECONDS = 10
XIVAPI_DEFAULT_LIMIT = 5


def _build_icon_url(icon_field: dict) -> str:
    """アイコンフィールドからアイコンURLを構築する

    Args:
        icon_field: XIVAPI v2のIconフィールドオブジェクト

    Returns:
        アイコン画像のURL。pathが存在しない場合は空文字列
    """
    path = icon_field.get("path", "")
    if path:
        return f"{XIVAPI_ASSET_URL}/{path}?format=png"
    return ""


def _parse_item_result(result: dict) -> dict:
    """XIVAPI v2の検索結果1件をパースする

    Args:
        result: XIVAPI v2の検索結果オブジェクト

    Returns:
        パース済みアイテム情報の辞書
    """
    fields = result.get("fields", {})

    # LevelItemはオブジェクト（.valueにアイテムレベル数値が入っている）
    level_item = fields.get("LevelItem", {})
    ilvl = level_item.get("value") if isinstance(level_item, dict) else level_item

    # ItemUICategory.fields.Name からカテゴリ名を取得
    category_obj = fields.get("ItemUICategory", {})
    category_name = ""
    if isinstance(category_obj, dict):
        category_fields = category_obj.get("fields", {})
        category_name = category_fields.get("Name", "")

    # アイコンURL構築
    icon_obj = fields.get("Icon", {})
    icon_url = _build_icon_url(icon_obj) if isinstance(icon_obj, dict) else ""

    return {
        "id": result.get("row_id"),
        "name": fields.get("Name", ""),
        "ilvl": ilvl,
        "category": category_name,
        "description": fields.get("Description", ""),
        "icon_url": icon_url,
    }


def search_item(query: str) -> str:
    """FF14のアイテムをXIVAPI v2で検索する

    Args:
        query: 検索するアイテム名（日本語）

    Returns:
        検索結果のJSON文字列（OpenAI tool resultとして使用）
    """
    logger.info(f"XIVAPI v2 アイテム検索: {query}")

    try:
        with httpx.Client(timeout=XIVAPI_TIMEOUT_SECONDS) as http_client:
            response = http_client.get(
                XIVAPI_SEARCH_URL,
                params={
                    "query": f'Name~"{query}"',
                    "sheets": "Item",
                    "fields": "Name,Icon,Description,LevelItem,ItemUICategory.Name",
                    "language": "ja",
                    "limit": XIVAPI_DEFAULT_LIMIT,
                },
            )
            response.raise_for_status()
            data = response.json()

        results = data.get("results", [])
        if not results:
            logger.info(f"XIVAPI v2 検索結果なし: {query}")
            return json.dumps(
                {"found": False, "query": query, "message": "アイテムが見つかりませんでした"},
                ensure_ascii=False,
            )

        items = [_parse_item_result(r) for r in results]
        logger.info(f"XIVAPI v2 検索結果: {len(items)}件")

        return json.dumps(
            {"found": True, "query": query, "items": items},
            ensure_ascii=False,
        )

    except httpx.TimeoutException:
        logger.warning(f"XIVAPI v2 タイムアウト: {query}")
        return json.dumps(
            {"found": False, "query": query, "error": "XIVAPI検索がタイムアウトしました"},
            ensure_ascii=False,
        )
    except httpx.HTTPStatusError as e:
        logger.error(
            f"XIVAPI v2 HTTPエラー: status={e.response.status_code}, query={query}",
            exc_info=True,
        )
        return json.dumps(
            {"found": False, "query": query, "error": "XIVAPIとの通信でエラーが発生しました"},
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error(f"XIVAPI v2 予期せぬエラー: {str(e)}", exc_info=True)
        return json.dumps(
            {"found": False, "query": query, "error": "アイテム検索中にエラーが発生しました"},
            ensure_ascii=False,
        )
