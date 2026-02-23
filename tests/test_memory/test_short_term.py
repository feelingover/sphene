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

    def test_get_active_channel_ids_empty(self):
        """チャンネルなしの場合、空リストが返ること"""
        buf = ChannelMessageBuffer(max_size=10, ttl_minutes=30)
        assert buf.get_active_channel_ids() == []

    def test_get_active_channel_ids_multiple(self):
        """複数チャンネルのIDがリストで返ること"""
        buf = ChannelMessageBuffer(max_size=10, ttl_minutes=30)
        buf.add_message(_make_message(channel_id=100, message_id=1))
        buf.add_message(_make_message(channel_id=200, message_id=2))
        ids = buf.get_active_channel_ids()
        assert set(ids) == {100, 200}

    def test_get_last_message_time_none_for_empty(self):
        """バッファが空のチャンネルは None を返すこと"""
        buf = ChannelMessageBuffer(max_size=10, ttl_minutes=30)
        assert buf.get_last_message_time(999) is None

    def test_get_last_message_time_returns_latest(self):
        """最新メッセージのタイムスタンプが返ること"""
        buf = ChannelMessageBuffer(max_size=10, ttl_minutes=30)
        buf.add_message(_make_message(minutes_ago=10, message_id=1))
        buf.add_message(_make_message(minutes_ago=2, message_id=2))
        last = buf.get_last_message_time(100)
        assert last is not None
        # 直近のメッセージが約2分前であることを確認
        from datetime import datetime, timedelta, timezone
        diff = datetime.now(timezone.utc) - last
        assert diff < timedelta(minutes=3)

    def test_get_last_message_time_timezone_aware(self):
        """返り値がタイムゾーン付きであること"""
        buf = ChannelMessageBuffer(max_size=10, ttl_minutes=30)
        buf.add_message(_make_message(message_id=1))
        last = buf.get_last_message_time(100)
        assert last is not None
        assert last.tzinfo is not None

    def test_count_messages_since_reflection_all_when_not_marked(self):
        """mark_reflected が呼ばれていない場合、全件数を返すこと"""
        buf = ChannelMessageBuffer(max_size=10, ttl_minutes=30)
        for i in range(5):
            buf.add_message(_make_message(message_id=i))
        assert buf.count_messages_since_reflection(100) == 5

    def test_count_messages_since_reflection_after_mark(self):
        """mark_reflected 後のメッセージのみがカウントされること"""
        buf = ChannelMessageBuffer(max_size=10, ttl_minutes=30)
        for i in range(3):
            buf.add_message(_make_message(message_id=i, minutes_ago=5))
        buf.mark_reflected(100)
        # mark_reflected 後に新しいメッセージを追加
        buf.add_message(_make_message(message_id=10, minutes_ago=0))
        count = buf.count_messages_since_reflection(100)
        assert count == 1

    def test_count_messages_since_reflection_empty(self):
        """バッファが空の場合 0 を返すこと"""
        buf = ChannelMessageBuffer(max_size=10, ttl_minutes=30)
        assert buf.count_messages_since_reflection(999) == 0

    def test_mark_reflected_sets_checkpoint(self):
        """mark_reflected が現在時刻をチェックポイントとして記録すること"""
        buf = ChannelMessageBuffer(max_size=10, ttl_minutes=30)
        buf.mark_reflected(100)
        assert 100 in buf._last_reflected

    def test_mark_reflected_multiple_times(self):
        """mark_reflected を複数回呼んでも正常に動作すること"""
        buf = ChannelMessageBuffer(max_size=10, ttl_minutes=30)
        buf.add_message(_make_message(message_id=1, minutes_ago=2))
        buf.mark_reflected(100)
        buf.add_message(_make_message(message_id=2, minutes_ago=0))
        buf.mark_reflected(100)
        # 2回目の mark_reflected 後は新規メッセージなし
        assert buf.count_messages_since_reflection(100) == 0
