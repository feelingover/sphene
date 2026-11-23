"""botテスト共通フィクスチャ"""

from collections.abc import Iterator

import pytest

import bot.events as events


@pytest.fixture(autouse=True)
def _reset_event_guards() -> Iterator[None]:
    """レート制限・翻訳重複抑止のモジュール状態をテスト間で持ち越さない"""
    for state in (
        events._user_mention_limiter._events,
        events._channel_mention_limiter._events,
        events._translated_messages,
    ):
        state.clear()
    yield
    for state in (
        events._user_mention_limiter._events,
        events._channel_mention_limiter._events,
        events._translated_messages,
    ):
        state.clear()
