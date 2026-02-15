"""短期記憶（チャンネルメッセージバッファ）のテスト"""

# type: ignore
# mypy: ignore-errors

from datetime import datetime, timedelta, timezone

import pytest

from memory.short_term import ChannelMessage, ChannelMessageBuffer


def _make_message(
    channel_id: int = 100,
    author_name: str = "TestUser",
    content: str = "テストメッセージ",
    minutes_ago: int = 0,
    message_id: int = 1,
    is_bot: bool = False,
) -> ChannelMessage:
    """テスト用ChannelMessageを生成するヘルパー"""
    return ChannelMessage(
        message_id=message_id,
        channel_id=channel_id,
        author_id=12345,
        author_name=author_name,
        content=content,
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        is_bot=is_bot,
    )


class TestChannelMessageBuffer:
    """ChannelMessageBufferのテスト"""

    def test_add_and_get_messages(self):
        """メッセージの追加と取得"""
        buf = ChannelMessageBuffer(max_size=10, ttl_minutes=30)
        msg = _make_message(content="Hello")
        buf.add_message(msg)

        messages = buf.get_recent_messages(100)
        assert len(messages) == 1
        assert messages[0].content == "Hello"

    def test_ring_buffer_max_size(self):
        """リングバッファの最大サイズ制限"""
        buf = ChannelMessageBuffer(max_size=3, ttl_minutes=30)
        for i in range(5):
            buf.add_message(_make_message(content=f"msg{i}", message_id=i))

        messages = buf.get_recent_messages(100)
        assert len(messages) == 3
        # 最新の3つが残る
        assert messages[0].content == "msg2"
        assert messages[1].content == "msg3"
        assert messages[2].content == "msg4"

    def test_get_recent_messages_with_limit(self):
        """limitパラメータが機能するか"""
        buf = ChannelMessageBuffer(max_size=10, ttl_minutes=30)
        for i in range(5):
            buf.add_message(_make_message(content=f"msg{i}", message_id=i))

        messages = buf.get_recent_messages(100, limit=2)
        assert len(messages) == 2
        # 最新の2つが返る
        assert messages[0].content == "msg3"
        assert messages[1].content == "msg4"

    def test_ttl_expiration(self):
        """TTL超過メッセージが取得されないこと"""
        buf = ChannelMessageBuffer(max_size=10, ttl_minutes=30)
        # 古いメッセージ（40分前）
        buf.add_message(_make_message(content="old", minutes_ago=40, message_id=1))
        # 新しいメッセージ（5分前）
        buf.add_message(_make_message(content="new", minutes_ago=5, message_id=2))

        messages = buf.get_recent_messages(100)
        assert len(messages) == 1
        assert messages[0].content == "new"

    def test_cleanup_expired(self):
        """cleanup_expiredが期限切れメッセージを削除すること"""
        buf = ChannelMessageBuffer(max_size=10, ttl_minutes=30)
        # 古いメッセージ
        buf.add_message(_make_message(content="old1", minutes_ago=40, message_id=1))
        buf.add_message(_make_message(content="old2", minutes_ago=35, message_id=2))
        # 新しいメッセージ
        buf.add_message(_make_message(content="new", minutes_ago=5, message_id=3))

        removed = buf.cleanup_expired()
        assert removed == 2
        # 残りは1メッセージ
        messages = buf.get_recent_messages(100)
        assert len(messages) == 1
        assert messages[0].content == "new"

    def test_cleanup_removes_empty_channels(self):
        """全メッセージが期限切れのチャンネルバッファが削除されること"""
        buf = ChannelMessageBuffer(max_size=10, ttl_minutes=30)
        buf.add_message(
            _make_message(channel_id=100, content="old", minutes_ago=40, message_id=1)
        )
        buf.add_message(
            _make_message(channel_id=200, content="new", minutes_ago=5, message_id=2)
        )

        assert buf.channel_count == 2
        buf.cleanup_expired()
        assert buf.channel_count == 1

    def test_separate_channels(self):
        """チャンネルごとに独立したバッファが管理されること"""
        buf = ChannelMessageBuffer(max_size=10, ttl_minutes=30)
        buf.add_message(_make_message(channel_id=100, content="ch100", message_id=1))
        buf.add_message(_make_message(channel_id=200, content="ch200", message_id=2))

        msgs_100 = buf.get_recent_messages(100)
        msgs_200 = buf.get_recent_messages(200)
        assert len(msgs_100) == 1
        assert len(msgs_200) == 1
        assert msgs_100[0].content == "ch100"
        assert msgs_200[0].content == "ch200"

    def test_get_recent_messages_empty_channel(self):
        """存在しないチャンネルIDで空リストが返ること"""
        buf = ChannelMessageBuffer(max_size=10, ttl_minutes=30)
        messages = buf.get_recent_messages(999)
        assert messages == []

    def test_get_context_string(self):
        """コンテキスト文字列のフォーマット"""
        buf = ChannelMessageBuffer(max_size=10, ttl_minutes=30)
        buf.add_message(
            _make_message(
                author_name="UserA", content="こんにちは", message_id=1
            )
        )
        buf.add_message(
            _make_message(
                author_name="Bot", content="やぁ！", message_id=2, is_bot=True
            )
        )

        context = buf.get_context_string(100)
        assert "UserA: こんにちは" in context
        assert "Bot[BOT]: やぁ！" in context

    def test_get_context_string_empty(self):
        """空チャンネルのコンテキスト文字列が空文字列であること"""
        buf = ChannelMessageBuffer(max_size=10, ttl_minutes=30)
        context = buf.get_context_string(999)
        assert context == ""

    def test_get_context_string_with_limit(self):
        """コンテキスト文字列のlimit指定"""
        buf = ChannelMessageBuffer(max_size=10, ttl_minutes=30)
        for i in range(5):
            buf.add_message(
                _make_message(content=f"msg{i}", message_id=i)
            )

        context = buf.get_context_string(100, limit=2)
        lines = context.strip().split("\n")
        assert len(lines) == 2

    def test_channel_count(self):
        """channel_countプロパティ"""
        buf = ChannelMessageBuffer(max_size=10, ttl_minutes=30)
        assert buf.channel_count == 0

        buf.add_message(_make_message(channel_id=100, message_id=1))
        assert buf.channel_count == 1

        buf.add_message(_make_message(channel_id=200, message_id=2))
        assert buf.channel_count == 2
