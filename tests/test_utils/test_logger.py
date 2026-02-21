import io
import json
import logging
import os
import re
from unittest.mock import patch

from log_utils.logger import _create_formatter, get_log_level, setup_logger


def test_get_log_level() -> None:
    """ログレベル文字列変換のテスト"""
    assert get_log_level("DEBUG") == logging.DEBUG
    assert get_log_level("INFO") == logging.INFO
    assert get_log_level("WARNING") == logging.WARNING
    assert get_log_level("ERROR") == logging.ERROR
    assert get_log_level("CRITICAL") == logging.CRITICAL
    # 無効な値の場合のデフォルト値テスト
    assert get_log_level("INVALID") == logging.INFO
    assert get_log_level("") == logging.INFO


def test_create_formatter_returns_json_formatter() -> None:
    """LOG_FORMAT=json の場合は JsonFormatter が返されることのテスト"""
    from pythonjsonlogger.json import JsonFormatter

    with patch("config.LOG_FORMAT", "json"):
        fmt = _create_formatter()
        assert isinstance(fmt, JsonFormatter)


def test_create_formatter_returns_text_formatter() -> None:
    """LOG_FORMAT=text の場合は標準 Formatter が返されることのテスト"""
    from pythonjsonlogger.json import JsonFormatter

    with patch("config.LOG_FORMAT", "text"):
        fmt = _create_formatter()
        assert isinstance(fmt, logging.Formatter)
        assert not isinstance(fmt, JsonFormatter)


def test_create_formatter_json_output_fields() -> None:
    """JSON フォーマッターが GCL 向けフィールド名で出力することのテスト"""
    with patch("config.LOG_FORMAT", "json"):
        fmt = _create_formatter()

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(fmt)
    test_logger = logging.getLogger("test_json_fields")
    test_logger.addHandler(handler)
    test_logger.setLevel(logging.INFO)
    test_logger.propagate = False

    test_logger.info("テストメッセージ")
    output = json.loads(stream.getvalue())

    assert output["severity"] == "INFO"
    assert output["logger"] == "test_json_fields"
    assert output["message"] == "テストメッセージ"
    assert "time" in output
    test_logger.removeHandler(handler)


def test_create_formatter_json_timestamp_rfc3339() -> None:
    """JSON フォーマッターのタイムスタンプが RFC3339 形式（+HH:MM）であることのテスト"""
    with patch("config.LOG_FORMAT", "json"):
        fmt = _create_formatter()

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(fmt)
    test_logger = logging.getLogger("test_rfc3339")
    test_logger.addHandler(handler)
    test_logger.setLevel(logging.INFO)
    test_logger.propagate = False

    test_logger.info("時刻テスト")
    output = json.loads(stream.getvalue())

    # RFC3339: コロンあり (+HH:MM 形式)
    assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$", output["time"])
    test_logger.removeHandler(handler)


def test_setup_logger_with_env_var(mock_env_vars: dict[str, str]) -> None:
    """環境変数からログレベルを取得するテスト"""
    # テストではmock_env_varsで"DEBUG"を設定済み
    with patch("config.LOG_LEVEL", "DEBUG"):
        with patch("logging.basicConfig") as mock_config:
            _ = setup_logger("test_logger")
            # basicConfigがDEBUGレベルで呼ばれたことを確認
            mock_config.assert_called_once()
            args, kwargs = mock_config.call_args
            assert kwargs["level"] == logging.DEBUG


def test_setup_logger_default_level() -> None:
    """環境変数がない場合のデフォルトレベルテスト"""
    # 環境変数をクリアしてデフォルト値をテスト
    with patch.dict(os.environ, {}, clear=True):
        with patch("config.LOG_LEVEL", ""):
            with patch("logging.basicConfig") as mock_config:
                _ = setup_logger("test_default_logger")
                # デフォルトのINFOレベルでbasicConfigが呼ばれたことを確認
                mock_config.assert_called_once()
                args, kwargs = mock_config.call_args
                assert kwargs["level"] == logging.INFO
