"""botテスト共通フィクスチャ"""

from collections.abc import Iterator

from unittest.mock import patch

import pytest

import bot.events as events


@pytest.fixture(autouse=True)
def _keep_test_process_sigterm() -> Iterator[None]:
    """SpheneBot.run の終了処理がテストプロセス自体の SIGTERM を無視に変えないようにする"""
    with patch("bot.discord_bot._ignore_sigterm"):
        yield


@pytest.fixture(autouse=True)
def _reset_event_guards() -> Iterator[None]:
    """レート制限・翻訳重複抑止のモジュール状態をテスト間で持ち越さない"""
    for state in (
        events._user_mention_limiter._events,
        events._channel_mention_limiter._events,
        events._user_translation_limiter._events,
        events._channel_translation_limiter._events,
        events._reaction_error_notify_limiter._events,
        events._translated_messages,
    ):
        state.clear()
    yield
    for state in (
        events._user_mention_limiter._events,
        events._channel_mention_limiter._events,
        events._user_translation_limiter._events,
        events._channel_translation_limiter._events,
        events._reaction_error_notify_limiter._events,
        events._translated_messages,
    ):
        state.clear()
