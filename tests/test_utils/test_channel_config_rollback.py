"""ChannelConfig の保存失敗時ロールバックと保存先ディレクトリ設定のテスト"""

import json
import os
from pathlib import Path
from typing import Any, Callable, Iterator
from unittest.mock import patch

import pytest

from utils.channel_config import ChannelConfig, ChannelConfigManager


@pytest.fixture
def local_conf(tmp_path: Path) -> Iterator[ChannelConfig]:
    """tmp_path を保存先とするローカルストレージの ChannelConfig"""
    with patch("config.LOCAL_STORAGE_DIR", str(tmp_path)):
        conf = ChannelConfig(guild_id="g1", storage_type="local")
        assert conf.save_config() is True
        assert conf.add_channel(100, "keep") is True
        yield conf


_MUTATIONS: list[tuple[str, Callable[[ChannelConfig], bool]]] = [
    ("set_behavior", lambda c: c.set_behavior("allow")),
    ("add_channel", lambda c: c.add_channel(200, "new")),
    ("remove_channel", lambda c: c.remove_channel(100)),
    ("clear_channels", lambda c: c.clear_channels()),
    ("set_translation_enabled", lambda c: c.set_translation_enabled(True)),
]


class TestRollbackOnSaveFailure:
    """保存に失敗したらメモリ上の config_data を変更前に戻す"""

    @pytest.mark.parametrize("name,mutate", _MUTATIONS, ids=[m[0] for m in _MUTATIONS])
    def test_rolls_back_on_failure(
        self, local_conf: ChannelConfig, name: str, mutate: Callable[[ChannelConfig], bool]
    ) -> None:
        before: dict[str, Any] = json.loads(json.dumps(local_conf.config_data))

        with patch("utils.file_utils.atomic_write_json", side_effect=OSError("disk full")):
            assert mutate(local_conf) is False

        assert local_conf.config_data == before

    @pytest.mark.parametrize("name,mutate", _MUTATIONS, ids=[m[0] for m in _MUTATIONS])
    def test_keeps_change_on_success(
        self, local_conf: ChannelConfig, name: str, mutate: Callable[[ChannelConfig], bool]
    ) -> None:
        before: dict[str, Any] = json.loads(json.dumps(local_conf.config_data))

        assert mutate(local_conf) is True

        assert local_conf.config_data != before

    def test_add_channel_failure_does_not_leak_into_channel_list(
        self, local_conf: ChannelConfig
    ) -> None:
        """get_channels() の参照を保持していても失敗した追加が混入しない"""
        with patch("utils.file_utils.atomic_write_json", side_effect=OSError("disk full")):
            assert local_conf.add_channel(200, "new") is False

        assert local_conf.is_channel_in_list(200) is False
        assert local_conf.is_channel_in_list(100) is True

    def test_firestore_failure_rolls_back(self) -> None:
        conf = ChannelConfig(guild_id="g2", storage_type="firestore", debug_mode=True)
        conf.debug_mode = False
        with patch("utils.channel_config.get_firestore_client", side_effect=RuntimeError("down")):
            assert conf.set_behavior("allow") is False
        assert conf.get_behavior() == "deny"

    def test_load_failed_rolls_back(self) -> None:
        """読み込み失敗で保存拒否された場合もロールバックされる"""
        conf = ChannelConfig(guild_id="g3", debug_mode=True)
        conf.debug_mode = False
        conf.load_failed = True
        assert conf.set_behavior("allow") is False
        assert conf.get_behavior() == "deny"


class TestLocalStorageDir:
    """LOCAL_STORAGE_DIR でローカル保存先を切り替えられる"""

    def test_config_file_path_uses_env_dir(self, tmp_path: Path) -> None:
        with patch("config.LOCAL_STORAGE_DIR", str(tmp_path)):
            conf = ChannelConfig(guild_id="g4", debug_mode=True)
            assert conf._get_config_file_path() == os.path.join(
                str(tmp_path), "channel_list.g4.json"
            )

    def test_save_and_reload_from_custom_dir(self, local_conf: ChannelConfig, tmp_path: Path) -> None:
        assert (tmp_path / "channel_list.g1.json").exists()
        with patch("config.LOCAL_STORAGE_DIR", str(tmp_path)):
            reloaded = ChannelConfig(guild_id="g1", storage_type="local")
        assert reloaded.is_channel_in_list(100) is True

    def test_delete_uses_env_dir(self, local_conf: ChannelConfig, tmp_path: Path) -> None:
        manager = ChannelConfigManager(debug_mode=False)
        with patch("config.LOCAL_STORAGE_DIR", str(tmp_path)), patch(
            "config.STORAGE_TYPE", "local"
        ):
            assert manager.delete_guild_config("g1") is True
        assert not (tmp_path / "channel_list.g1.json").exists()
