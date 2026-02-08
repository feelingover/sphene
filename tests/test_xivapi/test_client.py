"""XIVAPI v2 クライアントのテスト"""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from xivapi.client import (
    XIVAPI_DEFAULT_LIMIT,
    XIVAPI_FILTERED_LIMIT,
    XIVAPI_SEARCH_URL,
    _build_search_query,
    _resolve_job_abbreviation,
    search_item,
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
