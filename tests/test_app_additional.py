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
