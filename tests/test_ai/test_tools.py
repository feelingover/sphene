"""ai/tools.py のツールスキーマ変換テスト"""

from ai.tools import TOOL_DEFINITIONS_RAW, TOOL_FUNCTIONS, get_tools
from xivapi.client import CRAFT_TYPE_MAPPING, GAME_CONTENT_CATEGORIES


def _declarations() -> dict:
    return {fd.name: fd for fd in get_tools()[0].function_declarations or []}


class TestGetTools:
    def test_all_raw_definitions_are_converted(self):
        decls = _declarations()
        assert set(decls) == {t["name"] for t in TOOL_DEFINITIONS_RAW}
        assert set(decls) == set(TOOL_FUNCTIONS)

    def test_category_enum_is_preserved(self):
        category = _declarations()["search_game_content"].parameters.properties["category"]
        assert category.enum == list(GAME_CONTENT_CATEGORIES.keys())

    def test_craft_type_enum_contains_ja_and_en_names(self):
        craft_type = _declarations()["search_recipe"].parameters.properties["craft_type"]
        assert set(craft_type.enum) == set(CRAFT_TYPE_MAPPING) | set(CRAFT_TYPE_MAPPING.values())

    def test_properties_without_enum_have_none(self):
        query = _declarations()["search_item"].parameters.properties["query"]
        assert query.enum is None
        assert query.description

    def test_game_content_exposes_level_range(self):
        props = _declarations()["search_game_content"].parameters.properties
        assert "level_min" in props
        assert "level_max" in props

    def test_required_is_preserved(self):
        assert _declarations()["search_game_content"].parameters.required == ["category"]
        assert _declarations()["search_item"].parameters.required == []
