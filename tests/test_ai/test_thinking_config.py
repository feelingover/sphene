"""Thinkingレベル設定（ai/client.py）と呼び出し側への反映のテスト"""

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from google.genai import types

import config
from ai.client import (
    _build_thinking_config,
    get_light_thinking_config,
    get_main_thinking_config,
)


@pytest.fixture(autouse=True)
def _clear_thinking_cache() -> Iterator[None]:
    """lru_cache をテストごとにクリアする"""
    _build_thinking_config.cache_clear()
    yield
    _build_thinking_config.cache_clear()


class TestBuildThinkingConfig:
    """_build_thinking_config のテスト"""

    def test_empty_returns_none(self) -> None:
        """空文字はモデルのデフォルト（None）になる"""
        assert _build_thinking_config("") is None

    @pytest.mark.parametrize(
        ("level", "expected"),
        [
            ("minimal", types.ThinkingLevel.MINIMAL),
            ("low", types.ThinkingLevel.LOW),
            ("medium", types.ThinkingLevel.MEDIUM),
            ("high", types.ThinkingLevel.HIGH),
        ],
    )
    def test_valid_levels(self, level: str, expected: types.ThinkingLevel) -> None:
        """有効なレベルは ThinkingConfig に変換される"""
        result = _build_thinking_config(level)
        assert result is not None
        assert result.thinking_level == expected

    def test_invalid_level_returns_none_with_warning(self) -> None:
        """不正な値は警告を出してNoneを返す"""
        with patch("ai.client.logger") as mock_logger:
            assert _build_thinking_config("turbo") is None
            mock_logger.warning.assert_called_once()


class TestThinkingConfigAccessors:
    """get_main_thinking_config / get_light_thinking_config のテスト"""

    def test_main_uses_main_level(self) -> None:
        """MAIN_THINKING_LEVEL が反映される"""
        with patch.object(config, "MAIN_THINKING_LEVEL", "high"):
            result = get_main_thinking_config()
        assert result is not None
        assert result.thinking_level == types.ThinkingLevel.HIGH

    def test_main_default_is_model_default(self) -> None:
        """MAIN_THINKING_LEVEL が空ならNone"""
        with patch.object(config, "MAIN_THINKING_LEVEL", ""):
            assert get_main_thinking_config() is None

    def test_light_uses_light_level(self) -> None:
        """LIGHT_THINKING_LEVEL が反映される"""
        with patch.object(config, "LIGHT_THINKING_LEVEL", "low"):
            result = get_light_thinking_config()
        assert result is not None
        assert result.thinking_level == types.ThinkingLevel.LOW

    def test_light_default_is_low(self) -> None:
        """LIGHT_THINKING_LEVEL のデフォルトは low"""
        assert config.LIGHT_THINKING_LEVEL == "low"


class TestThinkingConfigApplied:
    """呼び出し側で ThinkingConfig が渡されることのテスト"""

    def test_router_uses_light_thinking(self) -> None:
        """Router LLM は軽量タスク用の ThinkingConfig を使う"""
        from ai.router import _call_router_llm

        mock_response = MagicMock()
        mock_response.text = '{"tool_mode": "none", "reason": "test"}'
        sentinel = types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)

        with patch("ai.router._get_genai_client"), patch(
            "ai.router._generate_content_with_retry", return_value=mock_response
        ) as mock_gen, patch(
            "ai.router.get_light_thinking_config", return_value=sentinel
        ):
            _call_router_llm("ピーコック装備のレシピを教えて", None)

        assert mock_gen.call_args.kwargs["config"].thinking_config is sentinel

    def test_tool_loop_uses_main_thinking(self) -> None:
        """ツール呼び出しループはメイン用の ThinkingConfig を使う"""
        from ai.api import call_genai_with_tools

        candidate = MagicMock()
        candidate.content.parts = [types.Part.from_text(text="answer")]
        candidate.grounding_metadata = None
        mock_response = MagicMock()
        mock_response.candidates = [candidate]
        sentinel = types.ThinkingConfig(thinking_level=types.ThinkingLevel.HIGH)

        with patch("ai.api._get_genai_client") as mock_client, patch(
            "ai.api.get_model_name", return_value="gemini-4-hydrogen"
        ), patch("ai.api.get_main_thinking_config", return_value=sentinel):
            mock_client.return_value.models.generate_content.return_value = mock_response
            success, _, _ = call_genai_with_tools([], "system", tool_mode="none")

        assert success is True
        _, kwargs = mock_client.return_value.models.generate_content.call_args
        assert kwargs["config"].thinking_config is sentinel
