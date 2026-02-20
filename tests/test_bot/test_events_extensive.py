"""
bot/events.py の広範なテスト
"""

# type: ignore
# mypy: ignore-errors

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import config
from bot.events import (
    is_bot_mentioned,
    process_conversation,
    _handle_on_ready,
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
        with patch("config.BOT_NAME", "アサヒ"):
            msg2 = MagicMock()
            msg2.content = "アサヒ、今日の天気は？"
            msg2.mentions = []
            mentioned, q, is_reply = await is_bot_mentioned(bot, msg2)
            assert mentioned is True
            assert q == "アサヒ、今日の天気は？"
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
    @patch("bot.events.channel_conversations")
    @patch("bot.events.split_message")
    async def test_process_conversation_chunking(self, mock_split, mock_conversations):
        """会話のチャンク分割送信テスト"""
        mock_api = MagicMock()
        mock_api.input_message.return_value = "Long message"
        mock_conversations.__getitem__.return_value = mock_api
        mock_split.return_value = ["Chunk 1", "Chunk 2"]

        message = MagicMock()
        message.channel.send = AsyncMock()

        await process_conversation(message, "question", is_reply=True)

        # 2つのチャンクが送信される
        assert message.channel.send.call_count == 2
        # 最初はリプライ（referenceあり）
        message.channel.send.assert_any_call("Chunk 1", reference=message)
        # 次は通常送信
        message.channel.send.assert_any_call("Chunk 2")

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

        bot.tree.add_command.assert_called_once_with(command_group)
        bot.tree.sync.assert_called_once()
        # 各ギルドの設定が初期化される
        assert mock_config_manager.get_config.call_count == 2

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
    @patch("bot.events.generate_contextual_response")
    @patch("bot.events.split_message")
    @patch("memory.judge.get_judge")
    async def test_process_autonomous_response(self, mock_get_judge, mock_split, mock_gen, mock_get_buffer):
        """自律応答の生成と送信プロセステスト"""
        bot = MagicMock()
        bot.user.id = 123
        message = MagicMock()
        message.channel.id = 100
        message.content = "Hello"
        
        mock_buffer = MagicMock()
        mock_buffer.get_context_string.return_value = "Past context"
        mock_get_buffer.return_value = mock_buffer
        
        mock_gen.return_value = "Autonomous Answer"
        mock_split.return_value = ["Autonomous Answer"]
        message.channel.send = AsyncMock()

        await _process_autonomous_response(bot, message, [])

        message.channel.send.assert_called_once_with("Autonomous Answer")
        mock_get_judge().record_response.assert_called_once_with(100)
        mock_buffer.add_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_reaction_exception(self):
        """リアクション処理中の例外ハンドリングテスト"""
        bot = MagicMock()
        reaction = MagicMock()
        reaction.message.channel.send = AsyncMock()
        reaction.emoji = "🇺🇸"
        user = MagicMock()
        user.bot = False
        
        with patch("bot.events.config_manager") as mock_cm:
            # get_config で例外を発生させる
            mock_cm.get_config.side_effect = Exception("Reaction Error")
            from bot.events import _handle_reaction
            await _handle_reaction(bot, reaction, user)
            
            reaction.message.channel.send.assert_called_once()
            args, _ = reaction.message.channel.send.call_args
            assert "エラーが発生しました" in args[0]

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
