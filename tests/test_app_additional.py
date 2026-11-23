"""
app.py のエントリポイントテスト
"""

import runpy
from unittest.mock import patch, MagicMock

def test_app_run_as_script():
    """app.py をスクリプトとして実行した場合のテスト"""
    with patch("bot.discord_bot.SpheneBot") as mock_bot_cls:
        mock_bot = MagicMock()
        mock_bot_cls.return_value = mock_bot
        
        runpy.run_path("app.py", run_name="__main__")
        
        mock_bot_cls.assert_called_once()
        mock_bot.run.assert_called_once()


def test_main_warns_deprecated_env_vars():
    """起動時に廃止済みの環境変数を警告すること"""
    import app

    with patch("app.SpheneBot") as mock_bot_cls, \
         patch("app.config.find_deprecated_env_vars",
               return_value=[("MEMORY_ENABLED", "LIVING_MEMORY_ENABLED に統合されました")]), \
         patch("app.logger") as mock_logger:
        app.main()

    mock_logger.warning.assert_called_once()
    assert "MEMORY_ENABLED" in mock_logger.warning.call_args[0][0]
    mock_bot_cls.return_value.run.assert_called_once()
