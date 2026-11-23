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
    guild_id: int | None = 1,
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
        guild_id=guild_id,
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
                with patch("memory.reflection.get_model_name", return_value="test-model"):
                    result = engine._call_reflection_llm(messages)

        assert result is None

    def test_returns_none_on_exception(self):
        """例外発生時に None を返すこと"""
        engine = ReflectionEngine()
        messages = [_make_message()]

        with patch("memory.reflection.get_genai_client"):
            with patch("memory.reflection._generate_content_with_retry", side_effect=Exception("API エラー")):
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
                with patch("ai.client.generate_embedding", return_value=None):
                    asyncio.run(engine._apply_facts(100, raw_facts, messages))

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
                with patch("ai.client.generate_embedding", return_value=None):
                    asyncio.run(engine._apply_facts(100, raw_facts, messages))

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
                with patch("ai.client.generate_embedding", return_value=None):
                    asyncio.run(engine._apply_facts(100, raw_facts, messages))

        # 処理したメッセージの最大タイムスタンプでチェックポイントを進める
        mock_buffer.mark_reflected.assert_called_once_with(100, until=messages[0].timestamp)

    def test_skips_non_dict_items(self):
        """辞書でないアイテムはスキップされること"""
        engine = ReflectionEngine()
        messages = [_make_message()]
        raw_facts = ["文字列", 123, {"content": "有効", "keywords": [], "source_user_ids": [], "shareable": False}]

        mock_store = MagicMock()
        mock_buffer = MagicMock()

        with patch("memory.fact_store.get_fact_store", return_value=mock_store):
            with patch("memory.short_term.get_channel_buffer", return_value=mock_buffer):
                with patch("ai.client.generate_embedding", return_value=None):
                    asyncio.run(engine._apply_facts(100, raw_facts, messages))

        assert mock_store.add_fact.call_count == 1

class TestApplyFactsWithEmbedding:
    """_apply_facts の Embedding 生成テスト"""

    def test_embedding_stored_in_fact(self):
        """generate_embedding の戻り値が fact.embedding に保存されること"""
        engine = ReflectionEngine()
        messages = [_make_message()]
        raw_facts = [
            {"content": "ファクト", "keywords": ["kw"], "source_user_ids": [1], "shareable": False},
        ]

        mock_store = MagicMock()
        mock_buffer = MagicMock()
        fake_embedding = [0.1, 0.2, 0.3]

        with patch("memory.fact_store.get_fact_store", return_value=mock_store):
            with patch("memory.short_term.get_channel_buffer", return_value=mock_buffer):
                with patch("ai.client.generate_embedding", return_value=fake_embedding):
                    asyncio.run(engine._apply_facts(100, raw_facts, messages))

        saved_fact = mock_store.add_fact.call_args[0][0]
        assert saved_fact.embedding == fake_embedding

    def test_embedding_none_on_failure(self):
        """generate_embedding が None を返した場合も fact が保存されること"""
        engine = ReflectionEngine()
        messages = [_make_message()]
        raw_facts = [
            {"content": "ファクト", "keywords": [], "source_user_ids": [], "shareable": False},
        ]

        mock_store = MagicMock()
        mock_buffer = MagicMock()

        with patch("memory.fact_store.get_fact_store", return_value=mock_store):
            with patch("memory.short_term.get_channel_buffer", return_value=mock_buffer):
                with patch("ai.client.generate_embedding", return_value=None):
                    asyncio.run(engine._apply_facts(100, raw_facts, messages))

        assert mock_store.add_fact.call_count == 1
        saved_fact = mock_store.add_fact.call_args[0][0]
        assert saved_fact.embedding is None


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


class TestUserProfileTags:
    """LIVING_MEMORY_ENABLED フラグのテスト（ユーザープロファイルタグ抽出）"""

    @pytest.mark.asyncio
    async def test_user_profile_llm_not_called_when_disabled(self):
        """LIVING_MEMORY_ENABLED=False のとき _call_user_profile_llm が呼ばれないこと"""
        engine = ReflectionEngine()
        messages = [_make_message() for _ in range(15)]

        with patch("config.LIVING_MEMORY_ENABLED", False):
            with patch.object(engine, "_call_reflection_llm", return_value=[]):
                with patch.object(engine, "_apply_facts"):
                    with patch.object(engine, "_call_user_profile_llm") as mock_profile_llm:
                        await engine._run_reflect(100, messages)
                        mock_profile_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_user_profile_llm_called_when_enabled(self):
        """LIVING_MEMORY_ENABLED=True のとき _call_user_profile_llm が呼ばれること"""
        engine = ReflectionEngine()
        messages = [_make_message() for _ in range(15)]

        with patch("config.LIVING_MEMORY_ENABLED", True):
            with patch.object(engine, "_call_reflection_llm", return_value=[]):
                with patch.object(engine, "_apply_facts"):
                    with patch.object(engine, "_call_user_profile_llm") as mock_profile_llm:
                        await engine._run_reflect(100, messages)
                        mock_profile_llm.assert_called_once_with(messages)

    def test_call_user_profile_llm_parses_and_updates(self):
        """_call_user_profile_llm が正常にパースし update_from_reflection を呼ぶこと"""
        engine = ReflectionEngine()
        messages = [_make_message(author_id=12345)]

        mock_response = MagicMock()
        mock_response.text = '[{"user_id": 12345, "tags": ["プログラマー"], "notable_facts": ["東京在住"], "personality_notes": "明るい", "last_conversation_summary": "テスト", "preferred_tone": null, "emotional_state_last": "楽しそう", "nickname": "ポチ"}]'

        mock_store = MagicMock()

        with patch("memory.reflection.get_genai_client"):
            with patch("memory.reflection._generate_content_with_retry", return_value=mock_response):
                with patch("memory.reflection.get_model_name", return_value="test-model"):
                    with patch("memory.user_profile.get_user_profile_store", return_value=mock_store):
                        engine._call_user_profile_llm(messages)

        mock_store.update_from_reflection.assert_called_once_with(1, 12345, {
            "user_id": 12345,
            "tags": ["プログラマー"],
            "notable_facts": ["東京在住"],
            "personality_notes": "明るい",
            "last_conversation_summary": "テスト",
            "preferred_tone": None,
            "emotional_state_last": "楽しそう",
            "nickname": "ポチ",
        })
        mock_store.persist_all.assert_called_once()

    def test_call_user_profile_llm_handles_invalid_json(self):
        """不正なJSONの場合、例外を発生させず警告ログを出すこと"""
        engine = ReflectionEngine()
        messages = [_make_message()]

        mock_response = MagicMock()
        mock_response.text = "invalid json"

        with patch("memory.reflection.get_genai_client"):
            with patch("memory.reflection._generate_content_with_retry", return_value=mock_response):
                with patch("memory.reflection.get_model_name", return_value="test-model"):
                    # 例外が発生しないこと
                    engine._call_user_profile_llm(messages)

    def test_call_user_profile_llm_skips_empty_messages(self):
        """空メッセージのとき何も実行しないこと"""
        engine = ReflectionEngine()

        with patch("memory.reflection.get_genai_client"):
            with patch("memory.reflection._generate_content_with_retry") as mock_api:
                engine._call_user_profile_llm([])
                mock_api.assert_not_called()



class TestApplyUserProfileResults:
    """_apply_user_profile_results の user_id 照合テスト"""

    def test_only_updates_authors_in_conversation(self):
        """会話に登場した人間ユーザーのみ更新し、それ以外のIDは無視すること"""
        from memory.reflection import _apply_user_profile_results

        messages = [
            _make_message(author_id=111),
            _make_message(author_id=999, is_bot=True),
        ]
        result = [
            {"user_id": 111, "nickname": "本人"},
            {"user_id": "222", "nickname": "部外者"},
            {"user_id": 999, "nickname": "ボット"},
            {"user_id": True, "nickname": "bool"},
            "not-a-dict",
        ]
        mock_store = MagicMock()
        with patch("memory.user_profile.get_user_profile_store", return_value=mock_store):
            count = _apply_user_profile_results(result, messages)

        assert count == 1
        mock_store.update_from_reflection.assert_called_once_with(1, 111, result[0])

    def test_accepts_numeric_string_user_id(self):
        """数字文字列の user_id も発言者と一致すれば受け付けること"""
        from memory.reflection import _apply_user_profile_results

        messages = [_make_message(author_id=111)]
        mock_store = MagicMock()
        with patch("memory.user_profile.get_user_profile_store", return_value=mock_store):
            count = _apply_user_profile_results([{"user_id": "111"}], messages)

        assert count == 1
        mock_store.update_from_reflection.assert_called_once_with(1, 111, {"user_id": "111"})


class TestParseFactItem:
    """_parse_fact_item の検証テスト"""

    def test_rejects_non_string_content(self):
        """content が文字列でなければ None を返すこと"""
        from memory.reflection import _parse_fact_item

        assert _parse_fact_item({"content": 123}) is None
        assert _parse_fact_item({"content": "   "}) is None
        assert _parse_fact_item("text") is None

    def test_normalizes_fields(self):
        """keywords・source_user_ids・shareable を正規化すること"""
        from memory.reflection import _parse_fact_item

        parsed = _parse_fact_item(
            {
                "content": "猫を\n飼っている",
                "keywords": "猫",
                "source_user_ids": [1, "2", "x", True],
                "shareable": "yes",
            }
        )
        assert parsed == {
            "content": "猫を 飼っている",
            "keywords": [],
            "source_user_ids": [1, 2],
            "shareable": False,
        }


class TestApplyFactsCheckpoint:
    """_apply_facts のチェックポイント更新テスト"""

    def test_marks_reflected_even_if_all_duplicates(self):
        """全件重複でスキップされても、処理済みとしてチェックポイントを進めること"""
        engine = ReflectionEngine()
        messages = [_make_message()]
        raw_facts = [{"content": "既知のファクト"}]
        mock_store = MagicMock()
        mock_store.add_fact.return_value = False
        mock_buffer = MagicMock()

        with patch("memory.fact_store.get_fact_store", return_value=mock_store), \
             patch("memory.short_term.get_channel_buffer", return_value=mock_buffer), \
             patch("ai.client.generate_embedding", return_value=None):
            asyncio.run(engine._apply_facts(100, raw_facts, messages))

        mock_store.persist_channel.assert_not_called()
        mock_buffer.mark_reflected.assert_called_once_with(100, until=messages[0].timestamp)

    def test_does_not_mark_when_all_invalid(self):
        """全件不正な場合はチェックポイントを進めないこと"""
        engine = ReflectionEngine()
        messages = [_make_message()]
        mock_buffer = MagicMock()

        with patch("memory.fact_store.get_fact_store", return_value=MagicMock()), \
             patch("memory.short_term.get_channel_buffer", return_value=mock_buffer), \
             patch("ai.client.generate_embedding", return_value=None):
            asyncio.run(engine._apply_facts(100, [{"content": None}], messages))

        mock_buffer.mark_reflected.assert_not_called()



class TestApplyUserProfileResultsGuildScope:
    """_apply_user_profile_results のギルド分離テスト"""

    def test_updates_profile_of_conversation_guild(self):
        """会話が行われたギルドのプロファイルだけを更新すること"""
        from memory.reflection import _apply_user_profile_results

        messages = [_make_message(author_id=111, guild_id=42)]
        mock_store = MagicMock()
        with patch("memory.user_profile.get_user_profile_store", return_value=mock_store):
            _apply_user_profile_results([{"user_id": 111}], messages)

        mock_store.update_from_reflection.assert_called_once_with(42, 111, {"user_id": 111})

    def test_skips_when_guild_unknown(self):
        """ギルドIDが不明なメッセージのみの場合は更新しないこと"""
        from memory.reflection import _apply_user_profile_results

        messages = [_make_message(author_id=111, guild_id=None)]
        mock_store = MagicMock()
        with patch("memory.user_profile.get_user_profile_store", return_value=mock_store):
            count = _apply_user_profile_results([{"user_id": 111}], messages)

        assert count == 0
        mock_store.update_from_reflection.assert_not_called()
