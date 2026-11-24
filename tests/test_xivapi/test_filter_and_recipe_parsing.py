"""XIVAPI: 0 や不正値のフィルタで空クエリを送らないこと・レシピのパース失敗の扱い"""

import json
from unittest.mock import patch

import pytest

from xivapi.client import _parse_recipe_result, search_action, search_item, search_recipe


class TestZeroFiltersDoNotSendEmptyQuery:
    @pytest.mark.parametrize(
        ("func", "kwargs"),
        [
            (search_item, {"ilvl_min": 0}),
            (search_item, {"ilvl_max": 0}),
            (search_action, {"level_min": 0}),
            (search_recipe, {"level_min": "高い"}),
        ],
    )
    def test_returns_error_without_request(self, func, kwargs):
        with patch("xivapi.client._execute_search") as execute:
            result = json.loads(func(**kwargs))
        execute.assert_not_called()
        assert result["found"] is False

    def test_recipe_level_zero_is_a_filter(self):
        """レシピは 0 も条件として扱う（_build_recipe_query と同じ）"""
        with patch("xivapi.client._execute_search", return_value={"results": []}) as execute:
            search_recipe(level_min=0)
        assert execute.call_args.kwargs["search_query"] == "+RecipeLevelTable.ClassJobLevel>=0"


class TestRecipeParsing:
    def test_none_amount_is_skipped(self):
        result = {
            "fields": {
                "Ingredient": [{"value": 5, "fields": {"Name": "A"}}, {"value": 6, "fields": {"Name": "B"}}],
                "AmountIngredient": [None, 2],
            }
        }
        assert _parse_recipe_result(result)["ingredients"] == [{"name": "B", "amount": 2}]

    def test_parse_failure_is_logged(self):
        with (
            patch("xivapi.client._execute_search", return_value={"results": ["broken", {"fields": {}}]}),
            patch("xivapi.client.logger") as logger,
        ):
            result = json.loads(search_recipe(query="a"))
        assert len(result["recipes"]) == 1
        assert logger.warning.call_args.kwargs["exc_info"] is True


class TestActionDetailFallback:
    def test_detail_fetch_failure_falls_back_and_is_logged(self):
        """詳細取得に失敗しても検索結果でパースし、warning を exc_info 付きで出す"""
        search_result = {"row_id": 100, "fields": {"Name@ja": "ファイア", "Description@ja": "検索結果の説明"}}
        with (
            patch("xivapi.client._execute_search", return_value={"results": [search_result]}),
            patch("xivapi.client._fetch_sheet_row", side_effect=RuntimeError("boom")),
            patch("xivapi.client.logger") as logger,
        ):
            result = json.loads(search_action(query="ファイア"))
        assert result["found"] is True
        assert result["actions"][0]["name"] == "ファイア"
        assert result["actions"][0]["description"] == "検索結果の説明"
        assert "row_id=100" in logger.warning.call_args.args[0]
        assert logger.warning.call_args.kwargs["exc_info"] is True
