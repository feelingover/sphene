"""XIVAPIクライアントのDQLサニタイズ・数値正規化・共有クライアントのテスト"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

import xivapi.client as xivapi_client
from xivapi.client import (
    _build_action_query,
    _build_game_content_query,
    _build_recipe_query,
    _build_search_query,
    _dql_int,
    _dql_str,
    _get_http_client,
    close_http_client,
)


class TestDqlStr:
    def test_removes_quotes_and_backslashes(self):
        assert _dql_str('a"b\\c') == "abc"

    def test_removes_control_chars(self):
        assert _dql_str("a\nb\tc\x00d\x7f") == "abcd"

    def test_keeps_japanese_and_symbols(self):
        assert _dql_str("エクサーク・コート（HQ）+1") == "エクサーク・コート（HQ）+1"


class TestDqlInt:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [(600, 600), (600.0, 600), ("600", 600), ("600.0", 600), (0, 0), (None, None)],
    )
    def test_normalizes(self, value, expected):
        assert _dql_int(value) == expected

    @pytest.mark.parametrize("value", ["abc", "", True, float("inf"), [1]])
    def test_invalid_values_return_none(self, value):
        assert _dql_int(value) is None


class TestQueryInjection:
    """引用符を含む入力でDQLの句が注入されないこと"""

    INJECTION = 'x" +LevelItem>=1 Name~"'

    def test_item_query(self):
        query = _build_search_query(query=self.INJECTION)
        assert query == 'Name@ja~"x +LevelItem>=1 Name~"'
        assert query.count('"') == 2

    def test_action_query(self):
        assert _build_action_query(query=self.INJECTION).count('"') == 2

    def test_recipe_query(self):
        assert _build_recipe_query(query=self.INJECTION).count('"') == 2

    def test_game_content_query(self):
        assert _build_game_content_query("Name", query=self.INJECTION).count('"') == 2

    def test_query_of_only_quotes_adds_no_name_clause(self):
        assert _build_search_query(query='""', ilvl_min=600) == "+LevelItem>=600"


class TestLevelCoercion:
    def test_float_levels_become_int(self):
        assert _build_search_query(ilvl_min=600.0, ilvl_max=650.0) == (  # type: ignore[arg-type]
            "+LevelItem>=600 +LevelItem<=650"
        )
        assert _build_action_query(level_min=50.0) == "+ClassJobLevel>=50"  # type: ignore[arg-type]
        assert _build_recipe_query(level_max=90.0) == (  # type: ignore[arg-type]
            "+RecipeLevelTable.ClassJobLevel<=90"
        )
        assert _build_game_content_query("Name", level_field="Lvl", level_min=30.0) == (  # type: ignore[arg-type]
            "+Lvl>=30"
        )

    def test_invalid_level_is_ignored(self):
        assert _build_recipe_query(query="a", level_min="高い") == 'ItemResult.Name@ja~"a"'  # type: ignore[arg-type]


class TestSharedHttpClient:
    def test_client_is_reused(self):
        try:
            first = _get_http_client()
            second = _get_http_client()
            assert first is second
            assert isinstance(first, httpx.Client)
        finally:
            close_http_client()

    def test_close_then_recreate(self):
        first = _get_http_client()
        close_http_client()
        assert first.is_closed
        assert xivapi_client._http_client is None
        second = _get_http_client()
        try:
            assert second is not first
        finally:
            close_http_client()

    def test_closed_client_is_replaced(self):
        first = _get_http_client()
        first.close()
        second = _get_http_client()
        try:
            assert second is not first
            assert not second.is_closed
        finally:
            close_http_client()

    def test_close_without_client_is_noop(self):
        close_http_client()
        assert xivapi_client._http_client is None

    @patch("xivapi.client.httpx.Client")
    def test_search_uses_single_client_across_requests(self, mock_client_class):
        mock_client = MagicMock()
        mock_client.is_closed = False
        mock_client.get.return_value.json.return_value = {"results": []}
        mock_client_class.return_value = mock_client

        xivapi_client.search_item(query="a")
        xivapi_client.search_item(query="b")

        assert mock_client_class.call_count == 1
        assert mock_client.get.call_count == 2
