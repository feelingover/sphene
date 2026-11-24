"""
bot/events.py の広範なテスト
"""

# type: ignore
# mypy: ignore-errors

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import config
from bot.events import (
    _collect_ai_context,
    _post_response_update,
    _send_chunks,
    is_bot_mentioned,
    process_conversation,
    _handle_on_ready,
    _handle_setup_hook,
    _handle_on_guild_join,
    _handle_on_guild_remove,
    translate_and_reply,
    _try_autonomous_response,
    _process_autonomous_response,
)


class TestEventsExtensive:
    """イベント処理の広範なテスト"""

    @pytest.mark.asyncio
    async def test_is_bot_mentioned_scenarios(self):
        """ボットが呼ばれたかどうかの各種パターンのテスト"""
        bot = MagicMock()
        bot.user.id = 123
        bot.user.mentions = [] # dummy

        # 1. メンション
        msg1 = MagicMock()
        msg1.content = "<@123> こんにちは"
        msg1.mentions = [bot.user]
        mentioned, q, is_reply = await is_bot_mentioned(bot, msg1)
        assert mentioned is True
        assert q == "こんにちは"
        assert is_reply is True

        # 2. 名前で呼ばれる
        with patch("config.BOT_NAME", "スフェーン"):
            msg2 = MagicMock()
            msg2.content = "スフェーン、今日の天気は？"
            msg2.mentions = []
            mentioned, q, is_reply = await is_bot_mentioned(bot, msg2)
            assert mentioned is True
            assert q == "スフェーン、今日の天気は？"
            assert is_reply is False

        # 3. リプライ
        msg3 = MagicMock()
        msg3.content = "そうだね"
        msg3.mentions = []
        msg3.reference = MagicMock()
        msg3.reference.resolved.author.id = 123
        mentioned, q, is_reply = await is_bot_mentioned(bot, msg3)
        assert mentioned is True
        assert q == "そうだね"
        assert is_reply is True

    @staticmethod
    def _role(role_id: int, bot_id: int | None) -> MagicMock:
        role = MagicMock()
        role.id = role_id
        if bot_id is None:
            role.tags = None
        else:
            role.tags.bot_id = bot_id
        return role

    @pytest.mark.asyncio
    async def test_is_bot_mentioned_by_bot_managed_role(self):
        """ボットの管理ロール宛てのメンションもボットへの呼びかけとして扱うこと"""
        bot = MagicMock()
        bot.user.id = 123
        msg = MagicMock()
        msg.content = "<@&999> おはよう！"
        msg.mentions = []
        msg.role_mentions = [self._role(999, bot_id=123)]

        mentioned, q, is_reply = await is_bot_mentioned(bot, msg)

        assert mentioned is True
        assert q == "おはよう！"
        assert is_reply is True

    @pytest.mark.asyncio
    async def test_is_bot_mentioned_ignores_other_roles(self):
        """他のボットの管理ロールや通常ロールへのメンションは無視すること"""
        bot = MagicMock()
        bot.user.id = 123
        msg = MagicMock()
        msg.content = "<@&555> <@&777> 集合！"
        msg.mentions = []
        msg.role_mentions = [self._role(555, bot_id=456), self._role(777, bot_id=None)]
        msg.reference = None

        with patch("config.BOT_NAME", "スフェーン"):
            mentioned, q, is_reply = await is_bot_mentioned(bot, msg)

        assert (mentioned, q, is_reply) == (False, "", False)

    @pytest.mark.asyncio
    async def test_is_bot_mentioned_strips_nickname_mention(self):
        """ニックネーム形式 <@!id> のメンションも本文から除去すること"""
        bot = MagicMock()
        bot.user.id = 123
        msg = MagicMock()
        msg.content = "<@!123> こんにちは <@123>"
        msg.mentions = [bot.user]
        msg.role_mentions = []

        mentioned, q, _ = await is_bot_mentioned(bot, msg)

        assert mentioned is True
        assert q == "こんにちは"

    @pytest.mark.asyncio
    async def test_is_bot_mentioned_keeps_other_mentions(self):
        """ボット以外へのメンションは本文に残すこと"""
        bot = MagicMock()
        bot.user.id = 123
        msg = MagicMock()
        msg.content = "<@123> <@456> にも教えてあげて"
        msg.mentions = [bot.user]
        msg.role_mentions = []

        _, q, _ = await is_bot_mentioned(bot, msg)

        assert q == "<@456> にも教えてあげて"

    @pytest.mark.asyncio
    async def test_is_bot_mentioned_no_content(self):
        """message.contentがNoneでも例外なく3要素を返すことを確認"""
        bot = MagicMock()
        msg = MagicMock()
        msg.content = None
        msg.mentions = []
        msg.reference = None

        mentioned, q, is_reply = await is_bot_mentioned(bot, msg)
        assert mentioned is False
        assert q == ""
        assert is_reply is False

    @pytest.mark.asyncio
    @patch("ai.conversation.channel_conversations")
    @patch("bot.events.split_message")
    async def test_process_conversation_chunking(self, mock_split, mock_conversations):
        """会話のチャンク分割送信テスト"""
        mock_api = MagicMock()
        mock_api.async_input_message = AsyncMock(return_value="Long message")
        mock_conversations.__getitem__.return_value = mock_api
        mock_split.return_value = ["Chunk 1", "Chunk 2"]

        message = MagicMock()
        message.content = ""
        message.channel.send = AsyncMock()

        await process_conversation(message, "question", is_reply=True)

        # 2つのチャンクが送信される
        assert message.channel.send.call_count == 2
        # 最初はリプライ（referenceあり）
        message.channel.send.assert_any_call("Chunk 1", reference=message.to_reference.return_value)
        message.to_reference.assert_called_with(fail_if_not_exists=False)
        # 次は通常送信
        message.channel.send.assert_any_call("Chunk 2")

    @pytest.mark.asyncio
    @patch("ai.conversation.channel_conversations")
    async def test_process_conversation_error_reply_tolerates_deleted_message(
        self, mock_conversations
    ):
        """応答生成失敗時のエラー返信も、元メッセージ削除で失敗しない reference を使う"""
        mock_api = MagicMock()
        mock_api.async_input_message = AsyncMock(return_value=None)
        mock_conversations.__getitem__.return_value = mock_api

        message = MagicMock()
        message.content = ""
        message.channel.send = AsyncMock()

        await process_conversation(message, "question", is_reply=True)

        message.channel.send.assert_called_once()
        assert (
            message.channel.send.call_args.kwargs["reference"]
            is message.to_reference.return_value
        )
        message.to_reference.assert_called_once_with(fail_if_not_exists=False)

    @pytest.mark.asyncio
    @patch("bot.events._post_response_update")
    @patch("ai.conversation.channel_conversations")
    async def test_process_conversation_whitespace_answer_sends_error(
        self, mock_conversations, mock_post_update
    ):
        """空白のみの応答はエラー返信に落とし、履歴更新はしない"""
        mock_api = MagicMock()
        mock_api.async_input_message = AsyncMock(return_value="  \n ")
        mock_conversations.__getitem__.return_value = mock_api

        message = MagicMock()
        message.content = ""
        message.channel.send = AsyncMock()

        await process_conversation(message, "question", is_reply=False)

        message.channel.send.assert_called_once()
        assert "エラー" in message.channel.send.call_args.args[0]
        mock_post_update.assert_not_called()

    @pytest.mark.asyncio
    @patch("bot.events.config_manager")
    async def test_handle_on_ready_sync(self, mock_config_manager):
        """on_readyでの準備処理テスト"""
        bot = MagicMock()
        bot.user.name = "Sphene"
        bot.user.discriminator = "0001"
        bot.guilds = [MagicMock(id=1, name="G1"), MagicMock(id=2, name="G2")]
        bot.add_cog = AsyncMock()
        bot.tree.sync = AsyncMock()

        command_group = MagicMock()

        await _handle_on_ready(bot, command_group)

        # コマンド登録・同期は setup_hook 側で行うため、on_ready では呼ばれない
        bot.tree.add_command.assert_not_called()
        bot.tree.sync.assert_not_called()
        # 各ギルドの設定が初期化される
        assert mock_config_manager.get_config.call_count == 2

    @pytest.mark.asyncio
    async def test_handle_setup_hook_registers_and_syncs_once(self):
        """setup_hookでコマンド登録と同期が1回だけ行われること"""
        bot = MagicMock()
        bot.tree.sync = AsyncMock()
        command_group = MagicMock()

        await _handle_setup_hook(bot, command_group)

        bot.tree.add_command.assert_called_once_with(command_group)
        bot.tree.sync.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("bot.events.config_manager")
    async def test_handle_on_guild_join_remove(self, mock_config_manager):
        """ギルド参加・脱退時の設定管理テスト"""
        guild = MagicMock(id=999, name="New Guild")
        
        # 参加
        await _handle_on_guild_join(guild)
        mock_config_manager.create_guild_config.assert_called_once_with(999)

        # 脱退
        await _handle_on_guild_remove(guild)
        mock_config_manager.delete_guild_config.assert_called_once_with(999)

    @pytest.mark.asyncio
    @patch("memory.short_term.get_channel_buffer")
    @patch("memory.judge.get_judge")
    @patch("bot.events._process_autonomous_response")
    async def test_try_autonomous_response_high_score(self, mock_process, mock_get_judge, mock_get_buffer):
        """高スコア時の自律応答トリガーテスト"""
        bot = MagicMock()
        message = MagicMock()
        message.id = 1
        message.channel.id = 100
        message.author.id = 200
        message.content = "Trigger"
        
        mock_judge = MagicMock()
        mock_judge.evaluate.return_value = MagicMock(score=90, reason="High")
        mock_get_judge.return_value = mock_judge
        
        with patch("config.JUDGE_LLM_THRESHOLD_HIGH", 80):
            await _try_autonomous_response(bot, message, [])
            mock_process.assert_called_once()

    @pytest.mark.asyncio
    @patch("memory.short_term.get_channel_buffer")
    @patch("ai.conversation.channel_conversations")
    @patch("bot.events.split_message")
    @patch("memory.judge.get_judge")
    async def test_process_autonomous_response(self, mock_get_judge, mock_split, mock_conversations, mock_get_buffer):
        """自律応答の生成と送信プロセステスト"""
        bot = MagicMock()
        bot.user.id = 123
        message = MagicMock()
        message.channel.id = 100
        message.content = "Hello"

        mock_buffer = MagicMock()
        mock_buffer.get_context_string.return_value = "Past context"
        mock_get_buffer.return_value = mock_buffer

        mock_api = MagicMock()
        mock_api.is_expired.return_value = False
        mock_api.async_input_message = AsyncMock(return_value="Autonomous Answer")
        mock_conversations.__getitem__.return_value = mock_api

        mock_split.return_value = ["Autonomous Answer"]
        message.channel.send = AsyncMock()

        await _process_autonomous_response(bot, message, [])

        message.channel.send.assert_called_once_with("Autonomous Answer")
        mock_get_judge().record_response.assert_called_once_with(100)
        mock_buffer.add_message.assert_called_once()

    @pytest.mark.asyncio
    @patch("memory.short_term.get_channel_buffer")
    @patch("ai.conversation.channel_conversations")
    @patch("memory.judge.get_judge")
    async def test_process_autonomous_response_whitespace_answer(
        self, mock_get_judge, mock_conversations, mock_get_buffer
    ):
        """空白のみの自律応答は送信せず、クールダウン・バッファも更新しない"""
        bot = MagicMock()
        bot.user.id = 123
        message = MagicMock()
        message.channel.id = 100
        message.content = "Hello"

        mock_buffer = MagicMock()
        mock_buffer.get_context_string.return_value = "Past context"
        mock_get_buffer.return_value = mock_buffer

        mock_api = MagicMock()
        mock_api.is_expired.return_value = False
        mock_api.async_input_message = AsyncMock(return_value="  \n ")
        mock_conversations.__getitem__.return_value = mock_api
        message.channel.send = AsyncMock()

        await _process_autonomous_response(bot, message, [])

        message.channel.send.assert_not_called()
        mock_get_judge().record_response.assert_not_called()
        mock_buffer.add_message.assert_not_called()

    def test_setup_events(self):
        """setup_events がイベントを登録することを確認"""
        bot = MagicMock()
        command_group = MagicMock()
        from bot.events import setup_events

        setup_events(bot, command_group)

        # bot.event (デコレータ) が呼ばれた回数を確認
        assert bot.event.call_count >= 5
        # bot.tree.error (デコレータ) が呼ばれたことを確認
        assert bot.tree.error.called

    @pytest.mark.asyncio
    async def test_setup_events_assigns_setup_hook(self):
        """setup_events が setup_hook を差し替え、コマンド同期を委譲すること"""
        bot = MagicMock()
        bot.tree.sync = AsyncMock()
        command_group = MagicMock()
        from bot.events import setup_events

        setup_events(bot, command_group)
        await bot.setup_hook()

        bot.tree.add_command.assert_called_once_with(command_group)
        bot.tree.sync.assert_awaited_once()


class TestCollectAiContext:
    """_collect_ai_context のテスト"""

    @pytest.mark.asyncio
    @patch("bot.events.config")
    @patch("memory.short_term.get_channel_buffer")
    async def test_memory_enabled_channel_context_disabled(
        self, mock_buffer_fn: MagicMock, mock_config: MagicMock
    ) -> None:
        """LIVING_MEMORY_ENABLED=False のとき channel_context のみ返す"""
        mock_config.LIVING_MEMORY_ENABLED = False

        mock_buffer = MagicMock()
        mock_buffer.get_context_string.return_value = "past messages"
        mock_buffer_fn.return_value = mock_buffer

        message = MagicMock()
        message.channel.id = 100

        ctx, summary, keywords, profile, facts = await _collect_ai_context(message)

        assert ctx == "past messages"
        assert summary == ""
        assert keywords == []
        assert profile == ""
        assert facts == ""

    @pytest.mark.asyncio
    @patch("bot.events.config")
    @patch("memory.short_term.get_channel_buffer")
    @patch("memory.channel_context.get_channel_context_store")
    @patch("memory.fact_store.get_fact_store")
    @patch("memory.fact_store.extract_keywords", return_value=[])
    async def test_channel_context_enabled(
        self,
        mock_extract_keywords: MagicMock,
        mock_fact_store_fn: MagicMock,
        mock_ctx_store_fn: MagicMock,
        mock_buffer_fn: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """LIVING_MEMORY_ENABLED=True のとき summary と topic_keywords が返る"""
        mock_config.LIVING_MEMORY_ENABLED = True
        mock_config.VECTOR_SEARCH_ENABLED = False

        mock_buffer = MagicMock()
        mock_buffer.get_context_string.return_value = "ctx"
        mock_buffer_fn.return_value = mock_buffer

        mock_ctx = MagicMock()
        mock_ctx.format_for_injection.return_value = "summary text"
        mock_ctx.topic_keywords = ["topic1", "topic2"]
        mock_ctx_store = MagicMock()
        mock_ctx_store.get_context.return_value = mock_ctx
        mock_ctx_store_fn.return_value = mock_ctx_store

        mock_fact_store_fn.return_value.search.return_value = []

        message = MagicMock()
        message.channel.id = 100
        message.content = "テストメッセージ"

        ctx, summary, keywords, profile, facts = await _collect_ai_context(message)

        assert ctx == "ctx"
        assert summary == "summary text"
        assert keywords == ["topic1", "topic2"]

    @pytest.mark.asyncio
    @patch("bot.events.config")
    @patch("memory.short_term.get_channel_buffer")
    @patch("memory.user_profile.get_user_profile_store")
    @patch("memory.fact_store.get_fact_store")
    @patch("memory.fact_store.extract_keywords", return_value=[])
    async def test_user_profile_enabled(
        self,
        mock_extract_keywords: MagicMock,
        mock_fact_store_fn: MagicMock,
        mock_profile_store_fn: MagicMock,
        mock_buffer_fn: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """LIVING_MEMORY_ENABLED=True のとき user_profile_str が返る"""
        mock_config.LIVING_MEMORY_ENABLED = True
        mock_config.VECTOR_SEARCH_ENABLED = False

        mock_buffer = MagicMock()
        mock_buffer.get_context_string.return_value = ""
        mock_buffer_fn.return_value = mock_buffer

        mock_profile = MagicMock()
        mock_profile.format_for_familiarity.return_value = "user profile text"
        mock_profile.format_for_context.return_value = ""
        mock_profile.format_for_persona.return_value = ""
        mock_profile_store = MagicMock()
        mock_profile_store.get_profile.return_value = mock_profile
        mock_profile_store_fn.return_value = mock_profile_store

        mock_fact_store_fn.return_value.search.return_value = []

        message = MagicMock()
        message.channel.id = 100
        message.author.id = 200
        message.author.display_name = "Taro"
        message.content = "テストメッセージ"

        ctx, summary, keywords, profile, facts = await _collect_ai_context(message)

        assert profile == "user profile text"


class TestSendChunks:
    """_send_chunks のテスト"""

    @pytest.mark.asyncio
    async def test_empty_chunks(self) -> None:
        """チャンクが空リストのとき何も送信されない"""
        message = MagicMock()
        message.channel.send = AsyncMock()

        await _send_chunks(message, [])

        message.channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_chunk_not_reply(self) -> None:
        """is_reply=False の1チャンクは通常送信"""
        message = MagicMock()
        message.channel.send = AsyncMock()
        message.channel.id = 100

        await _send_chunks(message, ["hello"], is_reply=False)

        message.channel.send.assert_called_once_with("hello")

    @pytest.mark.asyncio
    async def test_single_chunk_reply(self) -> None:
        """is_reply=True の1チャンクはリプライ送信"""
        message = MagicMock()
        message.channel.send = AsyncMock()
        message.channel.id = 100

        await _send_chunks(message, ["hello"], is_reply=True)

        message.channel.send.assert_called_once_with(
            "hello", reference=message.to_reference.return_value
        )
        message.to_reference.assert_called_once_with(fail_if_not_exists=False)

    @pytest.mark.asyncio
    async def test_multi_chunk_reply_first_is_reference(self) -> None:
        """is_reply=True の複数チャンクで、1つ目だけ reference が付く"""
        message = MagicMock()
        message.channel.send = AsyncMock()
        message.channel.id = 100

        await _send_chunks(message, ["chunk1", "chunk2", "chunk3"], is_reply=True)

        assert message.channel.send.call_count == 3
        calls = message.channel.send.call_args_list
        # 1チャンク目: 元メッセージ削除時も失敗しない reference
        assert calls[0].kwargs.get("reference") is message.to_reference.return_value
        message.to_reference.assert_called_once_with(fail_if_not_exists=False)
        # 2チャンク目以降: reference なし
        assert "reference" not in calls[1].kwargs
        assert "reference" not in calls[2].kwargs

    @pytest.mark.asyncio
    async def test_multi_chunk_no_reply(self) -> None:
        """is_reply=False の複数チャンクは全て通常送信"""
        message = MagicMock()
        message.channel.send = AsyncMock()
        message.channel.id = 100

        await _send_chunks(message, ["a", "b"], is_reply=False)

        calls = message.channel.send.call_args_list
        assert all("reference" not in c.kwargs for c in calls)


class TestPostResponseUpdate:
    """_post_response_update のテスト"""

    @patch("bot.events.config")
    def test_skips_profile_update_when_no_keywords(self, mock_config: MagicMock) -> None:
        """topic_keywords が空のとき update_last_topic は呼ばれない"""
        mock_config.LIVING_MEMORY_ENABLED = True

        message = MagicMock()
        message.channel.id = 100

        with patch("memory.user_profile.get_user_profile_store") as mock_store_fn:
            _post_response_update(message, "answer", [], MagicMock())
            mock_store_fn.assert_not_called()

    @patch("bot.events.config")
    def test_skips_buffer_when_bot_user_is_none(self, mock_config: MagicMock) -> None:
        """bot_user が None のとき add_message は呼ばれない"""
        mock_config.LIVING_MEMORY_ENABLED = False

        message = MagicMock()
        message.channel.id = 100

        with patch("memory.short_term.get_channel_buffer") as mock_buffer_fn:
            _post_response_update(message, "answer", [], None)
            mock_buffer_fn.assert_not_called()

    @patch("bot.events.config")
    def test_updates_profile_and_buffer(self, mock_config: MagicMock) -> None:
        """keywords あり・bot_user あり の場合、両方更新される"""
        mock_config.LIVING_MEMORY_ENABLED = True

        message = MagicMock()
        message.channel.id = 100
        message.author.id = 200
        message.created_at = datetime.now(timezone.utc)

        bot_user = MagicMock()
        bot_user.id = 999
        bot_user.display_name = "Bot"

        with (
            patch("memory.user_profile.get_user_profile_store") as mock_profile_fn,
            patch("memory.short_term.get_channel_buffer") as mock_buffer_fn,
        ):
            mock_profile_store = MagicMock()
            mock_profile_fn.return_value = mock_profile_store
            mock_buffer = MagicMock()
            mock_buffer_fn.return_value = mock_buffer

            _post_response_update(message, "answer", ["kw1"], bot_user)

            mock_profile_store.update_last_topic.assert_called_once_with(
                message.guild.id, 200, ["kw1"]
            )
            mock_buffer.add_message.assert_called_once()


class TestPrefetchMemory:
    """_prefetch_memory のテスト"""

    def test_warms_all_memory_stores(self):
        """チャンネルコンテキスト・プロファイル・ファクトを読み込み済みにすること"""
        from bot.events import _prefetch_memory

        message = MagicMock()
        message.guild.id = 10
        message.channel.id = 20
        message.author.id = 30
        message.author.display_name = "User"
        ctx_store, profile_store, fact_store = MagicMock(), MagicMock(), MagicMock()

        with patch("memory.channel_context.get_channel_context_store", return_value=ctx_store), \
             patch("memory.user_profile.get_user_profile_store", return_value=profile_store), \
             patch("memory.fact_store.get_fact_store", return_value=fact_store):
            _prefetch_memory(message)

        ctx_store.get_context.assert_called_once_with(20)
        profile_store.get_profile.assert_called_once_with(10, 30, "User")
        fact_store.ensure_loaded.assert_called_once_with(20)
