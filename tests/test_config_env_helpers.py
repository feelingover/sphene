"""config.py の環境変数ヘルパー（_env_bool / _env_int / _env_float）のテスト"""

import pytest

from config import _env_bool, _env_float, _env_int

VAR = "SPHENE_TEST_ENV_VAR"


class TestEnvBool:
    @pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "On", " true "])
    def test_true_values(self, monkeypatch, value):
        monkeypatch.setenv(VAR, value)
        assert _env_bool(VAR, False) is True

    @pytest.mark.parametrize("value", ["false", "False", "0", "no", "OFF"])
    def test_false_values(self, monkeypatch, value):
        monkeypatch.setenv(VAR, value)
        assert _env_bool(VAR, True) is False

    @pytest.mark.parametrize("default", [True, False])
    def test_unset_or_blank_uses_default(self, monkeypatch, default):
        monkeypatch.delenv(VAR, raising=False)
        assert _env_bool(VAR, default) is default
        monkeypatch.setenv(VAR, "  ")
        assert _env_bool(VAR, default) is default

    def test_invalid_value_names_variable(self, monkeypatch):
        monkeypatch.setenv(VAR, "maybe")
        with pytest.raises(ValueError, match=VAR):
            _env_bool(VAR, True)


class TestEnvInt:
    def test_parses(self, monkeypatch):
        monkeypatch.setenv(VAR, " 42 ")
        assert _env_int(VAR, 1) == 42

    def test_unset_uses_default(self, monkeypatch):
        monkeypatch.delenv(VAR, raising=False)
        assert _env_int(VAR, 7) == 7

    @pytest.mark.parametrize("value", ["abc", "1.5"])
    def test_invalid_value_names_variable(self, monkeypatch, value):
        monkeypatch.setenv(VAR, value)
        with pytest.raises(ValueError, match=VAR):
            _env_int(VAR, 1)


class TestEnvFloat:
    def test_parses(self, monkeypatch):
        monkeypatch.setenv(VAR, "0.25")
        assert _env_float(VAR, 1.0) == 0.25

    def test_unset_uses_default(self, monkeypatch):
        monkeypatch.delenv(VAR, raising=False)
        assert _env_float(VAR, 0.5) == 0.5

    def test_invalid_value_names_variable(self, monkeypatch):
        monkeypatch.setenv(VAR, "half")
        with pytest.raises(ValueError, match=VAR):
            _env_float(VAR, 1.0)
