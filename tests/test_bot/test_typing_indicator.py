"""入力中インジケーター（bot/events.py）のテスト"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.events import _typing_indicator


def _make_channel(enter_side_effect: Exception | None = None) -> tuple[MagicMock, MagicMock]:
    """typing() を持つチャンネルのモックを作る"""
    typing_cm = MagicMock()
    typing_cm.__aenter__ = AsyncMock(side_effect=enter_side_effect)
    typing_cm.__aexit__ = AsyncMock(return_value=None)
    channel = MagicMock()
    channel.typing.return_value = typing_cm
    return channel, typing_cm


class TestTypingIndicator:
    """_typing_indicator のテスト"""

    @pytest.mark.asyncio
    async def test_enters_and_exits_typing(self) -> None:
        """ブロックの前後でインジケーターの開始と終了が呼ばれる"""
        channel, typing_cm = _make_channel()

        async with _typing_indicator(channel):
            typing_cm.__aenter__.assert_awaited_once()
            typing_cm.__aexit__.assert_not_awaited()

        typing_cm.__aexit__.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_exits_typing_when_body_raises(self) -> None:
        """ブロック内で例外が起きてもインジケーターは終了し、例外は伝播する"""
        channel, typing_cm = _make_channel()

        with pytest.raises(ValueError):
            async with _typing_indicator(channel):
                raise ValueError("boom")

        typing_cm.__aexit__.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_continues_when_typing_fails(self) -> None:
        """インジケーターの表示に失敗しても処理は継続する"""
        channel, typing_cm = _make_channel(enter_side_effect=RuntimeError("forbidden"))
        executed = False

        with patch("bot.events.logger") as mock_logger:
            async with _typing_indicator(channel):
                executed = True

        assert executed is True
        mock_logger.warning.assert_called_once()
        typing_cm.__aexit__.assert_not_awaited()


class TestTypingIndicatorUsage:
    """応答生成時にインジケーターが使われることのテスト"""

    @pytest.mark.asyncio
    @patch("asyncio.to_thread")
    @patch("memory.judge.get_judge")
    @patch("memory.short_term.get_channel_buffer")
    async def test_short_ack_shows_typing_before_send(
        self, mock_buffer_fn: MagicMock, mock_get_judge: MagicMock, mock_to_thread: MagicMock
    ) -> None:
        """相槌の生成中はインジケーターが表示され、送信前に終了する"""
        from bot.events import _process_short_ack

        mock_buffer = MagicMock()
        mock_buffer.get_context_string.return_value = "User1: ありがとう"
        mock_buffer_fn.return_value = mock_buffer
        mock_to_thread.return_value = "どういたしまして！"

        channel, typing_cm = _make_channel()
        events: list[str] = []
        typing_cm.__aenter__.side_effect = lambda *a: events.append("typing_start")
        typing_cm.__aexit__.side_effect = lambda *a: events.append("typing_end")
        channel.send = AsyncMock(side_effect=lambda *a, **k: events.append("send"))
        channel.id = 100

        message = MagicMock()
        message.channel = channel
        message.content = "ありがとう"

        await _process_short_ack(MagicMock(), message)

        assert events == ["typing_start", "typing_end", "send"]

    @pytest.mark.asyncio
    @patch("utils.text_utils.translate_to_english")
    async def test_translation_shows_typing_before_send(self, mock_translate: AsyncMock) -> None:
        """翻訳中はインジケーターが表示され、送信前に終了する"""
        from bot.events import translate_and_reply

        events: list[str] = []

        async def _translate(_: str) -> str:
            events.append("translate")
            return "Good work today!"

        mock_translate.side_effect = _translate

        channel, typing_cm = _make_channel()
        typing_cm.__aenter__.side_effect = lambda *a: events.append("typing_start")
        typing_cm.__aexit__.side_effect = lambda *a: events.append("typing_end")
        channel.send = AsyncMock(side_effect=lambda *a, **k: events.append("send"))

        message = MagicMock()
        message.channel = channel
        message.content = "おつかれ〜！"
        message.author.id = 12345

        await translate_and_reply(message)

        assert events == ["typing_start", "translate", "typing_end", "send"]
