"""反省会エンジンのテスト"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from memory.reflection import ReflectionEngine, get_reflection_engine
from memory.short_term import ChannelMessage


def _make_message(
    channel_id: int = 100,
    author_name: str = "TestUser",
    author_id: int = 12345,
    content: str = "テストメッセージ",
    is_bot: bool = False,
) -> ChannelMessage:
    """テスト用ChannelMessageファクトリ"""
    return ChannelMessage(
        message_id=1,
        channel_id=channel_id,
        author_id=author_id,
        author_name=author_name,
        content=content,
        timestamp=datetime.now(timezone.utc),
        is_bot=is_bot,
    )


class TestReflectionEngineMaybeReflect:
    """ReflectionEngine.maybe_reflect のテスト"""

    @pytest.mark.asyncio
    async def test_skips_when_insufficient_messages(self):
        """メッセージ数が最小要件未満の場合スキップされること"""
        engine = ReflectionEngine()
        messages = [_make_message() for _ in range(3)]

        loop = asyncio.get_running_loop()
        with patch("config.REFLECTION_MIN_MESSAGES", 10):
            with patch.object(loop, "create_task") as mock_create_task:
                engine.maybe_reflect(100, messages)
                mock_create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_already_running(self):
        """既に実行中のチャンネルはスキップされること"""
        engine = ReflectionEngine()
        engine._running.add(100)
        messages = [_make_message() for _ in range(15)]

        loop = asyncio.get_running_loop()
        with patch("config.REFLECTION_MIN_MESSAGES", 10):
            with patch.object(loop, "create_task") as mock_create_task:
                engine.maybe_reflect(100, messages)
                mock_create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_triggers_when_sufficient_messages(self):
        """十分なメッセージ数のとき create_task が呼ばれること"""
        engine = ReflectionEngine()
        messages = [_make_message() for _ in range(15)]

        loop = asyncio.get_running_loop()
        with patch("config.REFLECTION_MIN_MESSAGES", 10):
            with patch.object(loop, "create_task") as mock_create_task:
                mock_create_task.return_value = MagicMock()
                engine.maybe_reflect(100, messages)
                mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_adds_to_running_before_future(self):
        """create_task 呼び出し前に _running に追加されること（二重スケジュール防止）"""
        engine = ReflectionEngine()
        messages = [_make_message() for _ in range(15)]
        captured_running = []

        loop = asyncio.get_running_loop()

        def capture_running(coro):
            captured_running.append(100 in engine._running)
            coro.close()
            return MagicMock()

        with patch("config.REFLECTION_MIN_MESSAGES", 10):
            with patch.object(loop, "create_task", side_effect=capture_running):
                engine.maybe_reflect(100, messages)

        assert captured_running[0] is True


class TestCallReflectionLlm:
    """ReflectionEngine._call_reflection_llm のテスト"""

    def test_returns_list_on_success(self):
        """正常なJSON配列を返すこと"""
        engine = ReflectionEngine()
        messages = [_make_message()]

        mock_response = MagicMock()
        mock_response.text = '[{"content": "テストファクト", "keywords": ["テスト"], "source_user_ids": [12345], "shareable": true}]'

        with patch("memory.reflection.get_genai_client"):
            with patch("memory.reflection._generate_content_with_retry", return_value=mock_response):
                with patch("config.REFLECTION_MODEL", ""):
                    with patch("memory.reflection.get_model_name", return_value="test-model"):
                        result = engine._call_reflection_llm(messages)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["content"] == "テストファクト"

    def test_returns_empty_list_on_empty_json(self):
        """空配列が返ってきたとき空リストを返すこと"""
        engine = ReflectionEngine()
        messages = [_make_message()]

        mock_response = MagicMock()
        mock_response.text = "[]"

        with patch("memory.reflection.get_genai_client"):
            with patch("memory.reflection._generate_content_with_retry", return_value=mock_response):
                with patch("config.REFLECTION_MODEL", ""):
                    with patch("memory.reflection.get_model_name", return_value="test-model"):
                        result = engine._call_reflection_llm(messages)

        assert result == []

    def test_returns_none_on_invalid_json(self):
        """不正なJSONのとき None を返すこと"""
        engine = ReflectionEngine()
        messages = [_make_message()]

        mock_response = MagicMock()
        mock_response.text = "not valid json"

        with patch("memory.reflection.get_genai_client"):
            with patch("memory.reflection._generate_content_with_retry", return_value=mock_response):
                with patch("config.REFLECTION_MODEL", ""):
                    with patch("memory.reflection.get_model_name", return_value="test-model"):
                        result = engine._call_reflection_llm(messages)

        assert result is None

    def test_returns_none_on_non_list(self):
        """JSON が配列でない場合 None を返すこと"""
        engine = ReflectionEngine()
        messages = [_make_message()]

        mock_response = MagicMock()
        mock_response.text = '{"key": "value"}'

        with patch("memory.reflection.get_genai_client"):
            with patch("memory.reflection._generate_content_with_retry", return_value=mock_response):
                with patch("config.REFLECTION_MODEL", ""):
                    with patch("memory.reflection.get_model_name", return_value="test-model"):
                        result = engine._call_reflection_llm(messages)

        assert result is None

    def test_returns_none_on_exception(self):
        """例外発生時に None を返すこと"""
        engine = ReflectionEngine()
        messages = [_make_message()]

        with patch("memory.reflection.get_genai_client"):
            with patch("memory.reflection._generate_content_with_retry", side_effect=Exception("API エラー")):
                with patch("config.REFLECTION_MODEL", ""):
                    with patch("memory.reflection.get_model_name", return_value="test-model"):
                        result = engine._call_reflection_llm(messages)

        assert result is None

    def test_returns_none_on_empty_messages(self):
        """メッセージが空の場合 None を返すこと"""
        engine = ReflectionEngine()

        with patch("memory.reflection.get_genai_client"):
            with patch("memory.reflection._generate_content_with_retry") as mock_api:
                result = engine._call_reflection_llm([])

        assert result is None


class TestApplyFacts:
    """ReflectionEngine._apply_facts のテスト"""

    def test_calls_add_fact_for_each_valid_item(self):
        """有効なファクトの数だけ add_fact が呼ばれること"""
        engine = ReflectionEngine()
        messages = [_make_message()]
        raw_facts = [
            {"content": "ファクト1", "keywords": ["kw1"], "source_user_ids": [1], "shareable": True},
            {"content": "ファクト2", "keywords": ["kw2"], "source_user_ids": [2], "shareable": False},
        ]

        mock_store = MagicMock()
        mock_buffer = MagicMock()

        with patch("memory.fact_store.get_fact_store", return_value=mock_store):
            with patch("memory.short_term.get_channel_buffer", return_value=mock_buffer):
                engine._apply_facts(100, raw_facts, messages)

        assert mock_store.add_fact.call_count == 2

    def test_skips_empty_content(self):
        """content が空のファクトはスキップされること"""
        engine = ReflectionEngine()
        messages = [_make_message()]
        raw_facts = [
            {"content": "", "keywords": [], "source_user_ids": [], "shareable": False},
            {"content": "有効なファクト", "keywords": ["kw"], "source_user_ids": [], "shareable": False},
        ]

        mock_store = MagicMock()
        mock_buffer = MagicMock()

        with patch("memory.fact_store.get_fact_store", return_value=mock_store):
            with patch("memory.short_term.get_channel_buffer", return_value=mock_buffer):
                engine._apply_facts(100, raw_facts, messages)

        assert mock_store.add_fact.call_count == 1

    def test_calls_mark_reflected(self):
        """_apply_facts 後に mark_reflected が呼ばれること"""
        engine = ReflectionEngine()
        messages = [_make_message()]
        raw_facts = [
            {"content": "ファクト", "keywords": [], "source_user_ids": [], "shareable": False}
        ]

        mock_store = MagicMock()
        mock_buffer = MagicMock()

        with patch("memory.fact_store.get_fact_store", return_value=mock_store):
            with patch("memory.short_term.get_channel_buffer", return_value=mock_buffer):
                engine._apply_facts(100, raw_facts, messages)

        mock_buffer.mark_reflected.assert_called_once_with(100)

    def test_skips_non_dict_items(self):
        """辞書でないアイテムはスキップされること"""
        engine = ReflectionEngine()
        messages = [_make_message()]
        raw_facts = ["文字列", 123, {"content": "有効", "keywords": [], "source_user_ids": [], "shareable": False}]

        mock_store = MagicMock()
        mock_buffer = MagicMock()

        with patch("memory.fact_store.get_fact_store", return_value=mock_store):
            with patch("memory.short_term.get_channel_buffer", return_value=mock_buffer):
                engine._apply_facts(100, raw_facts, messages)

        assert mock_store.add_fact.call_count == 1


class TestGetReflectionEngine:
    """シングルトンのテスト"""

    def test_singleton(self):
        """同じインスタンスが返ること"""
        import memory.reflection as ref_module

        original = ref_module._reflection_engine
        ref_module._reflection_engine = None
        try:
            e1 = get_reflection_engine()
            e2 = get_reflection_engine()
            assert e1 is e2
        finally:
            ref_module._reflection_engine = original
