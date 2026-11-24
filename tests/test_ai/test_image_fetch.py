"""画像取得（_fetch_image_part）のテスト: https 限定・リダイレクト禁止・URL マスク・mime 整形"""

from unittest.mock import MagicMock, patch

import pytest

from ai.conversation import _fetch_image_part, _redact_url

SIGNED_URL = "https://cdn.discordapp.com/attachments/1/2/a.png?ex=abc&is=def&hm=secret"


def _response(content_type: str = "image/png", body: bytes = b"img", is_redirect: bool = False):
    resp = MagicMock()
    resp.is_redirect = is_redirect
    resp.status_code = 302 if is_redirect else 200
    resp.headers = {"Content-Type": content_type}
    resp.iter_content.return_value = [body]
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


class TestRedactUrl:
    def test_removes_query_and_fragment(self):
        assert _redact_url(SIGNED_URL + "#frag") == "https://cdn.discordapp.com/attachments/1/2/a.png"


class TestFetchImagePart:
    def test_http_is_rejected(self):
        with patch("ai.conversation.requests.get") as get:
            assert _fetch_image_part("http://cdn.discordapp.com/a.png") is None
        get.assert_not_called()

    def test_redirects_are_not_followed(self):
        with patch("ai.conversation.requests.get", return_value=_response(is_redirect=True)) as get:
            assert _fetch_image_part(SIGNED_URL) is None
        assert get.call_args.kwargs["allow_redirects"] is False

    def test_mime_type_parameters_are_stripped(self):
        with (
            patch("ai.conversation.requests.get", return_value=_response("Image/PNG; charset=binary")),
            patch("ai.conversation.types.Part.from_bytes") as from_bytes,
        ):
            assert _fetch_image_part(SIGNED_URL) is from_bytes.return_value
        from_bytes.assert_called_once_with(data=b"img", mime_type="image/png")

    def test_error_log_hides_signed_query(self):
        with (
            patch("ai.conversation.requests.get", side_effect=RuntimeError(SIGNED_URL)),
            patch("ai.conversation.logger") as logger,
        ):
            assert _fetch_image_part(SIGNED_URL) is None
        message = logger.error.call_args.args[0]
        assert "hm=secret" not in message
        assert logger.error.call_args.kwargs["exc_info"] is True

    @pytest.mark.parametrize("url", ["https://evil.example.com/a.png", "https://cdn.discordapp.com.evil/a.png"])
    def test_disallowed_host_log_hides_query(self, url):
        with patch("ai.conversation.logger") as logger:
            assert _fetch_image_part(url + "?hm=secret") is None
        assert "hm=secret" not in logger.warning.call_args.args[0]
