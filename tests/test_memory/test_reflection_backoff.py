"""反省会の失敗時バックオフ・破棄のテスト"""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from memory.reflection import ReflectionEngine
from memory.short_term import ChannelMessage


def _messages(n: int = 15) -> list[ChannelMessage]:
    base = datetime(2026, 11, 1, tzinfo=timezone.utc)
    return [
        ChannelMessage(
            message_id=i,
            channel_id=100,
            author_id=1,
            author_name="U",
            content=f"m{i}",
            timestamp=base + timedelta(seconds=i),
            guild_id=1,
        )
        for i in range(n)
    ]


async def _run(engine: ReflectionEngine, messages: list[ChannelMessage], raw, apply_result=True):
    with patch.object(engine, "_call_reflection_llm", return_value=raw), \
         patch.object(engine, "_apply_facts", new_callable=AsyncMock, return_value=apply_result) as apply, \
         patch.object(engine, "_call_user_profile_llm") as profile:
        await engine._run_reflect(100, messages)
    return apply, profile


class TestRunReflectBackoff:
    @pytest.mark.asyncio
    async def test_llm_failure_records_backoff_and_skips_profile(self):
        engine = ReflectionEngine()

        with patch("config.LIVING_MEMORY_ENABLED", True):
            apply, profile = await _run(engine, _messages(), None)

        apply.assert_not_called()
        profile.assert_not_called()
        assert engine._backoff.failure_count(100) == 1
        assert engine._backoff.is_blocked(100)

    @pytest.mark.asyncio
    async def test_all_invalid_items_count_as_failure(self):
        engine = ReflectionEngine()

        with patch("config.LIVING_MEMORY_ENABLED", True):
            _, profile = await _run(engine, _messages(), [{"content": None}], apply_result=False)

        profile.assert_not_called()
        assert engine._backoff.failure_count(100) == 1

    @pytest.mark.asyncio
    async def test_success_resets_backoff_and_updates_profile(self):
        engine = ReflectionEngine()
        engine._backoff.record_failure(100)
        messages = _messages()

        with patch("config.LIVING_MEMORY_ENABLED", True):
            _, profile = await _run(engine, messages, [])

        profile.assert_called_once_with(messages)
        assert engine._backoff.failure_count(100) == 0

    @pytest.mark.asyncio
    async def test_batch_dropped_after_max_failures(self):
        engine = ReflectionEngine()
        messages = _messages()
        mock_buffer = MagicMock()

        with patch("config.LIVING_MEMORY_ENABLED", True), \
             patch("config.REFLECTION_MAX_FAILURES", 3), \
             patch("memory.short_term.get_channel_buffer", return_value=mock_buffer):
            for _ in range(2):
                _, profile = await _run(engine, messages, None)
                profile.assert_not_called()
            mock_buffer.mark_reflected.assert_not_called()

            _, profile = await _run(engine, messages, None)

        mock_buffer.mark_reflected.assert_called_once_with(100, until=messages[-1].timestamp)
        # 破棄でメッセージ群の処理は確定するため、プロファイルは更新し、バックオフも解除する
        profile.assert_called_once_with(messages)
        assert engine._backoff.failure_count(100) == 0
        assert not engine._backoff.is_blocked(100)

    @pytest.mark.asyncio
    async def test_running_flag_cleared_after_failure(self):
        engine = ReflectionEngine()
        engine._running.add(100)

        await _run(engine, _messages(), None)

        assert 100 not in engine._running


class TestMaybeReflectBackoff:
    def test_skips_while_blocked(self):
        engine = ReflectionEngine()
        engine._backoff.record_failure(100)

        with patch("config.REFLECTION_MIN_MESSAGES", 1), \
             patch("memory.reflection.asyncio.get_running_loop") as mock_loop:
            engine.maybe_reflect(100, _messages())

        mock_loop.assert_not_called()
        assert 100 not in engine._running

    def test_runs_when_not_blocked(self):
        engine = ReflectionEngine()
        loop = MagicMock()

        with patch("config.REFLECTION_MIN_MESSAGES", 1), \
             patch("memory.reflection.asyncio.get_running_loop", return_value=loop), \
             patch.object(engine, "_run_reflect", new=MagicMock()):
            engine.maybe_reflect(100, _messages())

        loop.create_task.assert_called_once()


class TestApplyFactsReturnValue:
    def _apply(self, raw_facts):
        engine = ReflectionEngine()
        with patch("memory.fact_store.get_fact_store", return_value=MagicMock()), \
             patch("memory.short_term.get_channel_buffer", return_value=MagicMock()), \
             patch("ai.client.generate_embedding", return_value=None):
            return asyncio.run(engine._apply_facts(100, raw_facts, _messages(1)))

    def test_all_invalid_returns_false(self):
        assert self._apply([{"content": None}]) is False

    def test_empty_array_returns_true(self):
        assert self._apply([]) is True

    def test_valid_item_returns_true(self):
        assert self._apply([{"content": "ファクト"}]) is True
