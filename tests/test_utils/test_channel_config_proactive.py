"""ChannelConfig の proactive_channels（自発会話の opt-in）のテスト"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from utils.channel_config import ChannelConfig


def _local_conf(tmp_path: Path) -> ChannelConfig:
    with patch("config.LOCAL_STORAGE_DIR", str(tmp_path)):
        return ChannelConfig(guild_id="g1", storage_type="local")


class TestProactiveChannels:
    """opt-in チャンネルの追加・削除・判定"""

    def test_default_is_empty(self) -> None:
        conf = ChannelConfig(guild_id="g1", debug_mode=True)
        assert conf.get_proactive_channels() == []
        assert conf.is_proactive_channel(100) is False

    def test_add_and_remove(self) -> None:
        conf = ChannelConfig(guild_id="g1", debug_mode=True)
        assert conf.add_proactive_channel(100) is True
        assert conf.add_proactive_channel(200) is True
        assert conf.is_proactive_channel(100) is True
        assert conf.is_proactive_channel("100") is True
        assert conf.get_proactive_channels() == ["100", "200"]
        assert conf.remove_proactive_channel(100) is True
        assert conf.get_proactive_channels() == ["200"]

    def test_add_is_idempotent(self) -> None:
        conf = ChannelConfig(guild_id="g1", debug_mode=True)
        conf.add_proactive_channel(100)
        with patch.object(conf, "save_config") as save:
            assert conf.add_proactive_channel("100") is True
        save.assert_not_called()
        assert conf.get_proactive_channels() == ["100"]

    def test_remove_unregistered_is_noop(self) -> None:
        conf = ChannelConfig(guild_id="g1", debug_mode=True)
        with patch.object(conf, "save_config") as save:
            assert conf.remove_proactive_channel(100) is True
        save.assert_not_called()

    def test_save_failure_rolls_back(self) -> None:
        conf = ChannelConfig(guild_id="g1", debug_mode=True)
        conf.add_proactive_channel(100)
        with patch.object(conf, "save_config", return_value=False):
            assert conf.add_proactive_channel(200) is False
            assert conf.remove_proactive_channel(100) is False
        assert conf.get_proactive_channels() == ["100"]

    def test_invalid_field_is_treated_as_empty(self) -> None:
        conf = ChannelConfig(guild_id="g1", debug_mode=True)
        conf.config_data["proactive_channels"] = "broken"
        assert conf.get_proactive_channels() == []
        assert conf.add_proactive_channel(100) is True
        assert conf.get_proactive_channels() == ["100"]


class TestProactivePersistence:
    """local / Firestore での永続化と旧データとの互換"""

    def test_legacy_local_data_without_field(self, tmp_path: Path) -> None:
        (tmp_path / "channel_list.g1.json").write_text(
            json.dumps({"behavior": "allow", "channels": [], "translation_enabled": True}),
            encoding="utf-8",
        )
        conf = _local_conf(tmp_path)
        assert conf.load_failed is False
        assert conf.get_proactive_channels() == []
        with patch("config.LOCAL_STORAGE_DIR", str(tmp_path)):
            assert conf.add_proactive_channel(100) is True
        saved = json.loads((tmp_path / "channel_list.g1.json").read_text(encoding="utf-8"))
        assert saved["proactive_channels"] == ["100"]
        # 既存の設定は保たれる
        assert saved["behavior"] == "allow"
        assert saved["translation_enabled"] is True

    def test_local_round_trip(self, tmp_path: Path) -> None:
        conf = _local_conf(tmp_path)
        with patch("config.LOCAL_STORAGE_DIR", str(tmp_path)):
            conf.add_proactive_channel(100)
        reloaded = _local_conf(tmp_path)
        assert reloaded.get_proactive_channels() == ["100"]

    def test_firestore_round_trip(self) -> None:
        db = MagicMock()
        doc = db.collection.return_value.document.return_value
        doc.get.return_value.exists = True
        doc.get.return_value.to_dict.return_value = {"behavior": "deny", "channels": []}
        with patch("utils.channel_config.get_firestore_client", return_value=db):
            conf = ChannelConfig(guild_id="g1", storage_type="firestore")
            assert conf.get_proactive_channels() == []
            assert conf.add_proactive_channel(100) is True
        saved = doc.set.call_args.args[0]
        assert saved["proactive_channels"] == ["100"]
