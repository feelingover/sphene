"""要約LLM出力の検証と失敗時バックオフのテスト"""

from unittest.mock import MagicMock, patch

import pytest

from memory.channel_context import ChannelContext
from memory.summarizer import Summarizer, _parse_summary_result


class TestParseSummaryResult:
    def test_valid_result(self):
        result = _parse_summary_result(
            {"summary": "要約", "mood": "楽しい", "topic_keywords": ["a", "b"]}
        )
        assert result == {"summary": "要約", "mood": "楽しい", "topic_keywords": ["a", "b"]}

    def test_single_element_list_is_unwrapped(self):
        assert _parse_summary_result([{"summary": "要約"}])["summary"] == "要約"

    @pytest.mark.parametrize("raw", [[], [{"summary": "a"}, {"summary": "b"}], "要約", 1, None])
    def test_non_object_returns_none(self, raw):
        assert _parse_summary_result(raw) is None

    @pytest.mark.parametrize("summary", [None, "", "   ", 123, ["要約"]])
    def test_invalid_summary_returns_none(self, summary):
        assert _parse_summary_result({"summary": summary}) is None

    def test_summary_is_sanitized_and_truncated(self):
        result = _parse_summary_result({"summary": "一行目\n\n二行目​" + "あ" * 1000})
        assert "\n" not in result["summary"]
        assert "​" not in result["summary"]
        assert result["summary"].startswith("一行目 二行目")
        assert len(result["summary"]) == 500

    def test_invalid_mood_becomes_none(self):
        assert _parse_summary_result({"summary": "s", "mood": ["x"]})["mood"] is None

    def test_string_keywords_become_none(self):
        """文字列の topic_keywords はリストとして扱わない（前回値を維持させる）"""
        assert _parse_summary_result({"summary": "s", "topic_keywords": "a,b"})["topic_keywords"] is None

    def test_keywords_are_sanitized(self):
        result = _parse_summary_result(
            {"summary": "s", "topic_keywords": ["a", 1, "a", "b\nc", "x" * 100]}
        )
        assert result["topic_keywords"] == ["a", "b c", "x" * 30]

    def test_keywords_are_limited(self):
        result = _parse_summary_result({"summary": "s", "topic_keywords": [str(i) for i in range(20)]})
        assert len(result["topic_keywords"]) == 10


class TestApplyParsedResult:
    def test_none_fields_keep_previous_values(self):
        context = ChannelContext(channel_id=1, summary="旧", mood="旧ムード", topic_keywords=["旧"])
        parsed = _parse_summary_result({"summary": "新", "mood": 1, "topic_keywords": "x"})

        Summarizer()._apply_result(context, parsed, [])

        assert context.summary == "新"
        assert context.mood == "旧ムード"
        assert context.topic_keywords == ["旧"]

    def test_empty_keyword_list_clears_keywords(self):
        context = ChannelContext(channel_id=1, summary="旧", topic_keywords=["旧"])
        parsed = _parse_summary_result({"summary": "新", "topic_keywords": []})

        Summarizer()._apply_result(context, parsed, [])

        assert context.topic_keywords == []


class TestCallSummarizeLlmValidation:
    @patch("memory.summarizer.get_model_name", return_value="m")
    @patch("memory.summarizer._get_genai_client")
    def test_list_output_does_not_raise(self, mock_get_client, _mock_model):
        mock_get_client.return_value.models.generate_content.return_value = MagicMock(
            text='["要約"]'
        )
        from memory.short_term import ChannelMessage
        from datetime import datetime, timezone

        msg = ChannelMessage(
            message_id=1, channel_id=1, author_id=1, author_name="U",
            content="c", timestamp=datetime.now(timezone.utc),
        )

        assert Summarizer()._call_summarize_llm(ChannelContext(channel_id=1), [msg]) is None


class TestSummarizerBackoff:
    @pytest.mark.asyncio
    async def test_failure_records_backoff(self):
        summarizer = Summarizer()
        with patch.object(summarizer, "_call_summarize_llm", return_value=None):
            await summarizer._run_summarize(1, ChannelContext(channel_id=1), [])

        assert summarizer._backoff.is_blocked(1)
        assert 1 not in summarizer._running

    @pytest.mark.asyncio
    async def test_exception_records_backoff(self):
        summarizer = Summarizer()
        with patch.object(summarizer, "_call_summarize_llm", side_effect=RuntimeError("x")):
            await summarizer._run_summarize(1, ChannelContext(channel_id=1), [])

        assert summarizer._backoff.failure_count(1) == 1

    @pytest.mark.asyncio
    @patch("memory.summarizer.get_channel_context_store")
    async def test_success_resets_backoff(self, mock_get_store):
        summarizer = Summarizer()
        summarizer._backoff.record_failure(1)
        with patch.object(
            summarizer, "_call_summarize_llm",
            return_value={"summary": "s", "mood": None, "topic_keywords": None},
        ):
            await summarizer._run_summarize(1, ChannelContext(channel_id=1), [])

        assert summarizer._backoff.failure_count(1) == 0
        mock_get_store.return_value.save_context.assert_called_once()

    @patch("memory.summarizer.get_channel_context_store")
    def test_maybe_summarize_skips_while_blocked(self, mock_get_store):
        mock_get_store.return_value.get_context.return_value.should_summarize.return_value = True
        summarizer = Summarizer()
        summarizer._backoff.record_failure(1)

        with patch("memory.summarizer.asyncio.create_task") as mock_task:
            summarizer.maybe_summarize(1, [])

        mock_task.assert_not_called()
        assert 1 not in summarizer._running
