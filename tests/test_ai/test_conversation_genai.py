"""ai/conversation.py のgoogle-genai向けテスト"""

from unittest.mock import MagicMock, patch

from google.genai import types

from ai.conversation import MAX_IMAGE_BYTES, Sphene

DISCORD_CDN_URL = "https://cdn.discordapp.com/attachments/123/456/img.jpg"
DISCORD_MEDIA_URL = "https://media.discordapp.net/attachments/123/456/img.jpg"


def _make_response_mock(**kwargs):
    """stream=True + with文対応のレスポンスモックを生成"""
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.headers = kwargs.get("headers", {})
    resp.iter_content.return_value = kwargs.get("chunks", [])
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_input_message_skips_oversize_image() -> None:
    """サイズ超過の画像はスキップされることを確認"""
    sphene = Sphene(system_setting="System")

    with patch("ai.conversation._call_genai_with_tools") as mock_call, patch(
        "requests.get"
    ) as mock_get, patch("ai.conversation.types.Part.from_bytes") as mock_from_bytes:
        mock_get.return_value = _make_response_mock(
            headers={
                "Content-Type": "image/jpeg",
                "Content-Length": str(MAX_IMAGE_BYTES + 1),
            },
            chunks=[b"x" * 10],
        )

        mock_call.return_value = (True, "ok", [])

        result = sphene.input_message("hi", [DISCORD_CDN_URL])

        assert result == "ok"
        mock_get.assert_called_once()
        mock_from_bytes.assert_not_called()


def test_input_message_skips_non_image_content_type() -> None:
    """画像以外のContent-Typeはスキップされることを確認"""
    sphene = Sphene(system_setting="System")

    with patch("ai.conversation._call_genai_with_tools") as mock_call, patch(
        "requests.get"
    ) as mock_get, patch("ai.conversation.types.Part.from_bytes") as mock_from_bytes:
        mock_get.return_value = _make_response_mock(
            headers={"Content-Type": "text/plain"},
            chunks=[b"not-an-image"],
        )

        mock_call.return_value = (True, "ok", [])

        result = sphene.input_message("hi", [DISCORD_CDN_URL])

        assert result == "ok"
        mock_get.assert_called_once()
        mock_from_bytes.assert_not_called()


def test_input_message_skips_streaming_overflow_without_length() -> None:
    """Content-Lengthが無くても上限超過ならスキップされることを確認"""
    sphene = Sphene(system_setting="System")

    with patch("ai.conversation._call_genai_with_tools") as mock_call, patch(
        "requests.get"
    ) as mock_get, patch("ai.conversation.types.Part.from_bytes") as mock_from_bytes:
        big_chunk = b"x" * (MAX_IMAGE_BYTES + 1)
        mock_get.return_value = _make_response_mock(
            headers={"Content-Type": "image/jpeg"},
            chunks=[big_chunk],
        )

        mock_call.return_value = (True, "ok", [])

        result = sphene.input_message("hi", [DISCORD_CDN_URL])

        assert result == "ok"
        mock_get.assert_called_once()
        mock_from_bytes.assert_not_called()


def test_input_message_skips_disallowed_domain() -> None:
    """許可されていないドメインの画像URLはフェッチされないことを確認"""
    sphene = Sphene(system_setting="System")

    with patch("ai.conversation._call_genai_with_tools") as mock_call, patch(
        "requests.get"
    ) as mock_get, patch("ai.conversation.types.Part.from_bytes") as mock_from_bytes:
        mock_call.return_value = (True, "ok", [])

        result = sphene.input_message("hi", ["https://evil.example.com/img.jpg"])

        assert result == "ok"
        mock_get.assert_not_called()
        mock_from_bytes.assert_not_called()


def test_input_message_allows_discord_media_domain() -> None:
    """media.discordapp.netドメインの画像は取得されることを確認"""
    sphene = Sphene(system_setting="System")

    fake_part = types.Part.from_bytes(data=b"fake", mime_type="image/png")

    with patch("ai.conversation._call_genai_with_tools") as mock_call, patch(
        "requests.get"
    ) as mock_get, patch(
        "ai.conversation.types.Part.from_bytes", return_value=fake_part
    ) as mock_from_bytes:
        mock_get.return_value = _make_response_mock(
            headers={"Content-Type": "image/png"},
            chunks=[b"fake-image-data"],
        )

        mock_call.return_value = (True, "ok", [])

        result = sphene.input_message("hi", [DISCORD_MEDIA_URL])

        assert result == "ok"
        mock_get.assert_called_once()
        mock_from_bytes.assert_called_once()


def test_input_message_handles_invalid_content_length() -> None:
    """不正なContent-Lengthヘッダーでもクラッシュしないことを確認"""
    sphene = Sphene(system_setting="System")

    fake_part = types.Part.from_bytes(data=b"fake", mime_type="image/jpeg")

    with patch("ai.conversation._call_genai_with_tools") as mock_call, patch(
        "requests.get"
    ) as mock_get, patch(
        "ai.conversation.types.Part.from_bytes", return_value=fake_part
    ) as mock_from_bytes:
        mock_get.return_value = _make_response_mock(
            headers={
                "Content-Type": "image/jpeg",
                "Content-Length": "invalid",
            },
            chunks=[b"small-image"],
        )

        mock_call.return_value = (True, "ok", [])

        result = sphene.input_message("hi", [DISCORD_CDN_URL])

        assert result == "ok"
        # Content-Lengthが不正でもクラッシュせず、ストリーミングで読み込まれる
        mock_from_bytes.assert_called_once()
