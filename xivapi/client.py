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
XIVAPI_FILTERED_LIMIT = 20

# ジョブ名マッピング（日本語名 → 英語略称）
JOB_NAME_MAPPING: dict[str, str] = {
    # タンク
    "ナイト": "PLD", "戦士": "WAR", "暗黒騎士": "DRK", "ガンブレイカー": "GNB",
    # ヒーラー
    "白魔道士": "WHM", "学者": "SCH", "占星術師": "AST", "賢者": "SGE",
    # メレーDPS
    "モンク": "MNK", "竜騎士": "DRG", "忍者": "NIN", "侍": "SAM",
    "リーパー": "RPR", "ヴァイパー": "VPR",
    # レンジDPS
    "吟遊詩人": "BRD", "機工士": "MCH", "踊り子": "DNC",
    # キャスターDPS
    "黒魔道士": "BLM", "召喚士": "SMN", "赤魔道士": "RDM", "ピクトマンサー": "PCT",
    # リミテッドジョブ
    "青魔道士": "BLU",
    # クラス（基本クラス）
    "剣術士": "GLA", "格闘士": "PGL", "斧術士": "MRD", "槍術士": "LNC",
    "弓術士": "ARC", "幻術士": "CNJ", "呪術士": "THM", "巴術士": "ACN", "双剣士": "ROG",
}

VALID_JOB_ABBREVIATIONS: set[str] = {
    "PLD", "WAR", "DRK", "GNB", "WHM", "SCH", "AST", "SGE",
    "MNK", "DRG", "NIN", "SAM", "RPR", "VPR",
    "BRD", "MCH", "DNC", "BLM", "SMN", "RDM", "PCT", "BLU",
    "GLA", "PGL", "MRD", "LNC", "ARC", "CNJ", "THM", "ACN", "ROG",
}


def _resolve_job_abbreviation(job_name: str) -> str | None:
    """ジョブ名を英語略称に解決する

    Args:
        job_name: 日本語ジョブ名（例: "竜騎士"）または英語略称（例: "DRG"）

    Returns:
        英語略称（例: "DRG"）。不明なジョブ名の場合はNone
    """
    if job_name in JOB_NAME_MAPPING:
        return JOB_NAME_MAPPING[job_name]
    upper = job_name.upper()
    if upper in VALID_JOB_ABBREVIATIONS:
        return upper
    return None


def _build_search_query(
    query: str = "",
    job_abbreviation: str = "",
    ilvl_min: int | None = None,
    ilvl_max: int | None = None,
) -> str:
    """XIVAPI v2の検索クエリ文字列を構築する

    Args:
        query: アイテム名の検索文字列
        job_abbreviation: ジョブ英語略称（例: "DRG"）
        ilvl_min: アイテムレベル下限
        ilvl_max: アイテムレベル上限

    Returns:
        XIVAPI v2のクエリ文字列
    """
    parts: list[str] = []
    if query:
        parts.append(f'+Name~"{query}"')
    if job_abbreviation:
        parts.append(f"+ClassJobCategory.{job_abbreviation}=1")
    if ilvl_min is not None:
        parts.append(f"+LevelItem>={ilvl_min}")
    if ilvl_max is not None:
        parts.append(f"+LevelItem<={ilvl_max}")
    return " ".join(parts)


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


def search_item(
    query: str = "",
    class_job: str = "",
    ilvl_min: int | None = None,
    ilvl_max: int | None = None,
) -> str:
    """FF14のアイテムをXIVAPI v2で検索する

    アイテム名、装備可能ジョブ、アイテムレベル範囲を組み合わせて検索できる。

    Args:
        query: 検索するアイテム名（日本語）。名前で絞らない場合は空文字列
        class_job: 装備可能ジョブ名。日本語名（例: "竜騎士"）または英語略称（例: "DRG"）
        ilvl_min: アイテムレベルの下限値（この値以上）
        ilvl_max: アイテムレベルの上限値（この値以下）

    Returns:
        検索結果のJSON文字列（OpenAI tool resultとして使用）
    """
    # ジョブ名の解決
    job_abbreviation = ""
    if class_job:
        resolved = _resolve_job_abbreviation(class_job)
        if resolved is None:
            return json.dumps(
                {"found": False, "error": f"不明なジョブ名です: {class_job}"},
                ensure_ascii=False,
            )
        job_abbreviation = resolved

    # パラメータが1つも指定されていない場合はエラー
    has_filters = bool(job_abbreviation) or ilvl_min is not None or ilvl_max is not None
    if not query and not has_filters:
        return json.dumps(
            {"found": False, "error": "検索条件を1つ以上指定してください"},
            ensure_ascii=False,
        )

    # クエリ文字列の構築
    search_query = _build_search_query(query, job_abbreviation, ilvl_min, ilvl_max)
    limit = XIVAPI_FILTERED_LIMIT if has_filters else XIVAPI_DEFAULT_LIMIT

    logger.info(f"XIVAPI v2 アイテム検索: query={search_query}, limit={limit}")

    try:
        with httpx.Client(timeout=XIVAPI_TIMEOUT_SECONDS) as http_client:
            response = http_client.get(
                XIVAPI_SEARCH_URL,
                params={
                    "query": search_query,
                    "sheets": "Item",
                    "fields": "Name,Icon,Description,LevelItem,ItemUICategory.Name",
                    "language": "ja",
                    "limit": limit,
                },
            )
            response.raise_for_status()
            data = response.json()

        results = data.get("results", [])
        if not results:
            logger.info(f"XIVAPI v2 検索結果なし: {search_query}")
            return json.dumps(
                {"found": False, "query": query, "message": "アイテムが見つかりませんでした"},
                ensure_ascii=False,
            )

        items = [_parse_item_result(r) for r in results]
        logger.info(f"XIVAPI v2 検索結果: {len(items)}件")

        response_data: dict = {"found": True, "query": query, "items": items}

        # フィルタ条件をレスポンスに含める
        if has_filters:
            filters: dict = {}
            if job_abbreviation:
                filters["class_job"] = job_abbreviation
            if ilvl_min is not None:
                filters["ilvl_min"] = ilvl_min
            if ilvl_max is not None:
                filters["ilvl_max"] = ilvl_max
            response_data["filters"] = filters

        return json.dumps(response_data, ensure_ascii=False)

    except httpx.TimeoutException:
        logger.warning(f"XIVAPI v2 タイムアウト: {search_query}")
        return json.dumps(
            {"found": False, "query": query, "error": "XIVAPI検索がタイムアウトしました"},
            ensure_ascii=False,
        )
    except httpx.HTTPStatusError as e:
        logger.error(
            f"XIVAPI v2 HTTPエラー: status={e.response.status_code}, query={search_query}",
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
