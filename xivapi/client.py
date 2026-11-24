"""XIVAPI v2 ゲームデータ検索クライアント

XIVAPI v2 APIを使用してFF14のゲームデータ（アイテム、アクション、レシピ等）を検索する。
将来的に自前DBへの差し替えを見据えた設計。
"""

import json
import re
import threading

import httpx

from log_utils.logger import logger

# 定数
XIVAPI_BASE_URL = "https://v2.xivapi.com/api"
XIVAPI_SEARCH_URL = f"{XIVAPI_BASE_URL}/search"
XIVAPI_ASSET_URL = f"{XIVAPI_BASE_URL}/asset"
XIVAPI_TIMEOUT_SECONDS = 30
XIVAPI_DEFAULT_LIMIT = 5
XIVAPI_FILTERED_LIMIT = 20

# ジョブ名マッピング（日本語名 → 英語略称）
JOB_NAME_MAPPING: dict[str, str] = {
    "ナイト": "PLD",
    "剣術士": "GLA",
    "戦士": "WAR",
    "斧術士": "MRD",
    "暗黒騎士": "DRK",
    "ガンブレイカー": "GNB",
    "白魔道士": "WHM",
    "幻術士": "CNJ",
    "学者": "SCH",
    "占星術師": "AST",
    "賢者": "SGE",
    "モンク": "MNK",
    "格闘士": "PGL",
    "竜騎士": "DRG",
    "槍術士": "LNC",
    "忍者": "NIN",
    "双剣士": "ROG",
    "侍": "SAM",
    "リーパー": "RPR",
    "ヴァイパー": "VPR",
    "吟遊詩人": "BRD",
    "弓術士": "ARC",
    "機工士": "MCH",
    "踊り子": "DNC",
    "黒魔道士": "BLM",
    "呪術士": "THM",
    "召喚士": "SMN",
    "赤魔道士": "RDM",
    "青魔道士": "BLU",
    "ピクトマンサー": "PCT",
}

VALID_JOB_ABBREVIATIONS: set[str] = set(JOB_NAME_MAPPING.values())

# DQLの文字列リテラルを壊す文字（引用符・バックスラッシュ・制御文字）
# XIVAPI v2 のクエリ言語には文字列のエスケープ構文が定義されていないため除去する
_DQL_UNSAFE_CHARS = re.compile(r'["\\\x00-\x1f\x7f]')

# 接続・TLSセッションを再利用するためのプロセス共有クライアント (httpx.Client はスレッドセーフ)
_http_client: httpx.Client | None = None
_http_client_lock = threading.Lock()


def _get_http_client() -> httpx.Client:
    """共有のhttpxクライアントを取得する (初回呼び出し時に生成)"""
    global _http_client
    with _http_client_lock:
        if _http_client is None or _http_client.is_closed:
            _http_client = httpx.Client(timeout=XIVAPI_TIMEOUT_SECONDS)
        return _http_client


def close_http_client() -> None:
    """共有のhttpxクライアントを閉じる (終了時用)"""
    global _http_client
    with _http_client_lock:
        if _http_client is not None:
            _http_client.close()
            _http_client = None


def _dql_str(value: str) -> str:
    """DQLの文字列リテラルとして安全な値にする (引用符等を除去)"""
    return _DQL_UNSAFE_CHARS.sub("", value)


def _dql_int(value: object) -> int | None:
    """DQLに埋め込む数値を整数に正規化する (LLMが600.0や"600"を渡すケースに対応)

    Returns:
        整数値。数値として解釈できない場合はNone (条件を付けない)
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(str(value)))
    except (ValueError, OverflowError):
        logger.warning(f"数値として解釈できない値を無視: {value!r}")
        return None


def _resolve_job_abbreviation(job_name: str) -> str | None:
    """ジョブ名を英語略称に解決する

    Args:
        job_name: 日本語ジョブ名（例: "竜騎士"）または英語略称（例: "DRG"）

    Returns:
        ジョブ略称（大文字）。不明な場合はNone
    """
    if job_name in JOB_NAME_MAPPING:
        return JOB_NAME_MAPPING[job_name]
    # 略称が直接指定された場合（大文字小文字正規化）
    upper_name = job_name.upper()
    if upper_name in VALID_JOB_ABBREVIATIONS:
        return upper_name
    return None


def _build_search_query(
    query: str = "",
    job_abbreviation: str = "",
    ilvl_min: int | None = None,
    ilvl_max: int | None = None,
) -> str:
    """Item検索用のDQLクエリを構築する"""
    parts: list[str] = []
    query = _dql_str(query)
    if query:
        parts.append(f'Name@ja~"{query}"')
    if job_abbreviation:
        parts.append(f'+ClassJobCategory.{job_abbreviation}=1')
    # 0は「指定なし」とみなす（AIのプレースホルダ対策）
    if ilvl_min := _dql_int(ilvl_min):
        parts.append(f"+LevelItem>={ilvl_min}")
    if ilvl_max := _dql_int(ilvl_max):
        parts.append(f"+LevelItem<={ilvl_max}")
    return " ".join(parts)


def _build_icon_url(icon_obj: dict) -> str:
    """XIVAPIのアイコンURLを構築する"""
    path = icon_obj.get("path", "")
    if not path:
        return ""
    # v2のアイコンURL形式: {XIVAPI_ASSET_URL}/{path}?format=png
    return f"{XIVAPI_ASSET_URL}/{path}?format=png"


def _execute_search(
    sheets: str,
    fields: str,
    search_query: str,
    limit: int,
    search_label: str,
) -> dict:
    """XIVAPI v2の検索APIを実行する共通ヘルパー"""
    logger.info(f"XIVAPI v2 {search_label}: query={search_query}, limit={limit}")
    response = _get_http_client().get(
        XIVAPI_SEARCH_URL,
        params={
            "query": search_query,
            "sheets": sheets,
            "fields": fields,
            "language": "ja",
            "limit": limit,
        },
    )
    response.raise_for_status()
    return response.json()


def _build_error_response(query: str, error: str) -> str:
    """エラーレスポンスのJSON文字列を構築する"""
    return json.dumps({"found": False, "query": query, "error": error}, ensure_ascii=False)


def _build_not_found_response(query: str, message: str) -> str:
    """結果なしレスポンスのJSON文字列を構築する"""
    return json.dumps({"found": False, "query": query, "message": message}, ensure_ascii=False)


def _fetch_sheet_row(sheet: str, row_id: int, fields: str = "") -> dict:
    """特定のシートから指定したIDの行データを取得する"""
    params = {"language": "ja"}
    if fields:
        params["fields"] = fields

    url = f"{XIVAPI_BASE_URL}/sheet/{sheet}/{row_id}"
    response = _get_http_client().get(url, params=params)
    response.raise_for_status()
    return response.json()


def _parse_item_result(result: dict) -> dict:
    """XIVAPI v2の検索結果1件をパースする"""
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

    # 名前と説明文（@ja があれば優先）
    name = fields.get("Name@ja") or fields.get("Name", "")
    description = fields.get("Description@ja") or fields.get("Description", "")

    return {
        "id": result.get("row_id"),
        "name": name,
        "ilvl": ilvl,
        "category": category_name,
        "description": description,
        "icon_url": icon_url,
    }


def _resolve_item_conditions(
    query: str,
    class_job: str,
    ilvl_min: int | None,
    ilvl_max: int | None,
) -> tuple[str | None, str, int | None, int | None]:
    """アイテム検索の条件を検証・正規化する

    Args:
        query: 検索キーワード
        class_job: ジョブ名 (略称・日本語名など)
        ilvl_min: アイテムレベル下限
        ilvl_max: アイテムレベル上限

    Returns:
        (エラー応答JSON または None, ジョブ略称, 正規化済みilvl_min, 正規化済みilvl_max)
    """
    job_abbreviation = ""
    if class_job:
        resolved = _resolve_job_abbreviation(class_job)
        if resolved is None:
            error = json.dumps(
                {"found": False, "error": f"不明なジョブ名です: {class_job}"},
                ensure_ascii=False,
            )
            return error, "", ilvl_min, ilvl_max
        job_abbreviation = resolved

    # _build_search_query と同じく、0や解釈できない値は「指定なし」に揃える（空クエリの送信を防ぐ）
    ilvl_min = _dql_int(ilvl_min) or None
    ilvl_max = _dql_int(ilvl_max) or None
    has_filters = bool(job_abbreviation) or ilvl_min is not None or ilvl_max is not None
    if not query and not has_filters:
        error = json.dumps(
            {"found": False, "error": "検索条件を1つ以上指定してください"},
            ensure_ascii=False,
        )
        return error, job_abbreviation, ilvl_min, ilvl_max
    return None, job_abbreviation, ilvl_min, ilvl_max


def _parse_item_results(search_results: list[dict]) -> list[dict]:
    """検索結果から有効なアイテムだけをパースする

    システム予約アイテム (IDが10未満) や名前の無いデータは除外し、
    パースに失敗した行はログを出してスキップする。

    Args:
        search_results: XIVAPI v2 の results 配列

    Returns:
        パース済みアイテムのリスト
    """
    items = []
    for r in search_results:
        f = r.get("fields", {})
        name = f.get("Name@ja") or f.get("Name", "")
        row_id = r.get("row_id", 0)
        # 名前があり、かつIDが10以上のものを有効とみなす
        if name and row_id >= 10:
            try:
                items.append(_parse_item_result(r))
            except Exception as pe:
                logger.error(f"Itemパースエラー (ID:{row_id}): {str(pe)}", exc_info=True)
                continue
    return items


def _build_item_filters(
    job_abbreviation: str, ilvl_min: int | None, ilvl_max: int | None
) -> dict:
    """応答に含める適用済みフィルタ情報を構築する

    Args:
        job_abbreviation: ジョブ略称 (空文字なら未指定)
        ilvl_min: アイテムレベル下限
        ilvl_max: アイテムレベル上限

    Returns:
        指定されたフィルタだけを含む辞書
    """
    filters: dict = {}
    if job_abbreviation:
        filters["class_job"] = job_abbreviation
    if ilvl_min is not None:
        filters["ilvl_min"] = ilvl_min
    if ilvl_max is not None:
        filters["ilvl_max"] = ilvl_max
    return filters


def _build_item_response(
    query: str, items: list[dict], filters: dict | None
) -> str:
    """アイテム検索の成功応答JSONを構築する

    Args:
        query: 検索キーワード
        items: パース済みアイテムのリスト
        filters: 適用したフィルタ情報 (フィルタ未指定ならNone)

    Returns:
        応答のJSON文字列
    """
    response_data: dict = {"found": True, "query": query, "items": items}
    if filters is not None:
        response_data["filters"] = filters
    return json.dumps(response_data, ensure_ascii=False)


def search_item(
    query: str = "",
    class_job: str = "",
    ilvl_min: int | None = None,
    ilvl_max: int | None = None,
) -> str:
    """FF14のアイテムをXIVAPI v2で検索する

    Args:
        query: 検索キーワード
        class_job: 装備可能ジョブ名
        ilvl_min: アイテムレベル下限
        ilvl_max: アイテムレベル上限

    Returns:
        検索結果のJSON文字列
    """
    error, job_abbreviation, ilvl_min, ilvl_max = _resolve_item_conditions(
        query, class_job, ilvl_min, ilvl_max
    )
    if error is not None:
        return error

    has_filters = bool(job_abbreviation) or ilvl_min is not None or ilvl_max is not None
    search_query = _build_search_query(query, job_abbreviation, ilvl_min, ilvl_max)
    limit = XIVAPI_FILTERED_LIMIT if has_filters else XIVAPI_DEFAULT_LIMIT

    try:
        data = _execute_search(
            sheets="Item",
            fields="*",
            search_query=search_query,
            limit=limit,
            search_label="アイテム検索",
        )

        search_results = data.get("results", [])
        if not search_results:
            logger.info(f"XIVAPI v2 検索結果なし: {search_query}")
            return _build_not_found_response(query, "アイテムが見つかりませんでした")

        # システム予約アイテムや無効なデータをフィルタリング
        items = _parse_item_results(search_results)
        if not items:
            return _build_not_found_response(query, "有効なアイテムが見つかりませんでした")

        logger.info(f"XIVAPI v2 検索結果: {len(items)}件")
        filters = _build_item_filters(job_abbreviation, ilvl_min, ilvl_max)
        return _build_item_response(query, items, filters if has_filters else None)

    except httpx.TimeoutException:
        logger.warning(f"XIVAPI v2 タイムアウト: {search_query}")
        return _build_error_response(query, "XIVAPI検索がタイムアウトしました")
    except httpx.HTTPStatusError as e:
        logger.error(f"XIVAPI v2 HTTPエラー: status={e.response.status_code}, query={search_query}", exc_info=True)
        return _build_error_response(query, "XIVAPIとの通信でエラーが発生しました")
    except Exception as e:
        logger.error(f"XIVAPI v2 予期せぬエラー: {str(e)}", exc_info=True)
        return _build_error_response(query, "アイテム検索中にエラーが発生しました")


def _build_action_query(
    query: str = "",
    job_abbreviation: str = "",
    level_min: int | None = None,
    level_max: int | None = None,
) -> str:
    """Action検索用のDQLクエリを構築する"""
    parts: list[str] = []
    query = _dql_str(query)
    if query:
        parts.append(f'Name@ja~"{query}"')
    if job_abbreviation:
        parts.append(f'+ClassJob.Abbreviation="{job_abbreviation}"')
    # 0は「指定なし」とみなす
    if level_min := _dql_int(level_min):
        parts.append(f"+ClassJobLevel>={level_min}")
    if level_max := _dql_int(level_max):
        parts.append(f"+ClassJobLevel<={level_max}")
    return " ".join(parts)


def _parse_action_result(result: dict) -> dict:
    """Action詳細データをパースする"""
    fields = result.get("fields", {})

    class_job_obj = fields.get("ClassJob", {})
    class_job = ""
    if isinstance(class_job_obj, dict):
        class_job = class_job_obj.get("fields", {}).get("Abbreviation", "")

    category_obj = fields.get("ActionCategory", {})
    action_category = ""
    if isinstance(category_obj, dict):
        action_category = category_obj.get("fields", {}).get("Name", "")

    icon_obj = fields.get("Icon", {})
    icon_url = _build_icon_url(icon_obj) if isinstance(icon_obj, dict) else ""

    name = fields.get("Name@ja") or fields.get("Name", "")
    
    description = result.get("transient", {}).get("Description", "")
    if not description:
        description = fields.get("Description@ja") or fields.get("Description", "")

    return {
        "id": result.get("row_id"),
        "name": name,
        "description": description,
        "class_job_level": fields.get("ClassJobLevel"),
        "class_job": class_job,
        "action_category": action_category,
        "icon_url": icon_url,
    }


def _resolve_action_conditions(
    query: str,
    class_job: str,
    level_min: int | None,
    level_max: int | None,
) -> tuple[str | None, str, int | None, int | None]:
    """アクション検索の条件（ジョブ名・レベル範囲）を検証・正規化する

    Args:
        query: 検索キーワード
        class_job: ジョブ名
        level_min: 習得レベル下限
        level_max: 習得レベル上限

    Returns:
        (エラーJSON or None, ジョブ略称, 正規化したレベル下限, 正規化したレベル上限)
    """
    job_abbreviation = ""
    if class_job:
        resolved = _resolve_job_abbreviation(class_job)
        if resolved is None:
            error = json.dumps({"found": False, "error": f"不明なジョブ名です: {class_job}"}, ensure_ascii=False)
            return error, "", level_min, level_max
        job_abbreviation = resolved

    # _build_action_query と同じく、0や解釈できない値は「指定なし」に揃える（空クエリの送信を防ぐ）
    level_min = _dql_int(level_min) or None
    level_max = _dql_int(level_max) or None
    has_filters = bool(job_abbreviation) or level_min is not None or level_max is not None
    if not query and not has_filters:
        error = json.dumps({"found": False, "error": "検索条件を1つ以上指定してください"}, ensure_ascii=False)
        return error, job_abbreviation, level_min, level_max
    return None, job_abbreviation, level_min, level_max


def _filter_valid_actions(search_results: list[dict]) -> list[dict]:
    """システム予約アクションや無効なデータを除外する

    名前があり、かつIDが10以上のものを有効とみなす。

    Args:
        search_results: XIVAPIの検索結果

    Returns:
        有効なアクションの検索結果
    """
    filtered_results = []
    for res in search_results:
        f = res.get("fields", {})
        name = f.get("Name@ja") or f.get("Name", "")
        row_id = res.get("row_id", 0)
        if name and row_id >= 10:
            filtered_results.append(res)
    return filtered_results


def _parse_actions_with_details(filtered_results: list[dict]) -> list[dict]:
    """上位3件は詳細を取得して説明文を補完し、残りは検索結果のままパースする

    詳細取得に失敗した場合は検索結果のデータでパースする。

    Args:
        filtered_results: 有効なアクションの検索結果

    Returns:
        パース済みのアクション情報のリスト
    """
    actions = []
    for res in filtered_results[:3]:
        try:
            row_id = res.get("row_id")
            if row_id:
                detail = _fetch_sheet_row("Action", row_id)
                actions.append(_parse_action_result(detail))
            else:
                actions.append(_parse_action_result(res))
        except Exception:
            actions.append(_parse_action_result(res))

    for res in filtered_results[3:]:
        actions.append(_parse_action_result(res))
    return actions


def search_action(
    query: str = "",
    class_job: str = "",
    level_min: int | None = None,
    level_max: int | None = None,
) -> str:
    """FF14のアクションをXIVAPI v2で検索する（2段階取得で説明文を補完）

    Args:
        query: 検索キーワード
        class_job: ジョブ名
        level_min: 習得レベル下限
        level_max: 習得レベル上限

    Returns:
        検索結果のJSON文字列
    """
    error, job_abbreviation, level_min, level_max = _resolve_action_conditions(
        query, class_job, level_min, level_max
    )
    if error is not None:
        return error

    has_filters = bool(job_abbreviation) or level_min is not None or level_max is not None
    search_query = _build_action_query(query, job_abbreviation, level_min, level_max)
    limit = XIVAPI_FILTERED_LIMIT if has_filters else XIVAPI_DEFAULT_LIMIT

    try:
        data = _execute_search(sheets="Action", fields="*", search_query=search_query, limit=limit, search_label="アクション検索")
        search_results = data.get("results", [])
        if not search_results:
            return _build_not_found_response(query, "アクションが見つかりませんでした")

        filtered_results = _filter_valid_actions(search_results)
        if not filtered_results:
            return _build_not_found_response(query, "有効なアクションが見つかりませんでした")

        actions = _parse_actions_with_details(filtered_results)
        return json.dumps({"found": True, "query": query, "actions": actions}, ensure_ascii=False)

    except Exception as e:
        logger.error(f"Action検索エラー: {str(e)}", exc_info=True)
        return _build_error_response(query, "アクション検索中にエラーが発生しました")


# クラフタージョブ名マッピング
CRAFT_TYPE_MAPPING: dict[str, str] = {
    "木工師": "Carpenter",
    "鍛冶師": "Smithing",
    "甲冑師": "Armorcraft",
    "彫金師": "Goldsmithing",
    "革細工師": "Leatherworking",
    "裁縫師": "Clothcraft",
    "錬金術師": "Alchemy",
    "調理師": "Cooking",
}

VALID_CRAFT_TYPES: set[str] = set(CRAFT_TYPE_MAPPING.values())


def _resolve_craft_type(craft_name: str) -> str | None:
    if craft_name in CRAFT_TYPE_MAPPING:
        return CRAFT_TYPE_MAPPING[craft_name]
    for valid in VALID_CRAFT_TYPES:
        if craft_name.lower() == valid.lower():
            return valid
    return None


def _build_recipe_query(query: str = "", craft_type: str = "", level_min: int | None = None, level_max: int | None = None) -> str:
    parts: list[str] = []
    query = _dql_str(query)
    if query:
        parts.append(f'ItemResult.Name@ja~"{query}"')
    if craft_type:
        parts.append(f'+CraftType.Name="{craft_type}"')
    if (level_min := _dql_int(level_min)) is not None:
        parts.append(f"+RecipeLevelTable.ClassJobLevel>={level_min}")
    if (level_max := _dql_int(level_max)) is not None:
        parts.append(f"+RecipeLevelTable.ClassJobLevel<={level_max}")
    return " ".join(parts)


def _is_positive_number(value: object) -> bool:
    """正の数値か（bool・None・文字列などは False）

    Args:
        value: 判定する値

    Returns:
        int/float で 0 より大きければ True
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _parse_recipe_result(result: dict) -> dict:
    fields = result.get("fields", {})
    item_result_obj = fields.get("ItemResult", {})
    item_name = item_result_obj.get("fields", {}).get("Name", "") if isinstance(item_result_obj, dict) else ""
    craft_type_obj = fields.get("CraftType", {})
    craft_type = craft_type_obj.get("fields", {}).get("Name", "") if isinstance(craft_type_obj, dict) else ""
    level_obj = fields.get("RecipeLevelTable", {})
    recipe_level = level_obj.get("fields", {}).get("ClassJobLevel") if isinstance(level_obj, dict) else None
    
    amount_result = fields.get("AmountResult")
    ingredients = []
    ingredient_items = fields.get("Ingredient", [])
    ingredient_amounts = fields.get("AmountIngredient", [])

    if isinstance(ingredient_items, list) and isinstance(ingredient_amounts, list):
        for item, amount in zip(ingredient_items, ingredient_amounts):
            # 素材の空き枠は amount=0 / None で返るため、数値以外も含めて読み飛ばす
            if not _is_positive_number(amount) or not isinstance(item, dict):
                continue
            item_id = item.get("value", 0)
            if _is_positive_number(item_id):
                name = item.get("fields", {}).get("Name", f"Unknown(ID:{item_id})")
                ingredients.append({"name": name, "amount": amount})

    return {"item_name": item_name, "craft_type": craft_type, "recipe_level": recipe_level, "amount_result": amount_result, "ingredients": ingredients}


def search_recipe(query: str = "", craft_type: str = "", level_min: int | None = None, level_max: int | None = None) -> str:
    resolved_craft_type = ""
    if craft_type:
        resolved = _resolve_craft_type(craft_type)
        if resolved is None:
            return json.dumps({"found": False, "error": f"不明なクラフタージョブです: {craft_type}"}, ensure_ascii=False)
        resolved_craft_type = resolved

    # _build_recipe_query と同じく、解釈できない値は「指定なし」に揃える（空クエリの送信を防ぐ）
    level_min = _dql_int(level_min)
    level_max = _dql_int(level_max)
    has_filters = bool(resolved_craft_type) or level_min is not None or level_max is not None
    if not query and not has_filters:
        return json.dumps({"found": False, "error": "検索条件を1つ以上指定してください"}, ensure_ascii=False)

    search_query = _build_recipe_query(query, resolved_craft_type, level_min, level_max)
    limit = XIVAPI_FILTERED_LIMIT if has_filters else XIVAPI_DEFAULT_LIMIT

    try:
        data = _execute_search(sheets="Recipe", fields="ItemResult.Name,CraftType.Name,RecipeLevelTable.ClassJobLevel,AmountResult,Ingredient,AmountIngredient", search_query=search_query, limit=limit, search_label="レシピ検索")
        results = data.get("results", [])
        if not results:
            return _build_not_found_response(query, "レシピが見つかりませんでした")
        recipes = []
        for r in results:
            try:
                recipes.append(_parse_recipe_result(r))
            except Exception:
                logger.warning(f"レシピ結果のパースに失敗したためスキップ: row_id={r.get('row_id') if isinstance(r, dict) else None}", exc_info=True)
                continue
        return json.dumps({"found": True, "query": query, "recipes": recipes}, ensure_ascii=False)
    except Exception as e:
        logger.error(f"レシピ検索エラー: query={query}: {e}", exc_info=True)
        return _build_error_response(query, "レシピ検索中にエラーが発生しました")


# ゲームコンテンツ検索
GAME_CONTENT_CATEGORIES: dict[str, dict] = {
    "Quest": {"sheet": "Quest", "fields": "Name,Name@ja,Levelmain,ClassJobCategory.Name", "name_field": "Name", "level_field": "Levelmain"},
    "Achievement": {"sheet": "Achievement", "fields": "Name,Name@ja,Description,Description@ja,Points,AchievementCategory.Name", "name_field": "Name", "level_field": None},
    "Fate": {"sheet": "Fate", "fields": "Name,Name@ja,Description,Description@ja,Lvl", "name_field": "Name", "level_field": "Lvl"},
    "Mount": {"sheet": "Mount", "fields": "Name,Name@ja,Description,Description@ja", "name_field": "Name", "level_field": None},
    "Minion": {"sheet": "Companion", "fields": "Name,Name@ja,Description,Description@ja", "name_field": "Name", "level_field": None},
    "Status": {"sheet": "Status", "fields": "Name,Name@ja,Description,Description@ja", "name_field": "Name", "level_field": None},
}
VALID_GAME_CONTENT_CATEGORIES = set(GAME_CONTENT_CATEGORIES.keys())

def _build_game_content_query(name_field: str, query: str = "", level_field: str | None = None, level_min: int | None = None, level_max: int | None = None) -> str:
    parts: list[str] = []
    query = _dql_str(query)
    if query:
        field = f"{name_field}@ja" if name_field == "Name" else name_field
        parts.append(f'{field}~"{query}"')
    if level_field:
        if (level_min := _dql_int(level_min)) is not None:
            parts.append(f"+{level_field}>={level_min}")
        if (level_max := _dql_int(level_max)) is not None:
            parts.append(f"+{level_field}<={level_max}")
    return " ".join(parts)

def _parse_game_content_result(result: dict, category_config: dict) -> dict:
    fields = result.get("fields", {})
    name = fields.get("Name@ja") or fields.get("Name", "")
    parsed: dict = {"name": name}
    description = fields.get("Description@ja") or fields.get("Description", "")
    if description: parsed["description"] = description
    level_field = category_config.get("level_field")
    if level_field and level_field in fields: parsed["level"] = fields[level_field]
    if "Points" in fields: parsed["points"] = fields["Points"]
    ach_cat = fields.get("AchievementCategory", {})
    if isinstance(ach_cat, dict) and ach_cat:
        parsed["achievement_category"] = ach_cat.get("fields", {}).get("Name", "")
    cjc = fields.get("ClassJobCategory", {})
    if isinstance(cjc, dict) and cjc:
        parsed["class_job_category"] = cjc.get("fields", {}).get("Name", "")
    icon_obj = fields.get("Icon", {})
    if isinstance(icon_obj, dict) and icon_obj:
        icon_url = _build_icon_url(icon_obj)
        if icon_url: parsed["icon_url"] = icon_url
    return parsed

def search_game_content(query: str = "", category: str = "", level_min: int | None = None, level_max: int | None = None) -> str:
    if not category or category not in GAME_CONTENT_CATEGORIES:
        return json.dumps({"found": False, "error": "不明なカテゴリです"}, ensure_ascii=False)
    config = GAME_CONTENT_CATEGORIES[category]
    search_query = _build_game_content_query(config["name_field"], query, config.get("level_field"), level_min, level_max)
    try:
        data = _execute_search(sheets=config["sheet"], fields=config["fields"], search_query=search_query, limit=XIVAPI_DEFAULT_LIMIT, search_label=f"{category}検索")
        results = data.get("results", [])
        if not results: return _build_not_found_response(query, "コンテンツが見つかりませんでした")
        contents = [_parse_game_content_result(r, config) for r in results]
        return json.dumps({"found": True, "query": query, "contents": contents}, ensure_ascii=False)
    except Exception as e:
        logger.error(f"コンテンツ検索エラー: query={query}, category={category}: {e}", exc_info=True)
        return _build_error_response(query, "コンテンツ検索中にエラーが発生しました")
