"""短期記憶: チャンネルメッセージのリングバッファ"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import config
from log_utils.logger import logger
from memory.sanitize import safe_author_name, sanitize_llm_text

# 1発言あたりの最大文字数（Discordのメッセージ上限に合わせる）
_MAX_CONTEXT_CONTENT_LENGTH = 4000


def _to_utc(ts: datetime) -> datetime:
    """aware/naive datetime を UTC aware に変換する"""
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


@dataclass
class ChannelMessage:
    """チャンネルメッセージのデータクラス"""

    message_id: int
    channel_id: int
    author_id: int
    author_name: str
    content: str
    timestamp: datetime
    is_bot: bool = False
    attachments: list[str] = field(default_factory=list)
    guild_id: int | None = None


def _format_context_line(msg: ChannelMessage) -> str:
    """メッセージを ``名前[BOT]: 本文`` 形式の1行にする（偽装対策済み）"""
    name = safe_author_name(msg.author_name)
    role = "[BOT]" if msg.is_bot else ""
    content = sanitize_llm_text(msg.content, _MAX_CONTEXT_CONTENT_LENGTH) or ""
    return f"{name}{role}: {content}"


class ChannelMessageBuffer:
    """チャンネルごとのリングバッファ（collections.deque使用）"""

    def __init__(self, max_size: int, ttl_minutes: int) -> None:
        self._max_size = max_size
        self._ttl_minutes = ttl_minutes
        self._buffers: dict[int, deque[ChannelMessage]] = {}
        self._last_reflected: dict[int, datetime] = {}

    def add_message(self, msg: ChannelMessage) -> None:
        """メッセージをチャンネルバッファに追加する"""
        channel_id = msg.channel_id
        if channel_id not in self._buffers:
            self._buffers[channel_id] = deque(maxlen=self._max_size)
        self._buffers[channel_id].append(msg)
        logger.debug(
            f"バッファ追加: チャンネル={channel_id}, "
            f"サイズ={len(self._buffers[channel_id])}/{self._max_size}"
        )

    def get_recent_messages(
        self, channel_id: int, limit: int = 20
    ) -> list[ChannelMessage]:
        """チャンネルの直近メッセージを取得する（TTL超過を除外）"""
        if channel_id not in self._buffers:
            return []
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=self._ttl_minutes)
        messages = [
            msg
            for msg in self._buffers[channel_id]
            if _to_utc(msg.timestamp) > cutoff
        ]
        return messages[-limit:]

    def get_context_string(self, channel_id: int, limit: int = 10) -> str:
        """LLMに渡すためのフォーマット済みコンテキスト文字列を返す

        1発言を必ず1行に収める。本文の改行・制御文字はつぶし、名前からは
        ``[BOT]`` 表記や ``:`` 区切りを偽装できる記号を取り除くことで、
        他人やボットの発言行を挿入するプロンプトインジェクションを防ぐ。
        """
        messages = self.get_recent_messages(channel_id, limit)
        if not messages:
            return ""
        return "\n".join(_format_context_line(msg) for msg in messages)

    def cleanup_expired(self) -> int:
        """TTL超過メッセージを全チャンネルから削除する"""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=self._ttl_minutes)
        total_removed = 0
        empty_channels: list[int] = []

        for channel_id, buf in self._buffers.items():
            before = len(buf)
            # dequeなので左側（古い方）から期限切れを削除
            while buf and _to_utc(buf[0].timestamp) <= cutoff:
                buf.popleft()
                total_removed += 1
            if not buf:
                empty_channels.append(channel_id)

        # 空になったチャンネルのバッファを削除
        for channel_id in empty_channels:
            del self._buffers[channel_id]

        return total_removed

    def get_active_channel_ids(self) -> list[int]:
        """バッファが存在するチャンネルIDのリストを返す"""
        return list(self._buffers.keys())

    def get_last_message_time(self, channel_id: int) -> datetime | None:
        """最新メッセージのタイムスタンプをUTCで返す（バッファが空なら None）"""
        buf = self._buffers.get(channel_id)
        if not buf:
            return None
        return _to_utc(buf[-1].timestamp)

    def count_messages_since_reflection(self, channel_id: int) -> int:
        """最後の反省会以降のメッセージ数を返す"""
        buf = self._buffers.get(channel_id)
        if not buf:
            return 0
        last_reflected = self._last_reflected.get(channel_id)
        if last_reflected is None:
            return len(buf)
        count = 0
        for msg in buf:
            if _to_utc(msg.timestamp) > last_reflected:
                count += 1
        return count

    def get_messages_since_reflection(
        self, channel_id: int, limit: int = 100
    ) -> list[ChannelMessage]:
        """最後の反省会以降のメッセージを返す（TTL超過を除外）

        反省会に同じメッセージを繰り返し渡さないよう、チェックポイント以降の差分だけを返す。

        Args:
            channel_id: チャンネルID
            limit: 返す最大件数（新しい方から）

        Returns:
            チェックポイントより新しいメッセージのリスト（古い順）
        """
        messages = self.get_recent_messages(channel_id, limit=self._max_size)
        last_reflected = self._last_reflected.get(channel_id)
        if last_reflected is not None:
            messages = [m for m in messages if _to_utc(m.timestamp) > last_reflected]
        return messages[-limit:]

    def mark_reflected(
        self, channel_id: int, until: datetime | None = None
    ) -> None:
        """反省会実行後に呼び、チェックポイントを記録する

        Args:
            channel_id: チャンネルID
            until: 処理済みメッセージの最大タイムスタンプ。指定すると、反省会の
                LLM呼び出し中に届いたメッセージを次回の対象として取りこぼさない。
                省略時は現在時刻。
        """
        checkpoint = _to_utc(until) if until is not None else datetime.now(timezone.utc)
        previous = self._last_reflected.get(channel_id)
        if previous is not None and checkpoint <= previous:
            return
        self._last_reflected[channel_id] = checkpoint

    @property
    def channel_count(self) -> int:
        """バッファを持つチャンネル数"""
        return len(self._buffers)


# モジュールレベルのシングルトン
_buffer: ChannelMessageBuffer | None = None


def get_channel_buffer() -> ChannelMessageBuffer:
    """チャンネルバッファのシングルトンインスタンスを取得する"""
    global _buffer
    if _buffer is None:
        _buffer = ChannelMessageBuffer(
            max_size=config.CHANNEL_BUFFER_SIZE,
            ttl_minutes=config.CHANNEL_BUFFER_TTL_MINUTES,
        )
        logger.info(
            f"チャンネルバッファ初期化: max_size={config.CHANNEL_BUFFER_SIZE}, "
            f"ttl={config.CHANNEL_BUFFER_TTL_MINUTES}分"
        )
    return _buffer
