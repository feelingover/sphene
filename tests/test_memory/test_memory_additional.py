"""
memory 関連の追加テスト
"""

import asyncio
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
import uuid

# ChannelContext
from memory.channel_context import get_channel_context_store, ChannelContext, ChannelContextStore
# UserProfile
from memory.user_profile import get_user_profile_store, UserProfile, UserProfileStore
# FactStore
from memory.fact_store import get_fact_store, FactStore, Fact
# LLMJudge
from memory.llm_judge import get_llm_judge, LLMJudge
# Reflection
from memory.reflection import get_reflection_engine, ReflectionEngine, _format_messages_for_reflection
from memory.short_term import ChannelMessage

class TestMemoryAdditional:
    """各メモリコンポーネントの追加テスト"""

    # --- ChannelContext ---
    def test_get_channel_context_store_singleton(self):
        import memory.channel_context
        memory.channel_context._store = None
        store1 = get_channel_context_store()
        assert get_channel_context_store() is store1

    def test_channel_context_load_exception(self):
        store = ChannelContextStore()
        with (
            patch("memory.channel_context.os.path.exists", return_value=True),
            patch("builtins.open", side_effect=Exception("Read error")),
        ):
            assert store._load_from_local(123) is None

    @patch("utils.firestore_client.get_firestore_client")
    def test_channel_context_firestore(self, mock_get_db):
        store = ChannelContextStore()
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {"summary": "test", "last_updated": "2025-01-01T00:00:00+00:00"}
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc
        
        result = store._load_from_firestore(123)
        assert result.summary == "test"

    # --- UserProfile ---
    def test_get_user_profile_store_singleton(self):
        import memory.user_profile
        memory.user_profile._store = None
        store1 = get_user_profile_store()
        assert get_user_profile_store() is store1

    def test_user_profile_save_exception(self):
        store = UserProfileStore()
        profile = UserProfile(user_id=123, display_name="Test")
        with patch("utils.file_utils.atomic_write_json", side_effect=Exception("Write error")):
            store._save_to_local(profile) # Should not crash

    # --- FactStore ---
    def test_get_fact_store_singleton(self):
        import memory.fact_store
        memory.fact_store._fact_store = None
        store1 = get_fact_store()
        assert get_fact_store() is store1

    def test_fact_decay_factor_no_tz(self):
        fact = Fact("f1", 123, "test", [], [], datetime.now() - timedelta(days=1))
        assert 0 <= fact.decay_factor(7) <= 1

    # --- LLMJudge ---
    def test_get_llm_judge_singleton(self):
        import memory.llm_judge
        memory.llm_judge._llm_judge = None
        judge1 = get_llm_judge()
        assert get_llm_judge() is judge1

    @pytest.mark.asyncio
    async def test_llm_judge_exception(self):
        judge = LLMJudge()
        with patch("asyncio.to_thread", side_effect=Exception("error")):
            res, rtype, should_react, reaction_emojis = await judge.evaluate("t", "c", "B")
            assert res is False
            assert rtype == "react_only"
            assert should_react is False
            assert reaction_emojis == []

    # --- Reflection ---
    def test_get_reflection_engine_singleton(self):
        import memory.reflection
        memory.reflection._reflection_engine = None
        engine1 = get_reflection_engine()
        assert get_reflection_engine() is engine1

    def test_reflection_apply_facts_filtering(self):
        engine = ReflectionEngine()
        raw_facts = [{"content": "valid", "source_user_ids": [123, "inv"]}]
        with (
            patch("memory.fact_store.get_fact_store") as mock_store_fn,
            patch("memory.short_term.get_channel_buffer") as mock_buffer_fn,
        ):
            mock_store = MagicMock()
            mock_store_fn.return_value = mock_store
            with patch("ai.client.generate_embedding", return_value=None):
                asyncio.run(engine._apply_facts(123, raw_facts, []))
            mock_store.add_fact.assert_called_once()
            fact = mock_store.add_fact.call_args[0][0]
            assert fact.source_user_ids == [123]
