"""XIVAPI v2 クライアントのテスト"""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from xivapi.client import (
    GAME_CONTENT_CATEGORIES,
    VALID_GAME_CONTENT_CATEGORIES,
    XIVAPI_DEFAULT_LIMIT,
    XIVAPI_FILTERED_LIMIT,
    XIVAPI_SEARCH_URL,
    _build_action_query,
    _build_game_content_query,
    _build_recipe_query,
    _build_search_query,
    _parse_action_result,
    _parse_game_content_result,
    _parse_recipe_result,
    _resolve_craft_type,
    _resolve_job_abbreviation,
    search_action,
    search_game_content,
    search_item,
    search_recipe,
)


# =============================================================================
# _resolve_job_abbreviation テスト
# =============================================================================
class TestResolveJobAbbreviation:
    """ジョブ名解決ヘルパーのテスト"""

    def test_japanese_job_name(self):
        assert _resolve_job_abbreviation("竜騎士") == "DRG"

    def test_japanese_tank(self):
        assert _resolve_job_abbreviation("ナイト") == "PLD"

    def test_japanese_healer(self):
        assert _resolve_job_abbreviation("白魔道士") == "WHM"

    def test_japanese_caster(self):
        assert _resolve_job_abbreviation("黒魔道士") == "BLM"

    def test_japanese_class(self):
        assert _resolve_job_abbreviation("槍術士") == "LNC"

    def test_english_abbreviation_uppercase(self):
        assert _resolve_job_abbreviation("DRG") == "DRG"

    def test_english_abbreviation_lowercase(self):
        assert _resolve_job_abbreviation("drg") == "DRG"

    def test_english_abbreviation_mixedcase(self):
        assert _resolve_job_abbreviation("Pld") == "PLD"

    def test_unknown_name_returns_none(self):
        assert _resolve_job_abbreviation("不明なジョブ") is None

    def test_empty_string_returns_none(self):
        assert _resolve_job_abbreviation("") is None


# =============================================================================
# _build_search_query テスト
# =============================================================================
class TestBuildSearchQuery:
    """クエリ文字列構築ヘルパーのテスト"""

    def test_name_only(self):
        result = _build_search_query(query="エクサーク")
        assert result == '+Name~"エクサーク"'

    def test_job_only(self):
        result = _build_search_query(job_abbreviation="DRG")
        assert result == "+ClassJobCategory.DRG=1"

    def test_ilvl_min_only(self):
        result = _build_search_query(ilvl_min=500)
        assert result == "+LevelItem>=500"

    def test_ilvl_max_only(self):
        result = _build_search_query(ilvl_max=550)
        assert result == "+LevelItem<=550"

    def test_ilvl_range(self):
        result = _build_search_query(ilvl_min=500, ilvl_max=550)
        assert result == "+LevelItem>=500 +LevelItem<=550"

    def test_all_parameters(self):
        result = _build_search_query(
            query="エクサーク", job_abbreviation="DRG", ilvl_min=500, ilvl_max=550
        )
        assert result == '+Name~"エクサーク" +ClassJobCategory.DRG=1 +LevelItem>=500 +LevelItem<=550'

    def test_name_and_job(self):
        result = _build_search_query(query="エクサーク", job_abbreviation="PLD")
        assert result == '+Name~"エクサーク" +ClassJobCategory.PLD=1'

    def test_job_and_ilvl(self):
        result = _build_search_query(job_abbreviation="WHM", ilvl_min=600)
        assert result == "+ClassJobCategory.WHM=1 +LevelItem>=600"

    def test_no_parameters(self):
        result = _build_search_query()
        assert result == ""


# =============================================================================
# search_item 統合テスト
# =============================================================================
def _make_mock_response(results: list, status_code: int = 200) -> MagicMock:
    """モックHTTPレスポンスを作成するヘルパー"""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = {"results": results}
    mock_response.raise_for_status.return_value = None
    return mock_response


def _make_item_result(
    row_id: int = 1,
    name: str = "テストアイテム",
    ilvl: int = 500,
    category: str = "胴防具",
    description: str = "テスト説明",
) -> dict:
    """テスト用のXIVAPI検索結果1件を作成するヘルパー"""
    return {
        "row_id": row_id,
        "fields": {
            "Name": name,
            "LevelItem": {"value": ilvl},
            "ItemUICategory": {"fields": {"Name": category}},
            "Description": description,
            "Icon": {"path": "icon/test.tex"},
        },
    }


class TestSearchItem:
    """search_item()の統合テスト"""

    @patch("xivapi.client.httpx.Client")
    def test_name_only_search_backward_compatible(self, mock_client_class):
        """名前のみ検索（既存動作の後方互換確認）"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response(
            [_make_item_result(name="エクサークコート")]
        )

        result = json.loads(search_item(query="エクサーク"))

        assert result["found"] is True
        assert result["query"] == "エクサーク"
        assert len(result["items"]) == 1
        assert result["items"][0]["name"] == "エクサークコート"
        assert "filters" not in result

        # limit=5 で呼ばれることを確認
        call_args = mock_client.get.call_args
        assert call_args.kwargs["params"]["limit"] == XIVAPI_DEFAULT_LIMIT

    @patch("xivapi.client.httpx.Client")
    def test_job_filter_search(self, mock_client_class):
        """ジョブフィルタ付き検索"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response(
            [_make_item_result(name="竜騎士の装備")]
        )

        result = json.loads(search_item(query="装備", class_job="竜騎士"))

        assert result["found"] is True
        assert result["filters"]["class_job"] == "DRG"

        call_args = mock_client.get.call_args
        assert "+ClassJobCategory.DRG=1" in call_args.kwargs["params"]["query"]
        assert call_args.kwargs["params"]["limit"] == XIVAPI_FILTERED_LIMIT

    @patch("xivapi.client.httpx.Client")
    def test_ilvl_range_search(self, mock_client_class):
        """IL範囲付き検索"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response(
            [_make_item_result(ilvl=520)]
        )

        result = json.loads(search_item(query="", class_job="DRG", ilvl_min=500, ilvl_max=550))

        assert result["found"] is True
        assert result["filters"]["class_job"] == "DRG"
        assert result["filters"]["ilvl_min"] == 500
        assert result["filters"]["ilvl_max"] == 550

        call_args = mock_client.get.call_args
        query_str = call_args.kwargs["params"]["query"]
        assert "+ClassJobCategory.DRG=1" in query_str
        assert "+LevelItem>=500" in query_str
        assert "+LevelItem<=550" in query_str

    @patch("xivapi.client.httpx.Client")
    def test_all_filters_combined(self, mock_client_class):
        """全フィルタ組み合わせ"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response(
            [_make_item_result(name="エクサークコート", ilvl=520)]
        )

        result = json.loads(
            search_item(query="エクサーク", class_job="竜騎士", ilvl_min=500, ilvl_max=550)
        )

        assert result["found"] is True
        assert result["query"] == "エクサーク"
        assert result["filters"]["class_job"] == "DRG"
        assert result["filters"]["ilvl_min"] == 500
        assert result["filters"]["ilvl_max"] == 550

    @patch("xivapi.client.httpx.Client")
    def test_pure_filter_search_no_name(self, mock_client_class):
        """名前なしの純フィルタ検索"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response(
            [_make_item_result(name="装備A"), _make_item_result(row_id=2, name="装備B")]
        )

        result = json.loads(search_item(class_job="DRG", ilvl_min=500))

        assert result["found"] is True
        assert result["query"] == ""
        assert len(result["items"]) == 2
        assert result["filters"]["class_job"] == "DRG"

    def test_unknown_job_name_error(self):
        """不明ジョブ名エラー"""
        result = json.loads(search_item(query="装備", class_job="不明ジョブ"))

        assert result["found"] is False
        assert "不明なジョブ名です" in result["error"]
        assert "不明ジョブ" in result["error"]

    def test_no_parameters_error(self):
        """パラメータなしエラー"""
        result = json.loads(search_item())

        assert result["found"] is False
        assert "検索条件を1つ以上指定してください" in result["error"]

    @patch("xivapi.client.httpx.Client")
    def test_no_results(self, mock_client_class):
        """結果なし"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response([])

        result = json.loads(search_item(query="存在しないアイテム"))

        assert result["found"] is False
        assert "見つかりませんでした" in result["message"]

    @patch("xivapi.client.httpx.Client")
    def test_timeout_error(self, mock_client_class):
        """タイムアウトエラー"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.TimeoutException("timeout")

        result = json.loads(search_item(query="テスト"))

        assert result["found"] is False
        assert "タイムアウト" in result["error"]

    @patch("xivapi.client.httpx.Client")
    def test_http_error(self, mock_client_class):
        """HTTPエラー"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_client.get.return_value = mock_response
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=mock_response
        )

        result = json.loads(search_item(query="テスト"))

        assert result["found"] is False
        assert "エラーが発生しました" in result["error"]

    @patch("xivapi.client.httpx.Client")
    def test_filtered_limit_used_with_filters(self, mock_client_class):
        """フィルタ時のlimit=20確認"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response([_make_item_result()])

        search_item(class_job="DRG")

        call_args = mock_client.get.call_args
        assert call_args.kwargs["params"]["limit"] == XIVAPI_FILTERED_LIMIT

    @patch("xivapi.client.httpx.Client")
    def test_default_limit_without_filters(self, mock_client_class):
        """フィルタなし時のlimit=5確認"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response([_make_item_result()])

        search_item(query="テスト")

        call_args = mock_client.get.call_args
        assert call_args.kwargs["params"]["limit"] == XIVAPI_DEFAULT_LIMIT

    @patch("xivapi.client.httpx.Client")
    def test_english_abbreviation_in_class_job(self, mock_client_class):
        """英語略称でのジョブ指定"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response([_make_item_result()])

        result = json.loads(search_item(class_job="pld"))

        assert result["found"] is True
        assert result["filters"]["class_job"] == "PLD"

    @patch("xivapi.client.httpx.Client")
    def test_ilvl_min_only_filter(self, mock_client_class):
        """IL下限のみ指定"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response([_make_item_result()])

        result = json.loads(search_item(ilvl_min=600))

        assert result["found"] is True
        assert result["filters"]["ilvl_min"] == 600
        assert "ilvl_max" not in result["filters"]

    @patch("xivapi.client.httpx.Client")
    def test_ilvl_max_only_filter(self, mock_client_class):
        """IL上限のみ指定"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response([_make_item_result()])

        result = json.loads(search_item(ilvl_max=100))

        assert result["found"] is True
        assert result["filters"]["ilvl_max"] == 100
        assert "ilvl_min" not in result["filters"]


# =============================================================================
# _build_action_query テスト
# =============================================================================
class TestBuildActionQuery:
    """アクション検索クエリ構築ヘルパーのテスト"""

    def test_name_only(self):
        result = _build_action_query(query="ボーパルスラスト")
        assert result == '+Name~"ボーパルスラスト"'

    def test_job_only(self):
        result = _build_action_query(job_abbreviation="DRG")
        assert result == '+ClassJob.Abbreviation="DRG"'

    def test_level_min_only(self):
        result = _build_action_query(level_min=50)
        assert result == "+ClassJobLevel>=50"

    def test_level_max_only(self):
        result = _build_action_query(level_max=60)
        assert result == "+ClassJobLevel<=60"

    def test_level_range(self):
        result = _build_action_query(level_min=50, level_max=60)
        assert result == "+ClassJobLevel>=50 +ClassJobLevel<=60"

    def test_all_parameters(self):
        result = _build_action_query(
            query="スラスト", job_abbreviation="DRG", level_min=50, level_max=60
        )
        assert result == '+Name~"スラスト" +ClassJob.Abbreviation="DRG" +ClassJobLevel>=50 +ClassJobLevel<=60'

    def test_name_and_job(self):
        result = _build_action_query(query="ケアル", job_abbreviation="WHM")
        assert result == '+Name~"ケアル" +ClassJob.Abbreviation="WHM"'

    def test_no_parameters(self):
        result = _build_action_query()
        assert result == ""


# =============================================================================
# _parse_action_result テスト
# =============================================================================
def _make_action_result(
    name: str = "テストアクション",
    description: str = "テスト説明",
    class_job_level: int = 50,
    class_job_abbr: str = "DRG",
    action_category: str = "アビリティ",
) -> dict:
    """テスト用のXIVAPIアクション検索結果1件を作成するヘルパー"""
    return {
        "row_id": 100,
        "fields": {
            "Name": name,
            "Description": description,
            "ClassJobLevel": class_job_level,
            "ClassJob": {"fields": {"Abbreviation": class_job_abbr}},
            "ActionCategory": {"fields": {"Name": action_category}},
            "Icon": {"path": "icon/action_test.tex"},
        },
    }


class TestParseActionResult:
    """_parse_action_result()のテスト"""

    def test_full_result(self):
        result = _parse_action_result(_make_action_result())
        assert result["name"] == "テストアクション"
        assert result["description"] == "テスト説明"
        assert result["class_job_level"] == 50
        assert result["class_job"] == "DRG"
        assert result["action_category"] == "アビリティ"
        assert "icon_url" in result
        assert "action_test.tex" in result["icon_url"]

    def test_missing_class_job(self):
        data = {
            "fields": {
                "Name": "テスト",
                "Description": "",
                "ClassJobLevel": 1,
                "ClassJob": {},
                "ActionCategory": {},
                "Icon": {},
            },
        }
        result = _parse_action_result(data)
        assert result["class_job"] == ""
        assert result["action_category"] == ""
        assert result["icon_url"] == ""

    def test_non_dict_class_job(self):
        data = {
            "fields": {
                "Name": "テスト",
                "ClassJob": "not_a_dict",
                "ActionCategory": "not_a_dict",
                "Icon": "not_a_dict",
            },
        }
        result = _parse_action_result(data)
        assert result["class_job"] == ""
        assert result["action_category"] == ""
        assert result["icon_url"] == ""


# =============================================================================
# search_action 統合テスト
# =============================================================================
class TestSearchAction:
    """search_action()の統合テスト"""

    @patch("xivapi.client.httpx.Client")
    def test_name_only_search(self, mock_client_class):
        """名前のみ検索"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response(
            [_make_action_result(name="ボーパルスラスト")]
        )

        result = json.loads(search_action(query="ボーパルスラスト"))

        assert result["found"] is True
        assert result["query"] == "ボーパルスラスト"
        assert len(result["actions"]) == 1
        assert result["actions"][0]["name"] == "ボーパルスラスト"
        assert "filters" not in result

        call_args = mock_client.get.call_args
        assert call_args.kwargs["params"]["limit"] == XIVAPI_DEFAULT_LIMIT

    @patch("xivapi.client.httpx.Client")
    def test_job_filter_search(self, mock_client_class):
        """ジョブフィルタ付き検索"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response(
            [_make_action_result(name="桜花狂咲", class_job_abbr="DRG")]
        )

        result = json.loads(search_action(query="桜花", class_job="竜騎士"))

        assert result["found"] is True
        assert result["filters"]["class_job"] == "DRG"

        call_args = mock_client.get.call_args
        assert '+ClassJob.Abbreviation="DRG"' in call_args.kwargs["params"]["query"]
        assert call_args.kwargs["params"]["limit"] == XIVAPI_FILTERED_LIMIT

    @patch("xivapi.client.httpx.Client")
    def test_level_range_search(self, mock_client_class):
        """レベル範囲付き検索"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response(
            [_make_action_result(class_job_level=55)]
        )

        result = json.loads(search_action(query="", class_job="DRG", level_min=50, level_max=60))

        assert result["found"] is True
        assert result["filters"]["class_job"] == "DRG"
        assert result["filters"]["level_min"] == 50
        assert result["filters"]["level_max"] == 60

        call_args = mock_client.get.call_args
        query_str = call_args.kwargs["params"]["query"]
        assert "+ClassJobLevel>=50" in query_str
        assert "+ClassJobLevel<=60" in query_str

    @patch("xivapi.client.httpx.Client")
    def test_all_filters_combined(self, mock_client_class):
        """全フィルタ組み合わせ"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response(
            [_make_action_result(name="テストスキル", class_job_level=55)]
        )

        result = json.loads(
            search_action(query="テスト", class_job="竜騎士", level_min=50, level_max=60)
        )

        assert result["found"] is True
        assert result["query"] == "テスト"
        assert result["filters"]["class_job"] == "DRG"
        assert result["filters"]["level_min"] == 50
        assert result["filters"]["level_max"] == 60

    def test_unknown_job_name_error(self):
        """不明ジョブ名エラー"""
        result = json.loads(search_action(query="テスト", class_job="不明ジョブ"))

        assert result["found"] is False
        assert "不明なジョブ名です" in result["error"]
        assert "不明ジョブ" in result["error"]

    def test_no_parameters_error(self):
        """パラメータなしエラー"""
        result = json.loads(search_action())

        assert result["found"] is False
        assert "検索条件を1つ以上指定してください" in result["error"]

    @patch("xivapi.client.httpx.Client")
    def test_no_results(self, mock_client_class):
        """結果なし"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response([])

        result = json.loads(search_action(query="存在しないアクション"))

        assert result["found"] is False
        assert "見つかりませんでした" in result["message"]

    @patch("xivapi.client.httpx.Client")
    def test_timeout_error(self, mock_client_class):
        """タイムアウトエラー"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.TimeoutException("timeout")

        result = json.loads(search_action(query="テスト"))

        assert result["found"] is False
        assert "タイムアウト" in result["error"]

    @patch("xivapi.client.httpx.Client")
    def test_http_error(self, mock_client_class):
        """HTTPエラー"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_client.get.return_value = mock_response
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=mock_response
        )

        result = json.loads(search_action(query="テスト"))

        assert result["found"] is False
        assert "エラーが発生しました" in result["error"]

    @patch("xivapi.client.httpx.Client")
    def test_filtered_limit_used_with_filters(self, mock_client_class):
        """フィルタ時のlimit=20確認"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response([_make_action_result()])

        search_action(class_job="DRG")

        call_args = mock_client.get.call_args
        assert call_args.kwargs["params"]["limit"] == XIVAPI_FILTERED_LIMIT

    @patch("xivapi.client.httpx.Client")
    def test_default_limit_without_filters(self, mock_client_class):
        """フィルタなし時のlimit=5確認"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response([_make_action_result()])

        search_action(query="テスト")

        call_args = mock_client.get.call_args
        assert call_args.kwargs["params"]["limit"] == XIVAPI_DEFAULT_LIMIT

    @patch("xivapi.client.httpx.Client")
    def test_english_abbreviation_in_class_job(self, mock_client_class):
        """英語略称でのジョブ指定"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response([_make_action_result()])

        result = json.loads(search_action(class_job="pld"))

        assert result["found"] is True
        assert result["filters"]["class_job"] == "PLD"


# =============================================================================
# _resolve_craft_type テスト
# =============================================================================
class TestResolveCraftType:
    """クラフタージョブ名解決ヘルパーのテスト"""

    def test_japanese_carpenter(self):
        assert _resolve_craft_type("木工師") == "Carpenter"

    def test_japanese_smithing(self):
        assert _resolve_craft_type("鍛冶師") == "Smithing"

    def test_japanese_armorcraft(self):
        assert _resolve_craft_type("甲冑師") == "Armorcraft"

    def test_japanese_goldsmithing(self):
        assert _resolve_craft_type("彫金師") == "Goldsmithing"

    def test_japanese_leatherworking(self):
        assert _resolve_craft_type("革細工師") == "Leatherworking"

    def test_japanese_clothcraft(self):
        assert _resolve_craft_type("裁縫師") == "Clothcraft"

    def test_japanese_alchemy(self):
        assert _resolve_craft_type("錬金術師") == "Alchemy"

    def test_japanese_cooking(self):
        assert _resolve_craft_type("調理師") == "Cooking"

    def test_english_name_exact_case(self):
        assert _resolve_craft_type("Smithing") == "Smithing"

    def test_english_name_lowercase(self):
        assert _resolve_craft_type("smithing") == "Smithing"

    def test_english_name_uppercase(self):
        assert _resolve_craft_type("SMITHING") == "Smithing"

    def test_english_name_mixed_case(self):
        assert _resolve_craft_type("cArPeNtEr") == "Carpenter"

    def test_unknown_name_returns_none(self):
        assert _resolve_craft_type("不明なクラフター") is None

    def test_empty_string_returns_none(self):
        assert _resolve_craft_type("") is None


# =============================================================================
# _build_recipe_query テスト
# =============================================================================
class TestBuildRecipeQuery:
    """レシピ検索クエリ構築ヘルパーのテスト"""

    def test_name_only(self):
        result = _build_recipe_query(query="ハイスチールインゴット")
        assert result == '+ItemResult.Name~"ハイスチールインゴット"'

    def test_craft_type_only(self):
        result = _build_recipe_query(craft_type="Smithing")
        assert result == '+CraftType.Name="Smithing"'

    def test_level_min_only(self):
        result = _build_recipe_query(level_min=50)
        assert result == "+RecipeLevelTable.ClassJobLevel>=50"

    def test_level_max_only(self):
        result = _build_recipe_query(level_max=60)
        assert result == "+RecipeLevelTable.ClassJobLevel<=60"

    def test_level_range(self):
        result = _build_recipe_query(level_min=50, level_max=60)
        assert result == "+RecipeLevelTable.ClassJobLevel>=50 +RecipeLevelTable.ClassJobLevel<=60"

    def test_all_parameters(self):
        result = _build_recipe_query(
            query="インゴット", craft_type="Smithing", level_min=50, level_max=60
        )
        assert result == (
            '+ItemResult.Name~"インゴット" +CraftType.Name="Smithing" '
            "+RecipeLevelTable.ClassJobLevel>=50 +RecipeLevelTable.ClassJobLevel<=60"
        )

    def test_name_and_craft_type(self):
        result = _build_recipe_query(query="インゴット", craft_type="Carpenter")
        assert result == '+ItemResult.Name~"インゴット" +CraftType.Name="Carpenter"'

    def test_no_parameters(self):
        result = _build_recipe_query()
        assert result == ""


# =============================================================================
# _parse_recipe_result テスト
# =============================================================================
def _make_recipe_result(
    item_name: str = "テストアイテム",
    craft_type: str = "Smithing",
    recipe_level: int = 50,
) -> dict:
    """テスト用のXIVAPIレシピ検索結果1件を作成するヘルパー"""
    return {
        "row_id": 200,
        "fields": {
            "ItemResult": {"fields": {"Name": item_name}},
            "CraftType": {"fields": {"Name": craft_type}},
            "RecipeLevelTable": {"fields": {"ClassJobLevel": recipe_level}},
        },
    }


class TestParseRecipeResult:
    """_parse_recipe_result()のテスト"""

    def test_full_result(self):
        result = _parse_recipe_result(_make_recipe_result())
        assert result["item_name"] == "テストアイテム"
        assert result["craft_type"] == "Smithing"
        assert result["recipe_level"] == 50

    def test_missing_nested_fields(self):
        data = {
            "fields": {
                "ItemResult": {},
                "CraftType": {},
                "RecipeLevelTable": {},
            },
        }
        result = _parse_recipe_result(data)
        assert result["item_name"] == ""
        assert result["craft_type"] == ""
        assert result["recipe_level"] is None

    def test_non_dict_nested_fields(self):
        data = {
            "fields": {
                "ItemResult": "not_a_dict",
                "CraftType": "not_a_dict",
                "RecipeLevelTable": "not_a_dict",
            },
        }
        result = _parse_recipe_result(data)
        assert result["item_name"] == ""
        assert result["craft_type"] == ""
        assert result["recipe_level"] is None


# =============================================================================
# search_recipe 統合テスト
# =============================================================================
class TestSearchRecipe:
    """search_recipe()の統合テスト"""

    @patch("xivapi.client.httpx.Client")
    def test_name_only_search(self, mock_client_class):
        """名前のみ検索"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response(
            [_make_recipe_result(item_name="ハイスチールインゴット")]
        )

        result = json.loads(search_recipe(query="ハイスチール"))

        assert result["found"] is True
        assert result["query"] == "ハイスチール"
        assert len(result["recipes"]) == 1
        assert result["recipes"][0]["item_name"] == "ハイスチールインゴット"
        assert "filters" not in result

        call_args = mock_client.get.call_args
        assert call_args.kwargs["params"]["limit"] == XIVAPI_DEFAULT_LIMIT

    @patch("xivapi.client.httpx.Client")
    def test_craft_type_filter_japanese(self, mock_client_class):
        """日本語クラフタージョブフィルタ付き検索"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response(
            [_make_recipe_result(item_name="インゴット", craft_type="Smithing")]
        )

        result = json.loads(search_recipe(query="インゴット", craft_type="鍛冶師"))

        assert result["found"] is True
        assert result["filters"]["craft_type"] == "Smithing"

        call_args = mock_client.get.call_args
        assert '+CraftType.Name="Smithing"' in call_args.kwargs["params"]["query"]
        assert call_args.kwargs["params"]["limit"] == XIVAPI_FILTERED_LIMIT

    @patch("xivapi.client.httpx.Client")
    def test_craft_type_filter_english(self, mock_client_class):
        """英語クラフタージョブフィルタ付き検索"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response(
            [_make_recipe_result(craft_type="Carpenter")]
        )

        result = json.loads(search_recipe(craft_type="carpenter"))

        assert result["found"] is True
        assert result["filters"]["craft_type"] == "Carpenter"

    @patch("xivapi.client.httpx.Client")
    def test_level_range_search(self, mock_client_class):
        """レベル範囲付き検索"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response(
            [_make_recipe_result(recipe_level=55)]
        )

        result = json.loads(
            search_recipe(query="", craft_type="鍛冶師", level_min=50, level_max=60)
        )

        assert result["found"] is True
        assert result["filters"]["craft_type"] == "Smithing"
        assert result["filters"]["level_min"] == 50
        assert result["filters"]["level_max"] == 60

        call_args = mock_client.get.call_args
        query_str = call_args.kwargs["params"]["query"]
        assert "+RecipeLevelTable.ClassJobLevel>=50" in query_str
        assert "+RecipeLevelTable.ClassJobLevel<=60" in query_str

    @patch("xivapi.client.httpx.Client")
    def test_all_filters_combined(self, mock_client_class):
        """全フィルタ組み合わせ"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response(
            [_make_recipe_result(item_name="テスト", craft_type="Smithing", recipe_level=55)]
        )

        result = json.loads(
            search_recipe(query="テスト", craft_type="鍛冶師", level_min=50, level_max=60)
        )

        assert result["found"] is True
        assert result["query"] == "テスト"
        assert result["filters"]["craft_type"] == "Smithing"
        assert result["filters"]["level_min"] == 50
        assert result["filters"]["level_max"] == 60

    def test_unknown_craft_type_error(self):
        """不明クラフタージョブエラー"""
        result = json.loads(search_recipe(query="テスト", craft_type="不明クラフター"))

        assert result["found"] is False
        assert "不明なクラフタージョブです" in result["error"]
        assert "不明クラフター" in result["error"]

    def test_no_parameters_error(self):
        """パラメータなしエラー"""
        result = json.loads(search_recipe())

        assert result["found"] is False
        assert "検索条件を1つ以上指定してください" in result["error"]

    @patch("xivapi.client.httpx.Client")
    def test_no_results(self, mock_client_class):
        """結果なし"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response([])

        result = json.loads(search_recipe(query="存在しないレシピ"))

        assert result["found"] is False
        assert "見つかりませんでした" in result["message"]

    @patch("xivapi.client.httpx.Client")
    def test_timeout_error(self, mock_client_class):
        """タイムアウトエラー"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.TimeoutException("timeout")

        result = json.loads(search_recipe(query="テスト"))

        assert result["found"] is False
        assert "タイムアウト" in result["error"]

    @patch("xivapi.client.httpx.Client")
    def test_http_error(self, mock_client_class):
        """HTTPエラー"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_client.get.return_value = mock_response
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=mock_response
        )

        result = json.loads(search_recipe(query="テスト"))

        assert result["found"] is False
        assert "エラーが発生しました" in result["error"]

    @patch("xivapi.client.httpx.Client")
    def test_filtered_limit_used_with_filters(self, mock_client_class):
        """フィルタ時のlimit=20確認"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response([_make_recipe_result()])

        search_recipe(craft_type="鍛冶師")

        call_args = mock_client.get.call_args
        assert call_args.kwargs["params"]["limit"] == XIVAPI_FILTERED_LIMIT

    @patch("xivapi.client.httpx.Client")
    def test_default_limit_without_filters(self, mock_client_class):
        """フィルタなし時のlimit=5確認"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response([_make_recipe_result()])

        search_recipe(query="テスト")

        call_args = mock_client.get.call_args
        assert call_args.kwargs["params"]["limit"] == XIVAPI_DEFAULT_LIMIT


# =============================================================================
# _build_game_content_query テスト
# =============================================================================
class TestBuildGameContentQuery:
    """汎用ゲームコンテンツクエリ構築ヘルパーのテスト"""

    def test_name_only(self):
        result = _build_game_content_query(name_field="Name", query="テスト")
        assert result == '+Name~"テスト"'

    def test_level_min_with_level_field(self):
        result = _build_game_content_query(
            name_field="Name", level_field="Lvl", level_min=50
        )
        assert result == "+Lvl>=50"

    def test_level_max_with_level_field(self):
        result = _build_game_content_query(
            name_field="Name", level_field="Lvl", level_max=60
        )
        assert result == "+Lvl<=60"

    def test_level_range_with_level_field(self):
        result = _build_game_content_query(
            name_field="Name", level_field="Lvl", level_min=50, level_max=60
        )
        assert result == "+Lvl>=50 +Lvl<=60"

    def test_all_parameters(self):
        result = _build_game_content_query(
            name_field="Name", query="テスト", level_field="Lvl", level_min=50, level_max=60
        )
        assert result == '+Name~"テスト" +Lvl>=50 +Lvl<=60'

    def test_level_ignored_when_no_level_field(self):
        """level_fieldがNoneの場合、レベルフィルタは無視される"""
        result = _build_game_content_query(
            name_field="Name", query="テスト", level_field=None, level_min=50, level_max=60
        )
        assert result == '+Name~"テスト"'

    def test_no_parameters(self):
        result = _build_game_content_query(name_field="Name")
        assert result == ""

    def test_quest_level_field(self):
        """Quest用のLevelmainフィールド"""
        result = _build_game_content_query(
            name_field="Name", query="テスト", level_field="Levelmain", level_min=70
        )
        assert result == '+Name~"テスト" +Levelmain>=70'


# =============================================================================
# _parse_game_content_result テスト
# =============================================================================
def _make_game_content_result(
    name: str = "テストコンテンツ",
    description: str | None = "テスト説明",
    level: int | None = None,
    level_field: str | None = None,
    points: int | None = None,
    achievement_category: str | None = None,
    class_job_category: str | None = None,
    icon_path: str | None = None,
) -> dict:
    """テスト用のXIVAPI汎用ゲームコンテンツ検索結果1件を作成するヘルパー"""
    fields: dict = {"Name": name}
    if description is not None:
        fields["Description"] = description
    if level is not None and level_field is not None:
        fields[level_field] = level
    if points is not None:
        fields["Points"] = points
    if achievement_category is not None:
        fields["AchievementCategory"] = {"fields": {"Name": achievement_category}}
    if class_job_category is not None:
        fields["ClassJobCategory"] = {"fields": {"Name": class_job_category}}
    if icon_path is not None:
        fields["Icon"] = {"path": icon_path}
    return {"row_id": 300, "fields": fields}


class TestParseGameContentResult:
    """_parse_game_content_result()のテスト"""

    def test_quest_result(self):
        """Quest結果のパース"""
        config = GAME_CONTENT_CATEGORIES["Quest"]
        data = _make_game_content_result(
            name="テストクエスト",
            description=None,
            level=70,
            level_field="Levelmain",
            class_job_category="ファイター ソーサラー",
        )
        result = _parse_game_content_result(data, config)

        assert result["name"] == "テストクエスト"
        assert result["level"] == 70
        assert result["class_job_category"] == "ファイター ソーサラー"
        assert "description" not in result

    def test_achievement_result(self):
        """Achievement結果のパース"""
        config = GAME_CONTENT_CATEGORIES["Achievement"]
        data = _make_game_content_result(
            name="テスト達成",
            description="達成説明",
            points=10,
            achievement_category="バトル",
        )
        result = _parse_game_content_result(data, config)

        assert result["name"] == "テスト達成"
        assert result["description"] == "達成説明"
        assert result["points"] == 10
        assert result["achievement_category"] == "バトル"
        assert "level" not in result

    def test_fate_result(self):
        """Fate結果のパース"""
        config = GAME_CONTENT_CATEGORIES["Fate"]
        data = _make_game_content_result(
            name="テストFATE",
            description="FATE説明",
            level=60,
            level_field="Lvl",
        )
        result = _parse_game_content_result(data, config)

        assert result["name"] == "テストFATE"
        assert result["description"] == "FATE説明"
        assert result["level"] == 60

    def test_mount_result(self):
        """Mount結果のパース"""
        config = GAME_CONTENT_CATEGORIES["Mount"]
        data = _make_game_content_result(
            name="テストマウント",
            description="マウント説明",
            icon_path="icon/mount.tex",
        )
        result = _parse_game_content_result(data, config)

        assert result["name"] == "テストマウント"
        assert result["description"] == "マウント説明"
        assert "icon_url" in result
        assert "mount.tex" in result["icon_url"]
        assert "level" not in result

    def test_minion_result(self):
        """Minion結果のパース"""
        config = GAME_CONTENT_CATEGORIES["Minion"]
        data = _make_game_content_result(
            name="テストミニオン",
            description="ミニオン説明",
            icon_path="icon/minion.tex",
        )
        result = _parse_game_content_result(data, config)

        assert result["name"] == "テストミニオン"
        assert result["description"] == "ミニオン説明"
        assert "icon_url" in result

    def test_status_result(self):
        """Status結果のパース"""
        config = GAME_CONTENT_CATEGORIES["Status"]
        data = _make_game_content_result(
            name="テストステータス",
            description="ステータス説明",
            icon_path="icon/status.tex",
        )
        result = _parse_game_content_result(data, config)

        assert result["name"] == "テストステータス"
        assert result["description"] == "ステータス説明"

    def test_empty_achievement_category(self):
        """空のAchievementCategoryはパースされない"""
        config = GAME_CONTENT_CATEGORIES["Achievement"]
        data = {"row_id": 1, "fields": {"Name": "テスト", "AchievementCategory": {}}}
        result = _parse_game_content_result(data, config)

        assert "achievement_category" not in result

    def test_empty_icon(self):
        """空のIconフィールド"""
        config = GAME_CONTENT_CATEGORIES["Mount"]
        data = {"row_id": 1, "fields": {"Name": "テスト", "Icon": {}}}
        result = _parse_game_content_result(data, config)

        assert "icon_url" not in result


# =============================================================================
# search_game_content 統合テスト
# =============================================================================
class TestSearchGameContent:
    """search_game_content()の統合テスト"""

    def test_missing_category_error(self):
        """カテゴリ未指定エラー"""
        result = json.loads(search_game_content(query="テスト"))

        assert result["found"] is False
        assert "categoryは必須パラメータです" in result["error"]

    def test_invalid_category_error(self):
        """無効カテゴリエラー"""
        result = json.loads(search_game_content(query="テスト", category="InvalidCategory"))

        assert result["found"] is False
        assert "不明なカテゴリです" in result["error"]
        assert "InvalidCategory" in result["error"]
        # 有効なカテゴリ一覧がエラーメッセージに含まれる
        for cat in VALID_GAME_CONTENT_CATEGORIES:
            assert cat in result["error"]

    def test_no_parameters_error(self):
        """クエリもレベルフィルタもなしエラー"""
        result = json.loads(search_game_content(category="Quest"))

        assert result["found"] is False
        assert "検索条件を1つ以上指定してください" in result["error"]

    @patch("xivapi.client.httpx.Client")
    def test_quest_search_success(self, mock_client_class):
        """Quest検索成功"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response(
            [_make_game_content_result(
                name="暁の血盟",
                level=50,
                level_field="Levelmain",
                class_job_category="ファイター ソーサラー",
            )]
        )

        result = json.loads(search_game_content(query="暁の血盟", category="Quest"))

        assert result["found"] is True
        assert result["query"] == "暁の血盟"
        assert result["category"] == "Quest"
        assert len(result["results"]) == 1
        assert result["results"][0]["name"] == "暁の血盟"
        assert "filters" not in result

        call_args = mock_client.get.call_args
        assert call_args.kwargs["params"]["sheets"] == "Quest"
        assert call_args.kwargs["params"]["limit"] == XIVAPI_DEFAULT_LIMIT

    @patch("xivapi.client.httpx.Client")
    def test_achievement_search_success(self, mock_client_class):
        """Achievement検索成功"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response(
            [_make_game_content_result(
                name="テスト達成",
                description="達成説明",
                points=10,
                achievement_category="バトル",
            )]
        )

        result = json.loads(search_game_content(query="テスト達成", category="Achievement"))

        assert result["found"] is True
        assert result["category"] == "Achievement"
        assert len(result["results"]) == 1

        call_args = mock_client.get.call_args
        assert call_args.kwargs["params"]["sheets"] == "Achievement"

    @patch("xivapi.client.httpx.Client")
    def test_fate_search_success(self, mock_client_class):
        """Fate検索成功"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response(
            [_make_game_content_result(
                name="テストFATE",
                description="FATE説明",
                level=60,
                level_field="Lvl",
            )]
        )

        result = json.loads(search_game_content(query="テストFATE", category="Fate"))

        assert result["found"] is True
        assert result["category"] == "Fate"

        call_args = mock_client.get.call_args
        assert call_args.kwargs["params"]["sheets"] == "Fate"

    @patch("xivapi.client.httpx.Client")
    def test_mount_search_success(self, mock_client_class):
        """Mount検索成功"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response(
            [_make_game_content_result(
                name="テストマウント",
                description="マウント説明",
                icon_path="icon/mount.tex",
            )]
        )

        result = json.loads(search_game_content(query="テストマウント", category="Mount"))

        assert result["found"] is True
        assert result["category"] == "Mount"

        call_args = mock_client.get.call_args
        assert call_args.kwargs["params"]["sheets"] == "Mount"

    @patch("xivapi.client.httpx.Client")
    def test_minion_search_uses_companion_sheet(self, mock_client_class):
        """Minion検索はCompanionシートを使用する"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response(
            [_make_game_content_result(name="テストミニオン")]
        )

        search_game_content(query="テストミニオン", category="Minion")

        call_args = mock_client.get.call_args
        assert call_args.kwargs["params"]["sheets"] == "Companion"

    @patch("xivapi.client.httpx.Client")
    def test_quest_level_filter(self, mock_client_class):
        """Questカテゴリのレベルフィルタ（level_fieldあり）"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response(
            [_make_game_content_result(name="テスト", level=70, level_field="Levelmain")]
        )

        result = json.loads(
            search_game_content(query="テスト", category="Quest", level_min=60, level_max=80)
        )

        assert result["found"] is True
        assert result["filters"]["level_min"] == 60
        assert result["filters"]["level_max"] == 80

        call_args = mock_client.get.call_args
        query_str = call_args.kwargs["params"]["query"]
        assert "+Levelmain>=60" in query_str
        assert "+Levelmain<=80" in query_str
        assert call_args.kwargs["params"]["limit"] == XIVAPI_FILTERED_LIMIT

    @patch("xivapi.client.httpx.Client")
    def test_fate_level_filter(self, mock_client_class):
        """Fateカテゴリのレベルフィルタ（level_fieldあり）"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response(
            [_make_game_content_result(name="テスト", level=50, level_field="Lvl")]
        )

        result = json.loads(
            search_game_content(query="テスト", category="Fate", level_min=40, level_max=60)
        )

        assert result["found"] is True
        assert result["filters"]["level_min"] == 40
        assert result["filters"]["level_max"] == 60

        call_args = mock_client.get.call_args
        query_str = call_args.kwargs["params"]["query"]
        assert "+Lvl>=40" in query_str
        assert "+Lvl<=60" in query_str

    @patch("xivapi.client.httpx.Client")
    def test_achievement_level_filter_ignored(self, mock_client_class):
        """Achievementカテゴリはlevel_fieldがNone→レベルフィルタ無視、limit=5"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response(
            [_make_game_content_result(name="テスト達成", points=10)]
        )

        result = json.loads(
            search_game_content(query="テスト", category="Achievement", level_min=50)
        )

        assert result["found"] is True
        # フィルタはレスポンスに含まれない（has_filters and level_field が False）
        assert "filters" not in result

        # クエリにレベル条件は含まれない
        call_args = mock_client.get.call_args
        query_str = call_args.kwargs["params"]["query"]
        assert ">=50" not in query_str
        # limit=5（フィルタ無効扱い）
        assert call_args.kwargs["params"]["limit"] == XIVAPI_DEFAULT_LIMIT

    @patch("xivapi.client.httpx.Client")
    def test_mount_level_filter_ignored(self, mock_client_class):
        """Mountカテゴリはlevel_fieldがNone→レベルフィルタ無視"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response(
            [_make_game_content_result(name="テストマウント")]
        )

        result = json.loads(
            search_game_content(query="テスト", category="Mount", level_min=10)
        )

        assert result["found"] is True
        assert "filters" not in result

        call_args = mock_client.get.call_args
        query_str = call_args.kwargs["params"]["query"]
        assert ">=10" not in query_str
        assert call_args.kwargs["params"]["limit"] == XIVAPI_DEFAULT_LIMIT

    @patch("xivapi.client.httpx.Client")
    def test_no_results(self, mock_client_class):
        """結果なし"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response([])

        result = json.loads(search_game_content(query="存在しないクエスト", category="Quest"))

        assert result["found"] is False
        assert "見つかりませんでした" in result["message"]
        assert "Quest" in result["message"]

    @patch("xivapi.client.httpx.Client")
    def test_timeout_error(self, mock_client_class):
        """タイムアウトエラー"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.TimeoutException("timeout")

        result = json.loads(search_game_content(query="テスト", category="Quest"))

        assert result["found"] is False
        assert "タイムアウト" in result["error"]

    @patch("xivapi.client.httpx.Client")
    def test_http_error(self, mock_client_class):
        """HTTPエラー"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_client.get.return_value = mock_response
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=mock_response
        )

        result = json.loads(search_game_content(query="テスト", category="Quest"))

        assert result["found"] is False
        assert "エラーが発生しました" in result["error"]

    @patch("xivapi.client.httpx.Client")
    def test_multiple_results(self, mock_client_class):
        """複数件取得"""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_mock_response([
            _make_game_content_result(name="クエストA"),
            _make_game_content_result(name="クエストB"),
            _make_game_content_result(name="クエストC"),
        ])

        result = json.loads(search_game_content(query="クエスト", category="Quest"))

        assert result["found"] is True
        assert len(result["results"]) == 3
