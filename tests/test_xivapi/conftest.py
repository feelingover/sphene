"""XIVAPIテスト共通フィクスチャ"""

from collections.abc import Iterator

import pytest

import xivapi.client as xivapi_client


@pytest.fixture(autouse=True)
def _reset_shared_http_client() -> Iterator[None]:
    """テスト間で共有httpxクライアント (モック) が持ち越されないようにする"""
    xivapi_client._http_client = None
    yield
    xivapi_client._http_client = None
