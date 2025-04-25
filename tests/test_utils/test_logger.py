import logging
import os
from typing import Dict
from unittest.mock import patch

from log_utils.logger import get_log_level, setup_logger


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


def test_setup_logger_with_env_var(mock_env_vars: Dict[str, str]) -> None:
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
