"""
Discordイベント処理のテスト
特にチャンネル評価機能に関するテスト
"""

# type: ignore
# mypy: ignore-errors

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.events import _handle_message


class TestEventHandling:
    """イベント処理のテスト"""

    @pytest.mark.asyncio
    @patch("bot.events.is_bot_mentioned")
    @patch("bot.events.config_manager")
    async def test_handle_message_deny_mode_blocked(
        self, mock_config_manager, mock_is_bot_mentioned
    ):
        """全体モード（deny）でブロックされるチャンネルのテスト"""
        # channel_configの代わりにconfig_managerを使用
        mock_channel_config = MagicMock()
        mock_channel_config.can_bot_speak.return_value = False
        mock_channel_config.get_mode_display_name.return_value = "全体モード"
        mock_config_manager.get_config.return_value = mock_channel_config

        # メッセージのモック
        message = MagicMock()
        message.author.bot = False
        message.channel.id = 12345
        message.content = "テストメッセージ"
        message.author.id = 67890
        # guildのモック
        message.guild = MagicMock()
        message.guild.id = 54321

        # ボットのモック
        bot = MagicMock()
        bot.user = MagicMock()

        # コマンド実行
        await _handle_message(bot, message)

        # アサーション
        mock_config_manager.get_config.assert_called_once_with(54321)
        mock_channel_config.can_bot_speak.assert_called_once_with(12345)
        # メッセージチェック関数は呼ばれない（ブロックされるため）
        mock_is_bot_mentioned.assert_not_called()

    @pytest.mark.asyncio
    @patch("bot.events.is_bot_mentioned")
    @patch("bot.events.process_conversation")
    @patch("bot.events.config_manager")
    async def test_handle_message_allow_mode_permitted(
        self, mock_config_manager, mock_process_conversation, mock_is_bot_mentioned
    ):
        """限定モード（allow）で許可されるチャンネルのテスト"""
        # channel_configの代わりにconfig_managerを使用
        mock_channel_config = MagicMock()
        mock_channel_config.can_bot_speak.return_value = True
        mock_channel_config.get_mode_display_name.return_value = "限定モード"
        mock_config_manager.get_config.return_value = mock_channel_config
        mock_is_bot_mentioned.return_value = (True, "テスト質問", True)

        # メッセージのモック
        message = MagicMock()
        message.author.bot = False
        message.channel.id = 12345
        message.content = "テストメッセージ"
        message.author.id = 67890
        message.attachments = []  # 添付ファイルなし
        message.created_at = datetime.now(timezone.utc)
        # guildのモック
        message.guild = MagicMock()
        message.guild.id = 54321

        # ボットのモック
        bot = MagicMock()
        bot.user = MagicMock()

        # コマンド実行
        await _handle_message(bot, message)

        # アサーション
        mock_config_manager.get_config.assert_called_once_with(54321)
        mock_channel_config.can_bot_speak.assert_called_once_with(12345)
        # メッセージチェック関数が呼ばれる（許可されるため）
        mock_is_bot_mentioned.assert_called_once()
        # メンションされていれば会話処理が呼ばれる
        mock_process_conversation.assert_called_once_with(
            message, "テスト質問", True, []
        )

    @pytest.mark.asyncio
    @patch("bot.events.config")
    @patch("bot.events.is_bot_mentioned")
    @patch("bot.events.process_conversation")
    @patch("bot.events.config_manager")
    async def test_handle_message_not_mentioned(
        self,
        mock_config_manager,
        mock_process_conversation,
        mock_is_bot_mentioned,
        mock_config,
    ):
        """ボットがメンションされていない場合のテスト"""
        mock_config.AUTONOMOUS_RESPONSE_ENABLED = False
        mock_config.CHANNEL_CONTEXT_ENABLED = False
        mock_config.USER_PROFILE_ENABLED = False
        mock_config.REFLECTION_ENABLED = False
        mock_config.PROACTIVE_CONVERSATION_ENABLED = False
        # channel_configの代わりにconfig_managerを使用
        mock_channel_config = MagicMock()
        mock_channel_config.can_bot_speak.return_value = True
        mock_config_manager.get_config.return_value = mock_channel_config
        mock_is_bot_mentioned.return_value = (False, "", False)

        # メッセージのモック
        message = MagicMock()
        message.author.bot = False
        message.channel.id = 12345
        message.content = "通常メッセージ"
        message.author.id = 67890
        message.created_at = datetime.now(timezone.utc)
        # guildのモック
        message.guild = MagicMock()
        message.guild.id = 54321

        # ボットのモック
        bot = MagicMock()
        bot.user = MagicMock()

        # コマンド実行
        await _handle_message(bot, message)

        # アサーション
        mock_config_manager.get_config.assert_called_once_with(54321)
        mock_channel_config.can_bot_speak.assert_called_once_with(12345)
        # メッセージチェック関数は呼ばれる（チャンネルは許可されるため）
        mock_is_bot_mentioned.assert_called_once()
        # メンションされていないので会話処理は呼ばれない
        mock_process_conversation.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_message_bot_message(self):
        """ボット自身のメッセージを無視するテスト"""
        # メッセージのモック
        message = MagicMock()
        message.author.bot = True  # ボットからのメッセージ
        message.channel.id = 12345
        message.content = "ボットからのメッセージ"

        # ボットのモック
        bot = MagicMock()
        bot.user = MagicMock()

        # コマンド実行
        await _handle_message(bot, message)

        # config_managerはmockしないで、テストの動作だけ確認
        # ボットのメッセージは早期に無視されるので、モックの検証は不要

    @pytest.mark.asyncio
    async def test_handle_message_empty_content(self):
        """空のメッセージコンテンツを無視するテスト"""
        # メッセージのモック
        message = MagicMock()
        message.author.bot = False
        message.content = None  # 空のコンテンツ
        message.attachments = []  # 添付ファイルもなし
        message.channel.id = 12345

        # ボットのモック
        bot = MagicMock()
        bot.user = MagicMock()

        # コマンド実行
        await _handle_message(bot, message)

        # config_managerはmockしないで、テストの動作だけ確認
        # 空のコンテンツかつ添付ファイルがない場合は早期に無視されるので、モックの検証は不要

    @pytest.mark.asyncio
    @patch("bot.events.is_bot_mentioned")
    @patch("bot.events.process_conversation")
    @patch("bot.events.config_manager")
    async def test_handle_message_with_image(
        self, mock_config_manager, mock_process_conversation, mock_is_bot_mentioned
    ):
        """画像添付のあるメッセージのテスト"""
        # channel_configの設定
        mock_channel_config = MagicMock()
        mock_channel_config.can_bot_speak.return_value = True
        mock_channel_config.get_mode_display_name.return_value = "限定モード"
        mock_config_manager.get_config.return_value = mock_channel_config
        mock_is_bot_mentioned.return_value = (True, "テスト質問", True)

        # 画像添付ファイルのモック
        mock_attachment1 = MagicMock()
        mock_attachment1.content_type = "image/jpeg"
        mock_attachment1.url = "https://example.com/test1.jpg"

        mock_attachment2 = MagicMock()
        mock_attachment2.content_type = "application/pdf"  # 画像ではないタイプ
        mock_attachment2.url = "https://example.com/test.pdf"

        # メッセージのモック
        message = MagicMock()
        message.author.bot = False
        message.channel.id = 12345
        message.content = "画像テスト"
        message.author.id = 67890
        message.attachments = [mock_attachment1, mock_attachment2]
        message.created_at = datetime.now(timezone.utc)
        # guildのモック
        message.guild = MagicMock()
        message.guild.id = 54321

        # ボットのモック
        bot = MagicMock()
        bot.user = MagicMock()

        # コマンド実行
        await _handle_message(bot, message)

        # アサーション
        mock_config_manager.get_config.assert_called_once()
        mock_channel_config.can_bot_speak.assert_called_once()
        mock_is_bot_mentioned.assert_called_once()
        # 画像URLのみがprocess_conversationに渡されることを確認
        mock_process_conversation.assert_called_once_with(
            message, "テスト質問", True, ["https://example.com/test1.jpg"]
        )

    @pytest.mark.asyncio
    @patch("bot.events.is_bot_mentioned")
    @patch("bot.events.process_conversation")
    @patch("bot.events.config_manager")
    async def test_handle_message_exception_handling(
        self, mock_config_manager, mock_process_conversation, mock_is_bot_mentioned
    ):
        """例外処理のテスト"""
        # モックのセットアップ - 例外を発生させる
        mock_config_manager.get_config.side_effect = Exception("テストエラー")

        # メッセージとチャンネルのモック
        message = MagicMock()
        message.author.bot = False
        message.channel.id = 12345
        message.content = "テストメッセージ"
        message.channel.send = AsyncMock()
        # guildのモック
        message.guild = MagicMock()
        message.guild.id = 54321

        # ボットのモック
        bot = MagicMock()
        bot.user = MagicMock()

        # コマンド実行
        await _handle_message(bot, message)

        # アサーション - エラーメッセージが送信されること
        message.channel.send.assert_called_once()
        args, kwargs = message.channel.send.call_args
        # セキュリティ改善により、エラー詳細は非公開（一般的なメッセージのみ）
        assert "エラー" in args[0]
        assert args[0] == "ごめん！メッセージ処理中にエラーが発生しちゃった...😢"


class TestDispatchResponse:
    """_dispatch_response のテスト"""

    @pytest.mark.asyncio
    @patch("bot.events._process_autonomous_response")
    async def test_dispatch_full_response(self, mock_process):
        """full_responseの場合_process_autonomous_responseが呼ばれる"""
        bot = MagicMock()
        message = MagicMock()

        from bot.events import _dispatch_response
        await _dispatch_response(bot, message, [], "full_response")

        mock_process.assert_called_once_with(bot, message, [])

    @pytest.mark.asyncio
    @patch("bot.events._send_reaction")
    async def test_dispatch_react_only(self, mock_reaction):
        """react_onlyの場合_send_reactionが呼ばれる"""
        bot = MagicMock()
        message = MagicMock()

        from bot.events import _dispatch_response
        await _dispatch_response(bot, message, [], "react_only")

        mock_reaction.assert_called_once_with(message)

    @pytest.mark.asyncio
    @patch("bot.events._process_short_ack")
    async def test_dispatch_short_ack(self, mock_ack):
        """short_ackの場合_process_short_ackが呼ばれる"""
        bot = MagicMock()
        message = MagicMock()

        from bot.events import _dispatch_response
        await _dispatch_response(bot, message, [], "short_ack")

        mock_ack.assert_called_once_with(bot, message, already_reacted=False)

    @pytest.mark.asyncio
    @patch("bot.events._process_short_ack")
    async def test_dispatch_short_ack_with_already_reacted(self, mock_ack):
        """already_reacted=True が _process_short_ack に伝播する"""
        bot = MagicMock()
        message = MagicMock()

        from bot.events import _dispatch_response
        await _dispatch_response(bot, message, [], "short_ack", already_reacted=True)

        mock_ack.assert_called_once_with(bot, message, already_reacted=True)


class TestSendReaction:
    """_send_reaction のテスト"""

    @pytest.mark.asyncio
    @patch("memory.judge.get_judge")
    async def test_send_reaction_adds_emoji(self, mock_get_judge):
        """リアクションが追加される"""
        mock_judge = MagicMock()
        mock_get_judge.return_value = mock_judge

        message = MagicMock()
        message.add_reaction = AsyncMock()
        message.channel.id = 100

        from bot.events import _send_reaction
        await _send_reaction(message)

        message.add_reaction.assert_called_once()
        mock_judge.record_response.assert_called_once_with(100)

    @pytest.mark.asyncio
    @patch("memory.judge.get_judge")
    async def test_send_reaction_uses_provided_emoji(self, mock_get_judge):
        """emojisが渡された場合は最初の絵文字が使われる"""
        mock_judge = MagicMock()
        mock_get_judge.return_value = mock_judge

        message = MagicMock()
        message.add_reaction = AsyncMock()
        message.channel.id = 100

        from bot.events import _send_reaction
        await _send_reaction(message, emojis=["🤔", "💡"])

        message.add_reaction.assert_called_once_with("🤔")
        mock_judge.record_response.assert_called_once_with(100)

    @pytest.mark.asyncio
    @patch("memory.judge.get_judge")
    async def test_send_reaction_record_false_skips_cooldown(self, mock_get_judge):
        """record=False の場合 record_response が呼ばれない"""
        mock_judge = MagicMock()
        mock_get_judge.return_value = mock_judge

        message = MagicMock()
        message.add_reaction = AsyncMock()
        message.channel.id = 100

        from bot.events import _send_reaction
        await _send_reaction(message, record=False)

        message.add_reaction.assert_called_once()
        mock_judge.record_response.assert_not_called()


class TestProcessShortAck:
    """_process_short_ack のテスト"""

    @pytest.mark.asyncio
    @patch("asyncio.to_thread")
    @patch("memory.judge.get_judge")
    @patch("memory.short_term.get_channel_buffer")
    async def test_short_ack_success(self, mock_buffer_fn, mock_get_judge, mock_to_thread):
        """相槌が正常に送信される"""
        mock_buffer = MagicMock()
        mock_buffer.get_context_string.return_value = "User1: hello"
        mock_buffer_fn.return_value = mock_buffer

        mock_judge = MagicMock()
        mock_get_judge.return_value = mock_judge

        mock_to_thread.return_value = "なるほどー"

        bot = MagicMock()
        bot.user = MagicMock()
        bot.user.id = 999
        bot.user.display_name = "Bot"

        message = MagicMock()
        message.channel.id = 100
        message.channel.send = AsyncMock()
        message.content = "テスト"
        message.created_at = MagicMock()

        from bot.events import _process_short_ack
        await _process_short_ack(bot, message)

        message.channel.send.assert_called_once_with("なるほどー")
        mock_judge.record_response.assert_called_once_with(100)

    @pytest.mark.asyncio
    @patch("memory.short_term.get_channel_buffer")
    async def test_short_ack_empty_context(self, mock_buffer_fn):
        """コンテキストが空の場合、send が呼ばれない"""
        mock_buffer = MagicMock()
        mock_buffer.get_context_string.return_value = ""
        mock_buffer_fn.return_value = mock_buffer

        bot = MagicMock()
        message = MagicMock()
        message.channel.id = 100
        message.channel.send = AsyncMock()

        from bot.events import _process_short_ack
        await _process_short_ack(bot, message)

        message.channel.send.assert_not_called()

    @pytest.mark.asyncio
    @patch("asyncio.to_thread")
    @patch("memory.short_term.get_channel_buffer")
    async def test_short_ack_none_answer(self, mock_buffer_fn, mock_to_thread):
        """generate_short_ack が None を返した場合、_send_reaction にフォールバック"""
        mock_buffer = MagicMock()
        mock_buffer.get_context_string.return_value = "User1: hello"
        mock_buffer_fn.return_value = mock_buffer

        mock_to_thread.return_value = None

        bot = MagicMock()
        message = MagicMock()
        message.channel.id = 100
        message.channel.send = AsyncMock()
        message.add_reaction = AsyncMock()
        message.content = "テスト"

        with patch("bot.events._send_reaction") as mock_send_reaction:
            mock_send_reaction.return_value = None

            from bot.events import _process_short_ack
            await _process_short_ack(bot, message)

        message.channel.send.assert_not_called()
        mock_send_reaction.assert_called_once_with(message)

    @pytest.mark.asyncio
    @patch("asyncio.to_thread")
    @patch("memory.judge.get_judge")
    @patch("memory.short_term.get_channel_buffer")
    async def test_short_ack_none_answer_already_reacted_skips_reaction(
        self, mock_buffer_fn, mock_get_judge, mock_to_thread
    ):
        """already_reacted=True かつ相槌失敗時はリアクションを追加せずクールダウンのみ記録"""
        mock_buffer = MagicMock()
        mock_buffer.get_context_string.return_value = "User1: hello"
        mock_buffer_fn.return_value = mock_buffer
        mock_judge = MagicMock()
        mock_get_judge.return_value = mock_judge
        mock_to_thread.return_value = None

        bot = MagicMock()
        message = MagicMock()
        message.channel.id = 100
        message.channel.send = AsyncMock()
        message.add_reaction = AsyncMock()
        message.content = "テスト"

        with patch("bot.events._send_reaction") as mock_send_reaction:
            from bot.events import _process_short_ack
            await _process_short_ack(bot, message, already_reacted=True)

        message.channel.send.assert_not_called()
        mock_send_reaction.assert_not_called()
        # クールダウンは記録される
        mock_judge.record_response.assert_called_once_with(100)


class TestCollectAiContextFacts:
    """_collect_ai_context のファクト検索テスト"""

    @pytest.mark.asyncio
    @patch("config.REFLECTION_ENABLED", True)
    @patch("config.CHANNEL_CONTEXT_ENABLED", False)
    @patch("config.USER_PROFILE_ENABLED", False)
    async def test_collect_ai_context_injects_facts(self):
        """REFLECTION_ENABLED=True のとき relevant_facts_str にファクトが含まれること"""
        from memory.fact_store import Fact
        from datetime import timezone
        import uuid

        mock_fact = Fact(
            fact_id=str(uuid.uuid4()),
            channel_id=12345,
            content="Aさんは先週Rustを始めた",
            keywords=["Rust", "Aさん"],
            source_user_ids=[67890],
            created_at=datetime.now(timezone.utc),
            shareable=True,
        )

        message = MagicMock()
        message.channel.id = 12345
        message.author.id = 67890
        message.content = "Rustについて"

        mock_buffer = MagicMock()
        mock_buffer.get_context_string.return_value = ""
        mock_store = MagicMock()
        mock_store.search.return_value = [mock_fact]

        with patch("memory.short_term.get_channel_buffer", return_value=mock_buffer):
            with patch("memory.fact_store.get_fact_store", return_value=mock_store):
                with patch("memory.fact_store.extract_keywords", return_value=["Rust"]):
                    from bot.events import _collect_ai_context
                    _, _, _, _, relevant_facts_str = await _collect_ai_context(message)

        assert "関連する過去の記憶" in relevant_facts_str
        assert "Aさんは先週Rustを始めた" in relevant_facts_str

    @pytest.mark.asyncio
    @patch("config.REFLECTION_ENABLED", False)
    @patch("config.CHANNEL_CONTEXT_ENABLED", False)
    @patch("config.USER_PROFILE_ENABLED", False)
    async def test_collect_ai_context_no_facts_when_disabled(self):
        """REFLECTION_ENABLED=False のとき relevant_facts_str が空であること"""
        message = MagicMock()
        message.channel.id = 12345
        message.author.id = 67890
        message.content = "テスト"

        mock_buffer = MagicMock()
        mock_buffer.get_context_string.return_value = ""

        with patch("memory.short_term.get_channel_buffer", return_value=mock_buffer):
            from bot.events import _collect_ai_context
            _, _, _, _, relevant_facts_str = await _collect_ai_context(message)

        assert relevant_facts_str == ""


class TestHandleMessageReflectionTrigger:
    """_handle_message の反省会トリガーテスト"""

    @pytest.mark.asyncio
    @patch("bot.events.config")
    @patch("bot.events.is_bot_mentioned")
    @patch("bot.events.config_manager")
    async def test_reflection_triggered_on_buffer_full(
        self, mock_config_manager, mock_is_bot_mentioned, mock_config
    ):
        """バッファが上限に達したとき反省会エンジンが呼ばれること"""
        mock_config.REFLECTION_ENABLED = True
        mock_config.REFLECTION_MAX_BUFFER_MESSAGES = 5
        mock_config.CHANNEL_CONTEXT_ENABLED = False
        mock_config.USER_PROFILE_ENABLED = False
        mock_config.AUTONOMOUS_RESPONSE_ENABLED = False
        mock_config.PROACTIVE_CONVERSATION_ENABLED = False

        mock_channel_config = MagicMock()
        mock_channel_config.can_bot_speak.return_value = True
        mock_config_manager.get_config.return_value = mock_channel_config
        mock_is_bot_mentioned.return_value = (False, "", False)

        mock_buffer = MagicMock()
        mock_buffer.get_last_message_time.return_value = None
        mock_buffer.count_messages_since_reflection.return_value = 5  # 上限到達
        mock_buffer.get_recent_messages.return_value = []

        mock_engine = MagicMock()

        message = MagicMock()
        message.author.bot = False
        message.channel.id = 12345
        message.content = "テスト"
        message.author.id = 67890
        message.attachments = []
        message.created_at = datetime.now(timezone.utc)
        message.guild = MagicMock()
        message.guild.id = 54321

        bot = MagicMock()
        bot.user = MagicMock()

        with patch("memory.short_term.get_channel_buffer", return_value=mock_buffer):
            with patch("memory.reflection.get_reflection_engine", return_value=mock_engine):
                await _handle_message(bot, message)

        mock_engine.maybe_reflect.assert_called_once()

    @pytest.mark.asyncio
    @patch("bot.events.config")
    @patch("bot.events.is_bot_mentioned")
    @patch("bot.events.config_manager")
    async def test_reflection_not_triggered_when_disabled(
        self, mock_config_manager, mock_is_bot_mentioned, mock_config
    ):
        """REFLECTION_ENABLED=False のとき反省会エンジンが呼ばれないこと"""
        mock_config.REFLECTION_ENABLED = False
        mock_config.CHANNEL_CONTEXT_ENABLED = False
        mock_config.USER_PROFILE_ENABLED = False
        mock_config.AUTONOMOUS_RESPONSE_ENABLED = False
        mock_config.PROACTIVE_CONVERSATION_ENABLED = False

        mock_channel_config = MagicMock()
        mock_channel_config.can_bot_speak.return_value = True
        mock_config_manager.get_config.return_value = mock_channel_config
        mock_is_bot_mentioned.return_value = (False, "", False)

        mock_buffer = MagicMock()
        mock_buffer.get_last_message_time.return_value = None

        mock_engine = MagicMock()

        message = MagicMock()
        message.author.bot = False
        message.channel.id = 12345
        message.content = "テスト"
        message.author.id = 67890
        message.attachments = []
        message.created_at = datetime.now(timezone.utc)
        message.guild = MagicMock()
        message.guild.id = 54321

        bot = MagicMock()
        bot.user = MagicMock()

        with patch("memory.short_term.get_channel_buffer", return_value=mock_buffer):
            with patch("memory.reflection.get_reflection_engine", return_value=mock_engine):
                await _handle_message(bot, message)

        mock_engine.maybe_reflect.assert_not_called()


class TestTryProactiveConversation:
    """_try_proactive_conversation のテスト"""

    @pytest.mark.asyncio
    async def test_skips_when_silence_too_short(self):
        """沈黙時間が設定未満の場合スキップされること"""
        from datetime import timedelta, timezone
        from bot.events import _try_proactive_conversation

        now = datetime.now(timezone.utc)
        pre_add_last_time = now - timedelta(minutes=2)  # 2分前

        message = MagicMock()
        message.created_at = now
        message.channel.id = 12345

        bot = MagicMock()

        with patch("config.REFLECTION_LULL_MINUTES", 10):
            with patch("memory.fact_store.get_fact_store") as mock_store_fn:
                await _try_proactive_conversation(bot, message, pre_add_last_time)
                mock_store_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_in_cooldown(self):
        """クールダウン中の場合スキップされること"""
        from datetime import timedelta, timezone
        from bot.events import _try_proactive_conversation

        now = datetime.now(timezone.utc)
        pre_add_last_time = now - timedelta(minutes=30)  # 十分な沈黙

        message = MagicMock()
        message.created_at = now
        message.channel.id = 12345

        bot = MagicMock()

        mock_judge = MagicMock()
        mock_judge.is_in_cooldown.return_value = True

        with patch("config.REFLECTION_LULL_MINUTES", 10):
            with patch("memory.judge.get_judge", return_value=mock_judge):
                with patch("memory.fact_store.get_fact_store") as mock_store_fn:
                    await _try_proactive_conversation(bot, message, pre_add_last_time)
                    mock_store_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_no_shareable_facts(self):
        """shareable ファクトがない場合スキップされること"""
        from datetime import timedelta, timezone
        from bot.events import _try_proactive_conversation

        now = datetime.now(timezone.utc)
        pre_add_last_time = now - timedelta(minutes=30)

        message = MagicMock()
        message.created_at = now
        message.channel.id = 12345

        bot = MagicMock()

        mock_judge = MagicMock()
        mock_judge.is_in_cooldown.return_value = False

        mock_store = MagicMock()
        mock_store.get_shareable_facts.return_value = []

        with patch("config.REFLECTION_LULL_MINUTES", 10):
            with patch("memory.judge.get_judge", return_value=mock_judge):
                with patch("memory.fact_store.get_fact_store", return_value=mock_store):
                    with patch("bot.events._dispatch_proactive_message") as mock_dispatch:
                        await _try_proactive_conversation(bot, message, pre_add_last_time)
                        mock_dispatch.assert_not_called()

    @pytest.mark.asyncio
    async def test_dispatches_when_conditions_met(self):
        """条件が揃ったとき _dispatch_proactive_message が呼ばれること"""
        from datetime import timedelta, timezone
        from memory.fact_store import Fact
        import uuid
        from bot.events import _try_proactive_conversation

        now = datetime.now(timezone.utc)
        pre_add_last_time = now - timedelta(minutes=30)

        message = MagicMock()
        message.created_at = now
        message.channel.id = 12345

        bot = MagicMock()

        mock_fact = Fact(
            fact_id=str(uuid.uuid4()),
            channel_id=12345,
            content="Aさんがゲームを始めた",
            keywords=["ゲーム"],
            source_user_ids=[1],
            created_at=now,
            shareable=True,
        )

        mock_judge = MagicMock()
        mock_judge.is_in_cooldown.return_value = False
        mock_store = MagicMock()
        mock_store.get_shareable_facts.return_value = [mock_fact]

        with patch("config.REFLECTION_LULL_MINUTES", 10):
            with patch("memory.judge.get_judge", return_value=mock_judge):
                with patch("memory.fact_store.get_fact_store", return_value=mock_store):
                    with patch("bot.events._dispatch_proactive_message", new_callable=AsyncMock) as mock_dispatch:
                        await _try_proactive_conversation(bot, message, pre_add_last_time)
                        mock_dispatch.assert_called_once_with(bot, message, mock_fact)


class TestTryAutonomousResponseReaction:
    """_try_autonomous_response のリアクション機能テスト"""

    def _make_message_mock(self) -> MagicMock:
        message = MagicMock()
        message.channel.id = 12345
        message.content = "テストメッセージ"
        message.author.id = 67890
        message.author.display_name = "TestUser"
        message.created_at = datetime.now(timezone.utc)
        message.add_reaction = AsyncMock()
        return message

    @pytest.mark.asyncio
    @patch("bot.events.config")
    @patch("asyncio.create_task")
    async def test_reaction_fires_when_should_react_true(self, mock_create_task, mock_config):
        """should_react=True のとき asyncio.create_task でリアクションが発火すること"""
        mock_config.JUDGE_LLM_THRESHOLD_HIGH = 60
        mock_config.JUDGE_LLM_THRESHOLD_LOW = 20
        mock_config.LLM_JUDGE_ENABLED = False
        mock_config.BOT_NAME = "テストボット"

        from memory.judge import JudgeResult
        mock_result = JudgeResult(
            score=10,  # 低スコア: should_respond=False
            should_respond=False,
            reason="テスト",
            response_type="full_response",
            should_react=True,
            reaction_emojis=["👀"],
        )
        mock_judge = MagicMock()
        mock_judge.evaluate.return_value = mock_result

        mock_buffer = MagicMock()
        mock_buffer.get_recent_messages.return_value = []

        bot = MagicMock()
        message = self._make_message_mock()

        with patch("memory.judge.get_judge", return_value=mock_judge):
            with patch("memory.short_term.get_channel_buffer", return_value=mock_buffer):
                from bot.events import _try_autonomous_response
                await _try_autonomous_response(bot, message, [])

        mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    @patch("bot.events.config")
    @patch("asyncio.create_task")
    async def test_reaction_not_fired_when_should_react_false(self, mock_create_task, mock_config):
        """should_react=False のとき asyncio.create_task が呼ばれないこと"""
        mock_config.JUDGE_LLM_THRESHOLD_HIGH = 60
        mock_config.JUDGE_LLM_THRESHOLD_LOW = 20
        mock_config.LLM_JUDGE_ENABLED = False
        mock_config.BOT_NAME = "テストボット"

        from memory.judge import JudgeResult
        mock_result = JudgeResult(
            score=0,
            should_respond=False,
            reason="テスト",
            response_type="full_response",
            should_react=False,
        )
        mock_judge = MagicMock()
        mock_judge.evaluate.return_value = mock_result

        mock_buffer = MagicMock()
        mock_buffer.get_recent_messages.return_value = []

        bot = MagicMock()
        message = self._make_message_mock()

        with patch("memory.judge.get_judge", return_value=mock_judge):
            with patch("memory.short_term.get_channel_buffer", return_value=mock_buffer):
                from bot.events import _try_autonomous_response
                await _try_autonomous_response(bot, message, [])

        mock_create_task.assert_not_called()

    @pytest.mark.asyncio
    @patch("bot.events.config")
    @patch("asyncio.create_task")
    @patch("bot.events._dispatch_response")
    async def test_high_score_both_reaction_and_reply(
        self, mock_dispatch, mock_create_task, mock_config
    ):
        """高スコアで should_react=True のとき、リアクションと返信が両方実行されること"""
        mock_config.JUDGE_LLM_THRESHOLD_HIGH = 60
        mock_config.JUDGE_LLM_THRESHOLD_LOW = 20
        mock_config.LLM_JUDGE_ENABLED = False
        mock_config.BOT_NAME = "テストボット"

        from memory.judge import JudgeResult
        mock_result = JudgeResult(
            score=80,  # 高スコア
            should_respond=True,
            reason="テスト",
            response_type="full_response",
            should_react=True,
            reaction_emojis=["😊"],
        )
        mock_judge = MagicMock()
        mock_judge.evaluate.return_value = mock_result

        mock_buffer = MagicMock()
        mock_buffer.get_recent_messages.return_value = []

        bot = MagicMock()
        message = self._make_message_mock()

        with patch("memory.judge.get_judge", return_value=mock_judge):
            with patch("memory.short_term.get_channel_buffer", return_value=mock_buffer):
                from bot.events import _try_autonomous_response
                await _try_autonomous_response(bot, message, [])

        # リアクションも返信も発火
        mock_create_task.assert_called_once()
        mock_dispatch.assert_called_once()

    @pytest.mark.asyncio
    @patch("bot.events.config")
    @patch("asyncio.create_task")
    @patch("bot.events._dispatch_response")
    async def test_llm_judge_reaction_fires_when_llm_should_react(
        self, mock_dispatch, mock_create_task, mock_config
    ):
        """LLM Judge が should_react=True を返したとき、リアクションが発火すること"""
        mock_config.JUDGE_LLM_THRESHOLD_HIGH = 60
        mock_config.JUDGE_LLM_THRESHOLD_LOW = 20
        mock_config.LLM_JUDGE_ENABLED = True
        mock_config.BOT_NAME = "テストボット"

        from memory.judge import JudgeResult
        mock_result = JudgeResult(
            score=40,  # 中間スコア: LLM Judge へ
            should_respond=False,
            reason="テスト",
            response_type="full_response",
            should_react=False,  # ルールベースはreact不要
        )
        mock_judge = MagicMock()
        mock_judge.evaluate.return_value = mock_result

        mock_buffer = MagicMock()
        mock_buffer.get_recent_messages.return_value = []
        mock_buffer.get_context_string.return_value = "context"

        mock_llm_judge = MagicMock()
        mock_llm_judge.evaluate = AsyncMock(
            return_value=(True, "full_response", True, ["🤔"])
        )

        bot = MagicMock()
        message = self._make_message_mock()

        with patch("memory.judge.get_judge", return_value=mock_judge):
            with patch("memory.short_term.get_channel_buffer", return_value=mock_buffer):
                with patch("memory.llm_judge.get_llm_judge", return_value=mock_llm_judge):
                    from bot.events import _try_autonomous_response
                    await _try_autonomous_response(bot, message, [])

        # LLM judgeのリアクションが発火
        mock_create_task.assert_called_once()
        # 返信も発火
        mock_dispatch.assert_called_once()
