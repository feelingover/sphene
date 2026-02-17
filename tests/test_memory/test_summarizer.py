# type: ignore
# mypy: ignore-errors

"""Summarizerモジュールのテスト"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from memory.channel_context import ChannelContext
from memory.short_term import ChannelMessage
from memory.summarizer import (
    Summarizer,
    _extract_active_users,
    _format_messages_for_summary,
    get_summarizer,
)


def _make_message(
    author_name: str = "TestUser",
    content: str = "テストメッセージ",
    is_bot: bool = False,
    message_id: int = 1,
    channel_id: int = 100,
    author_id: int = 1000,
) -> ChannelMessage:
    """テスト用ChannelMessageファクトリ"""
    return ChannelMessage(
        message_id=message_id,
        channel_id=channel_id,
        author_id=author_id,
        author_name=author_name,
        content=content,
        timestamp=datetime.now(timezone.utc),
        is_bot=is_bot,
    )


class TestFormatMessagesForSummary:
    """_format_messages_for_summaryのテスト"""

    def test_empty_list_returns_empty_string(self):
        """空リストの場合、空文字列を返すこと"""
        result = _format_messages_for_summary([])
        assert result == ""

    def test_normal_messages(self):
        """通常メッセージが正しくフォーマットされること"""
        messages = [
            _make_message(author_name="Alice", content="こんにちは"),
            _make_message(author_name="Bob", content="やあ"),
        ]
        result = _format_messages_for_summary(messages)
        assert result == "Alice: こんにちは\nBob: やあ"

    def test_bot_messages_get_bot_tag(self):
        """Botメッセージに[BOT]タグが付くこと"""
        messages = [
            _make_message(author_name="Alice", content="質問です"),
            _make_message(author_name="アサヒ", content="回答です", is_bot=True),
        ]
        result = _format_messages_for_summary(messages)
        assert "Alice: 質問です" in result
        assert "アサヒ[BOT]: 回答です" in result

    def test_single_message(self):
        """メッセージが1件の場合も正しくフォーマットされること"""
        messages = [_make_message(author_name="Solo", content="一人です")]
        result = _format_messages_for_summary(messages)
        assert result == "Solo: 一人です"

    def test_bot_only_messages(self):
        """Botメッセージのみの場合も正しく動作すること"""
        messages = [
            _make_message(author_name="Bot1", content="ボット1", is_bot=True),
            _make_message(author_name="Bot2", content="ボット2", is_bot=True),
        ]
        result = _format_messages_for_summary(messages)
        assert "Bot1[BOT]: ボット1" in result
        assert "Bot2[BOT]: ボット2" in result


class TestExtractActiveUsers:
    """_extract_active_usersのテスト"""

    def test_empty_list_returns_empty(self):
        """空リストの場合、空リストを返すこと"""
        result = _extract_active_users([])
        assert result == []

    def test_normal_users(self):
        """通常ユーザーが抽出されること"""
        messages = [
            _make_message(author_name="Alice"),
            _make_message(author_name="Bob"),
        ]
        result = _extract_active_users(messages)
        assert result == ["Alice", "Bob"]

    def test_bot_users_excluded(self):
        """Botユーザーが除外されること"""
        messages = [
            _make_message(author_name="Alice"),
            _make_message(author_name="BotUser", is_bot=True),
            _make_message(author_name="Bob"),
        ]
        result = _extract_active_users(messages)
        assert result == ["Alice", "Bob"]
        assert "BotUser" not in result

    def test_duplicates_removed(self):
        """重複ユーザーが除外されること"""
        messages = [
            _make_message(author_name="Alice"),
            _make_message(author_name="Bob"),
            _make_message(author_name="Alice"),
            _make_message(author_name="Bob"),
        ]
        result = _extract_active_users(messages)
        assert result == ["Alice", "Bob"]

    def test_order_preserved(self):
        """出現順が保持されること"""
        messages = [
            _make_message(author_name="Charlie"),
            _make_message(author_name="Alice"),
            _make_message(author_name="Bob"),
            _make_message(author_name="Alice"),
        ]
        result = _extract_active_users(messages)
        assert result == ["Charlie", "Alice", "Bob"]

    def test_all_bots_returns_empty(self):
        """全てBotの場合、空リストを返すこと"""
        messages = [
            _make_message(author_name="Bot1", is_bot=True),
            _make_message(author_name="Bot2", is_bot=True),
        ]
        result = _extract_active_users(messages)
        assert result == []


class TestSummarizerMaybeSummarize:
    """Summarizer.maybe_summarizeのテスト"""

    @patch("memory.summarizer.get_channel_context_store")
    def test_skip_when_should_summarize_false(self, mock_get_store):
        """should_summarizeがFalseの場合、要約がスキップされること"""
        mock_ctx = MagicMock()
        mock_ctx.should_summarize.return_value = False
        mock_store = MagicMock()
        mock_store.get_context.return_value = mock_ctx
        mock_get_store.return_value = mock_store

        summarizer = Summarizer()
        messages = [_make_message()]

        with patch("memory.summarizer.asyncio.ensure_future") as mock_future:
            summarizer.maybe_summarize(100, messages)
            mock_future.assert_not_called()

    @patch("memory.summarizer.get_channel_context_store")
    def test_skip_when_already_running(self, mock_get_store):
        """既に実行中の場合、重複実行を防止すること"""
        mock_ctx = MagicMock()
        mock_ctx.should_summarize.return_value = True
        mock_store = MagicMock()
        mock_store.get_context.return_value = mock_ctx
        mock_get_store.return_value = mock_store

        summarizer = Summarizer()
        summarizer._running.add(100)  # 既に実行中
        messages = [_make_message()]

        with patch("memory.summarizer.asyncio.ensure_future") as mock_future:
            summarizer.maybe_summarize(100, messages)
            mock_future.assert_not_called()

    @patch("memory.summarizer.get_channel_context_store")
    def test_trigger_when_should_summarize_true(self, mock_get_store):
        """should_summarizeがTrueの場合、asyncio.ensure_futureが呼ばれること"""
        mock_ctx = MagicMock()
        mock_ctx.should_summarize.return_value = True
        mock_ctx.message_count_since_update = 20
        mock_store = MagicMock()
        mock_store.get_context.return_value = mock_ctx
        mock_get_store.return_value = mock_store

        summarizer = Summarizer()
        messages = [_make_message()]

        with patch("memory.summarizer.asyncio.ensure_future") as mock_future:
            summarizer.maybe_summarize(100, messages)
            mock_future.assert_called_once()

    @patch("memory.summarizer.get_channel_context_store")
    def test_different_channel_not_blocked(self, mock_get_store):
        """異なるチャンネルが実行中でも、別チャンネルはブロックされないこと"""
        mock_ctx = MagicMock()
        mock_ctx.should_summarize.return_value = True
        mock_ctx.message_count_since_update = 20
        mock_store = MagicMock()
        mock_store.get_context.return_value = mock_ctx
        mock_get_store.return_value = mock_store

        summarizer = Summarizer()
        summarizer._running.add(200)  # 別チャンネルが実行中
        messages = [_make_message()]

        with patch("memory.summarizer.asyncio.ensure_future") as mock_future:
            summarizer.maybe_summarize(100, messages)
            mock_future.assert_called_once()


class TestSummarizerCallSummarizeLlm:
    """Summarizer._call_summarize_llmのテスト"""

    @patch("memory.summarizer.config")
    @patch("memory.summarizer.get_model_name")
    @patch("memory.summarizer._get_genai_client")
    def test_success(self, mock_get_client, mock_get_model, mock_config):
        """LLM呼び出しが成功した場合、解析済み辞書を返すこと"""
        mock_config.SUMMARIZE_MODEL = ""
        mock_get_model.return_value = "gemini-2.5-flash"

        expected_result = {
            "summary": "テスト要約",
            "mood": "楽しい",
            "topic_keywords": ["Python", "テスト"],
        }
        mock_response = MagicMock()
        mock_response.text = json.dumps(expected_result, ensure_ascii=False)
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        summarizer = Summarizer()
        context = ChannelContext(channel_id=100, summary="前回の要約")
        messages = [
            _make_message(author_name="Alice", content="こんにちは"),
            _make_message(author_name="Bob", content="やあ"),
        ]

        result = summarizer._call_summarize_llm(context, messages)

        assert result is not None
        assert result["summary"] == "テスト要約"
        assert result["mood"] == "楽しい"
        assert result["topic_keywords"] == ["Python", "テスト"]
        mock_client.models.generate_content.assert_called_once()

    @patch("memory.summarizer.config")
    @patch("memory.summarizer.get_model_name")
    @patch("memory.summarizer._get_genai_client")
    def test_uses_summarize_model_when_set(self, mock_get_client, mock_get_model, mock_config):
        """SUMMARIZE_MODELが設定されている場合、そのモデルを使用すること"""
        mock_config.SUMMARIZE_MODEL = "gemini-2.5-pro"

        mock_response = MagicMock()
        mock_response.text = json.dumps({"summary": "要約", "mood": "", "topic_keywords": []})
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        summarizer = Summarizer()
        context = ChannelContext(channel_id=100)
        messages = [_make_message()]

        summarizer._call_summarize_llm(context, messages)

        call_args = mock_client.models.generate_content.call_args
        assert call_args.kwargs["model"] == "gemini-2.5-pro"
        mock_get_model.assert_not_called()

    @patch("memory.summarizer.config")
    @patch("memory.summarizer.get_model_name")
    @patch("memory.summarizer._get_genai_client")
    def test_falls_back_to_default_model(self, mock_get_client, mock_get_model, mock_config):
        """SUMMARIZE_MODELが空の場合、get_model_nameのデフォルトを使用すること"""
        mock_config.SUMMARIZE_MODEL = ""
        mock_get_model.return_value = "gemini-2.5-flash"

        mock_response = MagicMock()
        mock_response.text = json.dumps({"summary": "要約", "mood": "", "topic_keywords": []})
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        summarizer = Summarizer()
        context = ChannelContext(channel_id=100)
        messages = [_make_message()]

        summarizer._call_summarize_llm(context, messages)

        call_args = mock_client.models.generate_content.call_args
        assert call_args.kwargs["model"] == "gemini-2.5-flash"
        mock_get_model.assert_called_once()

    @patch("memory.summarizer.config")
    @patch("memory.summarizer.get_model_name")
    @patch("memory.summarizer._get_genai_client")
    def test_empty_messages_returns_none(self, mock_get_client, mock_get_model, mock_config):
        """メッセージが空の場合、Noneを返すこと"""
        mock_config.SUMMARIZE_MODEL = ""
        mock_get_model.return_value = "gemini-2.5-flash"

        summarizer = Summarizer()
        context = ChannelContext(channel_id=100)
        messages = []

        result = summarizer._call_summarize_llm(context, messages)

        assert result is None
        mock_get_client.return_value.models.generate_content.assert_not_called()

    @patch("memory.summarizer.config")
    @patch("memory.summarizer.get_model_name")
    @patch("memory.summarizer._get_genai_client")
    def test_empty_response_text_returns_none(self, mock_get_client, mock_get_model, mock_config):
        """レスポンスのtextが空の場合、Noneを返すこと"""
        mock_config.SUMMARIZE_MODEL = ""
        mock_get_model.return_value = "gemini-2.5-flash"

        mock_response = MagicMock()
        mock_response.text = ""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        summarizer = Summarizer()
        context = ChannelContext(channel_id=100)
        messages = [_make_message()]

        result = summarizer._call_summarize_llm(context, messages)

        assert result is None

    @patch("memory.summarizer.config")
    @patch("memory.summarizer.get_model_name")
    @patch("memory.summarizer._get_genai_client")
    def test_llm_exception_returns_none(self, mock_get_client, mock_get_model, mock_config):
        """LLM呼び出しで例外が発生した場合、Noneを返すこと"""
        mock_config.SUMMARIZE_MODEL = ""
        mock_get_model.return_value = "gemini-2.5-flash"

        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("API Error")
        mock_get_client.return_value = mock_client

        summarizer = Summarizer()
        context = ChannelContext(channel_id=100)
        messages = [_make_message()]

        result = summarizer._call_summarize_llm(context, messages)

        assert result is None

    @patch("memory.summarizer.config")
    @patch("memory.summarizer.get_model_name")
    @patch("memory.summarizer._get_genai_client")
    def test_invalid_json_returns_none(self, mock_get_client, mock_get_model, mock_config):
        """不正なJSONレスポンスの場合、Noneを返すこと"""
        mock_config.SUMMARIZE_MODEL = ""
        mock_get_model.return_value = "gemini-2.5-flash"

        mock_response = MagicMock()
        mock_response.text = "これはJSONではない"
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        summarizer = Summarizer()
        context = ChannelContext(channel_id=100)
        messages = [_make_message()]

        result = summarizer._call_summarize_llm(context, messages)

        assert result is None

    @patch("memory.summarizer.config")
    @patch("memory.summarizer.get_model_name")
    @patch("memory.summarizer._get_genai_client")
    def test_previous_context_included_in_prompt(self, mock_get_client, mock_get_model, mock_config):
        """前回の要約がある場合、プロンプトに含まれること"""
        mock_config.SUMMARIZE_MODEL = ""
        mock_get_model.return_value = "gemini-2.5-flash"

        mock_response = MagicMock()
        mock_response.text = json.dumps({"summary": "新要約", "mood": "", "topic_keywords": []})
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        summarizer = Summarizer()
        context = ChannelContext(channel_id=100, summary="前回の要約です")
        messages = [_make_message()]

        summarizer._call_summarize_llm(context, messages)

        call_args = mock_client.models.generate_content.call_args
        prompt = call_args.kwargs["contents"]
        assert "前回の要約: 前回の要約です" in prompt


class TestSummarizerApplyResult:
    """Summarizer._apply_resultのテスト"""

    def test_all_fields_updated(self):
        """全フィールドが正しく更新されること"""
        summarizer = Summarizer()
        context = ChannelContext(
            channel_id=100,
            summary="古い要約",
            mood="古い雰囲気",
            topic_keywords=["古い話題"],
            message_count_since_update=15,
        )
        result = {
            "summary": "新しい要約",
            "mood": "楽しい",
            "topic_keywords": ["Python", "Discord"],
        }
        messages = [
            _make_message(author_name="Alice"),
            _make_message(author_name="Bob"),
        ]

        summarizer._apply_result(context, result, messages)

        assert context.summary == "新しい要約"
        assert context.mood == "楽しい"
        assert context.topic_keywords == ["Python", "Discord"]
        assert context.active_users == ["Alice", "Bob"]
        assert context.message_count_since_update == 0

    def test_counter_reset_to_zero(self):
        """メッセージカウンタが0にリセットされること"""
        summarizer = Summarizer()
        context = ChannelContext(
            channel_id=100,
            message_count_since_update=42,
        )
        result = {"summary": "要約", "mood": "", "topic_keywords": []}
        messages = [_make_message()]

        summarizer._apply_result(context, result, messages)

        assert context.message_count_since_update == 0

    def test_last_updated_set(self):
        """last_updatedが更新されること"""
        summarizer = Summarizer()
        old_time = datetime(2020, 1, 1, tzinfo=timezone.utc)
        context = ChannelContext(
            channel_id=100,
            last_updated=old_time,
        )
        result = {"summary": "要約", "mood": "", "topic_keywords": []}
        messages = [_make_message()]

        summarizer._apply_result(context, result, messages)

        assert context.last_updated > old_time
        assert context.last_updated.tzinfo == timezone.utc

    def test_missing_keys_keep_old_values(self):
        """結果に含まれないキーは元の値を保持すること"""
        summarizer = Summarizer()
        context = ChannelContext(
            channel_id=100,
            summary="元の要約",
            mood="元の雰囲気",
            topic_keywords=["元の話題"],
        )
        result = {}  # キーなし
        messages = [_make_message()]

        summarizer._apply_result(context, result, messages)

        assert context.summary == "元の要約"
        assert context.mood == "元の雰囲気"
        assert context.topic_keywords == ["元の話題"]
        # カウンタは常にリセットされる
        assert context.message_count_since_update == 0

    def test_active_users_extracted_from_messages(self):
        """active_usersがメッセージから正しく抽出されること"""
        summarizer = Summarizer()
        context = ChannelContext(channel_id=100)
        result = {"summary": "要約", "mood": "", "topic_keywords": []}
        messages = [
            _make_message(author_name="Alice"),
            _make_message(author_name="BotUser", is_bot=True),
            _make_message(author_name="Bob"),
            _make_message(author_name="Alice"),  # 重複
        ]

        summarizer._apply_result(context, result, messages)

        assert context.active_users == ["Alice", "Bob"]


class TestGetSummarizer:
    """get_summarizerシングルトンのテスト"""

    def test_returns_summarizer_instance(self):
        """Summarizerインスタンスを返すこと"""
        import memory.summarizer as mod

        mod._summarizer = None  # シングルトンをリセット
        instance = get_summarizer()
        assert isinstance(instance, Summarizer)
        mod._summarizer = None  # テスト後にクリーンアップ

    def test_singleton_returns_same_instance(self):
        """同一インスタンスが返されること"""
        import memory.summarizer as mod

        mod._summarizer = None  # シングルトンをリセット
        instance1 = get_summarizer()
        instance2 = get_summarizer()
        assert instance1 is instance2
        mod._summarizer = None  # テスト後にクリーンアップ

    def test_creates_new_when_none(self):
        """_summarizerがNoneの場合に新しいインスタンスが作成されること"""
        import memory.summarizer as mod

        mod._summarizer = None
        assert mod._summarizer is None
        instance = get_summarizer()
        assert mod._summarizer is not None
        assert mod._summarizer is instance
        mod._summarizer = None  # テスト後にクリーンアップ
