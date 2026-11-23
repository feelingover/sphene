"""ai/api.py のリトライ判定・エラーハンドリングのテスト"""

from unittest.mock import MagicMock

import httpx
import pytest
from google.api_core import exceptions as google_exceptions
from google.genai import errors as genai_errors

from ai.api import _handle_api_error, _should_retry_api_error


def _api_error(code: int) -> genai_errors.APIError:
    return genai_errors.APIError(code, {"error": {"message": "x", "status": "X"}})


class TestShouldRetryApiError:
    """_should_retry_api_error のテスト"""

    @pytest.mark.parametrize("code", [408, 429, 500, 502, 503, 504])
    def test_retries_transient_status_codes(self, code: int) -> None:
        """一時的なステータスコードはリトライすること"""
        assert _should_retry_api_error(_api_error(code)) is True

    @pytest.mark.parametrize("code", [400, 401, 403, 404])
    def test_does_not_retry_client_errors(self, code: int) -> None:
        """クライアントエラーはリトライしないこと"""
        assert _should_retry_api_error(_api_error(code)) is False

    @pytest.mark.parametrize(
        "exc",
        [
            httpx.ReadTimeout("timeout"),
            httpx.ConnectError("refused"),
            httpx.RemoteProtocolError("closed"),
            ConnectionResetError("reset"),
            TimeoutError("timeout"),
        ],
    )
    def test_retries_network_errors(self, exc: BaseException) -> None:
        """タイムアウト・接続断などのネットワークエラーはリトライすること"""
        assert _should_retry_api_error(exc) is True

    def test_retries_google_api_core_errors(self) -> None:
        """google.api_core の一時的エラーはリトライすること"""
        assert _should_retry_api_error(google_exceptions.ServiceUnavailable("x")) is True
        assert _should_retry_api_error(google_exceptions.DeadlineExceeded("x")) is True

    def test_does_not_retry_by_message_substring(self) -> None:
        """メッセージに "500" 等を含むだけの例外はリトライしないこと"""
        assert _should_retry_api_error(ValueError("max 5000 tokens exceeded")) is False
        assert _should_retry_api_error(RuntimeError("HTTP 503 in message only")) is False


class TestHandleApiErrorTimeout:
    """_handle_api_error のタイムアウト時の文言テスト"""

    def test_timeout_returns_busy_message(self) -> None:
        """タイムアウト時は内部詳細を含まない専用の文言を返すこと"""
        message = _handle_api_error(httpx.ReadTimeout("secret-endpoint timed out"))
        assert "時間内に返事が来なかった" in message
        assert "secret-endpoint" not in message

    def test_other_errors_return_generic_message(self) -> None:
        """その他のエラーは汎用の文言を返すこと"""
        message = _handle_api_error(MagicMock(spec=Exception))
        assert "エラーが発生" in message
