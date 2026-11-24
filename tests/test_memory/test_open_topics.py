"""未解決の話題（open_topics）の抽出・永続化のテスト"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from memory.channel_context import ChannelContext
from memory.open_topics import (
    JST,
    MAX_OPEN_TOPICS,
    OpenTopic,
    format_now_jst,
    format_open_topics_for_prompt,
    load_open_topics,
    parse_follow_up_after,
    parse_open_topics_result,
)
from memory.short_term import ChannelMessage
from memory.summarizer import Summarizer, _parse_summary_result


def _topic(topic_id: str = "abc12345", **kwargs) -> OpenTopic:
    defaults: dict = {"text": "土曜にレイド挑戦", "kind": "plan", "follow_up_after": None}
    defaults.update(kwargs)
    return OpenTopic(id=topic_id, **defaults)


def _msg() -> ChannelMessage:
    return ChannelMessage(
        message_id=1, channel_id=1, author_id=1, author_name="U",
        content="c", timestamp=datetime.now(timezone.utc),
    )


class TestParseFollowUpAfter:
    def test_aware_iso_is_converted_to_utc(self):
        result = parse_follow_up_after("2026-11-28T21:00+09:00")
        assert result == datetime(2026, 11, 28, 12, 0, tzinfo=timezone.utc)

    def test_naive_iso_is_treated_as_jst(self):
        result = parse_follow_up_after("2026-11-28T21:00")
        assert result == datetime(2026, 11, 28, 12, 0, tzinfo=timezone.utc)

    def test_datetime_is_accepted(self):
        value = datetime(2026, 11, 28, 12, 0, tzinfo=timezone.utc)
        assert parse_follow_up_after(value) == value

    @pytest.mark.parametrize("value", [None, "", "  ", "来週の土曜", "2026-13-40", 123, ["x"]])
    def test_invalid_values_become_none(self, value):
        assert parse_follow_up_after(value) is None


class TestParseOpenTopicsResult:
    @pytest.mark.parametrize("raw", [None, "話題", 1, {"id": "a"}])
    def test_missing_or_non_list_returns_none(self, raw):
        """キーの欠落・型不正は None（前回値を維持させる）"""
        assert parse_open_topics_result(raw, [_topic()]) is None

    def test_empty_list_clears_topics(self):
        assert parse_open_topics_result([], [_topic()]) == []

    def test_valid_topic_is_parsed(self):
        result = parse_open_topics_result(
            [{"id": None, "text": "ボス攻略の結果", "kind": "plan",
              "follow_up_after": "2026-11-28T21:00+09:00"}],
            [],
        )
        assert result is not None and len(result) == 1
        assert result[0].text == "ボス攻略の結果"
        assert result[0].kind == "plan"
        assert result[0].follow_up_after == datetime(2026, 11, 28, 12, 0, tzinfo=timezone.utc)
        assert len(result[0].id) == 8

    @pytest.mark.parametrize("kind", ["todo", None, "", 1, "PLAN"])
    def test_invalid_kind_is_dropped(self, kind):
        result = parse_open_topics_result(
            [{"id": None, "text": "x", "kind": kind}, {"id": None, "text": "y", "kind": "question"}],
            [],
        )
        assert [t.text for t in result] == ["y"]

    @pytest.mark.parametrize("text", [None, "", "   ", 1, ["x"]])
    def test_empty_text_is_dropped(self, text):
        assert parse_open_topics_result([{"id": None, "text": text, "kind": "plan"}], []) == []

    def test_non_dict_items_are_dropped(self):
        result = parse_open_topics_result(["x", 1, None, {"text": "ok", "kind": "pending"}], [])
        assert [t.text for t in result] == ["ok"]

    def test_text_is_sanitized_and_truncated(self):
        result = parse_open_topics_result(
            [{"id": None, "text": "一行目\n二行目" + "あ" * 200, "kind": "plan"}], []
        )
        assert "\n" not in result[0].text
        assert len(result[0].text) == 100

    @pytest.mark.parametrize("value", [None, "不明", 42])
    def test_null_or_invalid_follow_up_after_becomes_none(self, value):
        result = parse_open_topics_result(
            [{"id": None, "text": "x", "kind": "plan", "follow_up_after": value}], []
        )
        assert result[0].follow_up_after is None

    def test_count_is_limited(self):
        raw = [{"id": None, "text": f"話題{i}", "kind": "plan"} for i in range(MAX_OPEN_TOPICS + 3)]
        result = parse_open_topics_result(raw, [])
        assert len(result) == MAX_OPEN_TOPICS
        assert result[-1].text == f"話題{MAX_OPEN_TOPICS - 1}"

    def test_known_id_is_kept(self):
        previous = [_topic("keep0001")]
        result = parse_open_topics_result(
            [{"id": "keep0001", "text": "土曜のレイド（延期）", "kind": "plan"}], previous
        )
        assert result[0].id == "keep0001"
        assert result[0].text == "土曜のレイド（延期）"

    @pytest.mark.parametrize("raw_id", [None, "unknown1", 123, ""])
    def test_unknown_or_null_id_gets_new_id(self, raw_id):
        result = parse_open_topics_result(
            [{"id": raw_id, "text": "x", "kind": "plan"}], [_topic("keep0001")]
        )
        assert result[0].id not in ("keep0001", raw_id)
        assert len(result[0].id) == 8

    def test_duplicate_known_id_is_reassigned(self):
        result = parse_open_topics_result(
            [{"id": "keep0001", "text": "a", "kind": "plan"},
             {"id": "keep0001", "text": "b", "kind": "plan"}],
            [_topic("keep0001")],
        )
        assert result[0].id == "keep0001"
        assert result[1].id != "keep0001"

    def test_new_ids_are_unique(self):
        raw = [{"id": None, "text": f"t{i}", "kind": "plan"} for i in range(MAX_OPEN_TOPICS)]
        ids = [t.id for t in parse_open_topics_result(raw, [])]
        assert len(set(ids)) == len(ids)


class TestFormatForPrompt:
    def test_empty_topics(self):
        assert format_open_topics_for_prompt([]) == "[]"

    def test_topics_are_json_with_jst_time(self):
        topic = _topic(follow_up_after=datetime(2026, 11, 28, 12, 0, tzinfo=timezone.utc))
        data = json.loads(format_open_topics_for_prompt([topic, _topic("b", kind="question")]))
        assert data[0] == {
            "id": "abc12345", "text": "土曜にレイド挑戦", "kind": "plan",
            "follow_up_after": "2026-11-28T21:00+09:00",
        }
        assert data[1]["follow_up_after"] is None

    def test_format_now_jst(self):
        now = datetime(2026, 11, 24, 12, 30, tzinfo=timezone.utc)
        assert format_now_jst(now) == "2026-11-24T21:30+09:00（火）"

    def test_format_now_jst_defaults_to_current_time(self):
        assert "+09:00" in format_now_jst()


class TestOpenTopicSerialization:
    def test_round_trip(self):
        topic = _topic(follow_up_after=datetime(2026, 11, 28, 12, 0, tzinfo=timezone.utc))
        assert OpenTopic.from_dict(topic.to_dict()) == topic

    def test_round_trip_without_follow_up(self):
        topic = _topic()
        assert OpenTopic.from_dict(topic.to_dict()) == topic

    @pytest.mark.parametrize("data", [
        None, "x", {}, {"id": "a", "text": "t"}, {"id": "a", "text": "t", "kind": "bad"},
        {"id": "", "text": "t", "kind": "plan"}, {"id": "a", "text": "", "kind": "plan"},
        {"id": 1, "text": "t", "kind": "plan"},
    ])
    def test_invalid_data_returns_none(self, data):
        assert OpenTopic.from_dict(data) is None

    def test_load_open_topics_skips_invalid(self):
        raw = [_topic("a").to_dict(), {"id": "b"}, "x", _topic("c").to_dict()]
        assert [t.id for t in load_open_topics(raw)] == ["a", "c"]

    @pytest.mark.parametrize("raw", [None, "x", {}])
    def test_load_open_topics_non_list(self, raw):
        assert load_open_topics(raw) == []

    def test_load_open_topics_is_limited(self):
        raw = [_topic(str(i)).to_dict() for i in range(MAX_OPEN_TOPICS + 2)]
        assert len(load_open_topics(raw)) == MAX_OPEN_TOPICS


class TestChannelContextOpenTopics:
    def test_round_trip(self):
        ctx = ChannelContext(
            channel_id=1,
            summary="s",
            open_topics=[
                _topic("a", follow_up_after=datetime(2026, 11, 28, 12, 0, tzinfo=timezone.utc)),
                _topic("b", kind="question"),
            ],
        )
        restored = ChannelContext.from_dict(json.loads(json.dumps(ctx.to_dict())))
        assert restored.open_topics == ctx.open_topics

    def test_legacy_data_without_open_topics(self):
        """旧データ（open_topics フィールドなし）も読み込める"""
        restored = ChannelContext.from_dict({
            "channel_id": 1, "summary": "旧要約", "mood": "m", "topic_keywords": ["k"],
            "active_users": [], "last_updated": "2026-01-01T00:00:00+00:00",
            "message_count_since_update": 3,
        })
        assert restored.summary == "旧要約"
        assert restored.open_topics == []

    def test_default_is_empty(self):
        assert ChannelContext(channel_id=1).to_dict()["open_topics"] == []

    def test_not_included_in_injection(self):
        ctx = ChannelContext(channel_id=1, summary="s", open_topics=[_topic(text="秘密の予定")])
        assert "秘密の予定" not in ctx.format_for_injection()


class TestSummarizerOpenTopics:
    def test_parse_summary_result_includes_open_topics(self):
        result = _parse_summary_result(
            {"summary": "s", "open_topics": [{"id": "a", "text": "続き", "kind": "pending"}]},
            [_topic("a")],
        )
        assert [(t.id, t.text) for t in result["open_topics"]] == [("a", "続き")]

    def test_parse_summary_result_without_previous(self):
        result = _parse_summary_result(
            {"summary": "s", "open_topics": [{"id": "a", "text": "新規", "kind": "plan"}]}
        )
        assert result["open_topics"][0].id != "a"

    def test_apply_result_updates_open_topics(self):
        ctx = ChannelContext(channel_id=1, open_topics=[_topic("old")])
        new = [_topic("new")]
        Summarizer()._apply_result(ctx, {"summary": "s", "open_topics": new}, [], 0)
        assert ctx.open_topics == new

    def test_apply_result_keeps_previous_when_none(self):
        ctx = ChannelContext(channel_id=1, open_topics=[_topic("old")])
        parsed = _parse_summary_result({"summary": "s", "open_topics": "壊れた値"}, ctx.open_topics)
        Summarizer()._apply_result(ctx, parsed, [], 0)
        assert [t.id for t in ctx.open_topics] == ["old"]

    def test_apply_result_empty_list_clears(self):
        ctx = ChannelContext(channel_id=1, open_topics=[_topic("old")])
        parsed = _parse_summary_result({"summary": "s", "open_topics": []}, ctx.open_topics)
        Summarizer()._apply_result(ctx, parsed, [], 0)
        assert ctx.open_topics == []

    @patch("memory.summarizer.get_model_name", return_value="m")
    @patch("memory.summarizer._get_genai_client")
    def test_prompt_contains_previous_topics_and_now(self, mock_get_client, _model):
        response = MagicMock()
        response.text = json.dumps({
            "summary": "新要約",
            "open_topics": [
                {"id": "keep0001", "text": "レイド", "kind": "plan", "follow_up_after": None},
                {"id": None, "text": "装備の相談", "kind": "pending", "follow_up_after": None},
            ],
        })
        client = MagicMock()
        client.models.generate_content.return_value = response
        mock_get_client.return_value = client
        ctx = ChannelContext(
            channel_id=1, summary="旧",
            open_topics=[_topic("keep0001"), _topic("gone0002", text="解決済みの質問")],
        )

        fixed_now = "2026-11-24T21:30+09:00（火）"
        with patch("memory.summarizer.format_now_jst", return_value=fixed_now):
            result = Summarizer()._call_summarize_llm(ctx, [_msg()])

        prompt = client.models.generate_content.call_args.kwargs["contents"][0].parts[0].text
        assert f"現在時刻（JST）: {fixed_now}" in prompt
        assert '"id": "keep0001"' in prompt
        assert "解決済みの質問" in prompt
        ids = [t.id for t in result["open_topics"]]
        assert ids[0] == "keep0001"
        assert ids[1] not in ("keep0001", "gone0002")
        assert "gone0002" not in ids

    @patch("memory.summarizer.get_model_name", return_value="m")
    @patch("memory.summarizer._get_genai_client")
    def test_prompt_with_no_previous_topics(self, mock_get_client, _model):
        response = MagicMock()
        response.text = json.dumps({"summary": "s"})
        client = MagicMock()
        client.models.generate_content.return_value = response
        mock_get_client.return_value = client

        result = Summarizer()._call_summarize_llm(ChannelContext(channel_id=1), [_msg()])

        prompt = client.models.generate_content.call_args.kwargs["contents"][0].parts[0].text
        assert "--- 前回の未解決の話題 ---\n[]\n---" in prompt
        assert result["open_topics"] is None


def test_jst_offset():
    assert JST.utcoffset(None) == timedelta(hours=9)


class TestStorePersistence:
    """local / Firestore の両方で open_topics が永続化されること"""

    @patch("memory.channel_context.local_storage_path")
    @patch("memory.channel_context.config")
    def test_local_round_trip(self, mock_config, mock_path, tmp_path):
        from memory.channel_context import ChannelContextStore

        mock_config.STORAGE_TYPE = "local"
        mock_path.side_effect = lambda name: str(tmp_path / name)
        topics = [_topic("a", follow_up_after=datetime(2026, 11, 28, 12, 0, tzinfo=timezone.utc))]

        assert ChannelContextStore().save_context(ChannelContext(channel_id=7, open_topics=topics))
        restored = ChannelContextStore().get_context(7)

        assert restored.open_topics == topics

    @patch("memory.channel_context.config")
    def test_firestore_round_trip(self, mock_config):
        from memory.channel_context import ChannelContextStore

        mock_config.STORAGE_TYPE = "firestore"
        saved: dict = {}
        doc_ref = MagicMock()
        doc_ref.set.side_effect = lambda data: saved.update(data)
        snapshot = MagicMock(exists=True)
        snapshot.to_dict.side_effect = lambda: dict(saved)
        doc_ref.get.return_value = snapshot
        db = MagicMock()
        db.collection.return_value.document.return_value = doc_ref
        topics = [_topic("a"), _topic("b", kind="question")]

        with patch("utils.firestore_client.get_firestore_client", return_value=db):
            ChannelContextStore().save_context(ChannelContext(channel_id=7, open_topics=topics))
            restored = ChannelContextStore().get_context(7)

        assert saved["open_topics"] == [t.to_dict() for t in topics]
        assert restored.open_topics == topics
