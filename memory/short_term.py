"""短期記憶: チャンネルメッセージのリングバッファ"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import config
from log_utils.logger import logger


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


class ChannelMessageBuffer:
    """チャンネルごとのリングバッファ（collections.deque使用）"""

    def __init__(self, max_size: int, ttl_minutes: int) -> None:
        self._max_size = max_size
        self._ttl_minutes = ttl_minutes
        self._buffers: dict[int, deque[ChannelMessage]] = {}

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
            if msg.timestamp.replace(tzinfo=timezone.utc) > cutoff
        ]
        return messages[-limit:]

    def get_context_string(self, channel_id: int, limit: int = 10) -> str:
        """LLMに渡すためのフォーマット済みコンテキスト文字列を返す"""
        messages = self.get_recent_messages(channel_id, limit)
        if not messages:
            return ""
        lines = []
        for msg in messages:
            role = "[BOT]" if msg.is_bot else ""
            lines.append(f"{msg.author_name}{role}: {msg.content}")
        return "\n".join(lines)

    def cleanup_expired(self) -> int:
        """TTL超過メッセージを全チャンネルから削除する"""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=self._ttl_minutes)
        total_removed = 0
        empty_channels: list[int] = []

        for channel_id, buf in self._buffers.items():
            before = len(buf)
            # dequeなので左側（古い方）から期限切れを削除
            while buf and buf[0].timestamp.replace(tzinfo=timezone.utc) <= cutoff:
                buf.popleft()
                total_removed += 1
            if not buf:
                empty_channels.append(channel_id)

        # 空になったチャンネルのバッファを削除
        for channel_id in empty_channels:
            del self._buffers[channel_id]

        return total_removed

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
