"""utils/text_utils.pyのテスト"""

from unittest.mock import MagicMock, patch

import pytest

from utils.text_utils import (
    PREVIEW_LENGTH,
    translate_to_english,
    translate_to_japanese,
    truncate_text,
)


def test_truncate_text_short_text() -> None:
    """短いテキストは切り詰めされないこと"""
    text = "短いテキスト"
    result = truncate_text(text)
    assert result == text
    assert "..." not in result


def test_truncate_text_long_text() -> None:
    """長いテキストは切り詰めて...が付くこと"""
    # デフォルトの長さ（PREVIEW_LENGTH）より長いテキスト
    long_text = "あ" * (PREVIEW_LENGTH + 10)
    result = truncate_text(long_text)
    assert len(result) == PREVIEW_LENGTH + 3  # 切り詰め + "..." の長さ
    assert result.endswith("...")
    assert result.startswith(long_text[:PREVIEW_LENGTH])


def test_truncate_text_exact_length() -> None:
    """ちょうどの長さのテキストは切り詰めされないこと"""
    text = "あ" * PREVIEW_LENGTH
    result = truncate_text(text)
    assert result == text
    assert "..." not in result


def test_truncate_text_empty() -> None:
    """空文字列は空のまま返されること"""
    assert truncate_text("") == ""


def test_truncate_text_custom_length() -> None:
    """カスタム長さでの切り詰めが機能すること"""
    text = "これはカスタム長さでのテストです"
    custom_length = 5
    result = truncate_text(text, custom_length)
    assert len(result) == custom_length + 3  # カスタム長さ + "..." の長さ
    assert result == f"{text[:custom_length]}..."


def test_truncate_text_none() -> None:
    """None値が渡された場合は空文字列を返すこと"""
    # mypy対策でここではNoneを直接渡さない
    none_text: str = None  # type: ignore
    result = truncate_text(none_text)
    assert result == ""


@pytest.mark.asyncio
@patch("utils.text_utils.get_model_name")
@patch("utils.text_utils._get_genai_client")
async def test_translate_to_english_success(
    mock_get_client: MagicMock, mock_model_name: MagicMock
) -> None:
    """英語翻訳が成功するケース"""
    mock_model_name.return_value = "gemini-2.5-flash"

    mock_response = MagicMock()
    mock_response.text = "This is a translation test."
    mock_get_client.return_value.models.generate_content.return_value = mock_response

    result = await translate_to_english("これは翻訳テストです")

    assert result == "This is a translation test."
    mock_get_client.return_value.models.generate_content.assert_called_once()


@pytest.mark.asyncio
@patch("utils.text_utils.get_model_name")
@patch("utils.text_utils._get_genai_client")
async def test_translate_to_english_error(
    mock_get_client: MagicMock, mock_model_name: MagicMock
) -> None:
    """英語翻訳中にエラーが発生するケース"""
    mock_model_name.return_value = "gemini-2.5-flash"
    mock_get_client.return_value.models.generate_content.side_effect = Exception(
        "API error"
    )

    result = await translate_to_english("エラーになるテキスト")

    assert result is None


@pytest.mark.asyncio
@patch("utils.text_utils.get_model_name")
@patch("utils.text_utils._get_genai_client")
async def test_translate_to_japanese_success(
    mock_get_client: MagicMock, mock_model_name: MagicMock
) -> None:
    """日本語翻訳が成功するケース"""
    mock_model_name.return_value = "gemini-2.5-flash"

    mock_response = MagicMock()
    mock_response.text = "これは翻訳されたテキストです。"
    mock_get_client.return_value.models.generate_content.return_value = mock_response

    result = await translate_to_japanese("This is a test for translation.")

    assert result == "これは翻訳されたテキストです。"
    mock_get_client.return_value.models.generate_content.assert_called_once()


@pytest.mark.asyncio
@patch("utils.text_utils.get_model_name")
@patch("utils.text_utils._get_genai_client")
async def test_translate_to_japanese_error(
    mock_get_client: MagicMock, mock_model_name: MagicMock
) -> None:
    """日本語翻訳中にエラーが発生するケース"""
    mock_model_name.return_value = "gemini-2.5-flash"
    mock_get_client.return_value.models.generate_content.side_effect = Exception(
        "API error"
    )

    result = await translate_to_japanese("Error causing text")

    assert result is None


def test_split_message_short() -> None:
    """短いメッセージは分割されないこと"""
    from utils.text_utils import split_message

    text = "Short message"
    chunks = split_message(text)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_split_message_long() -> None:
    """長いメッセージは指定長で分割されること"""
    from utils.text_utils import split_message

    # max_length=10 for easy testing
    text = "123456789012345"
    chunks = split_message(text, max_length=10)
    assert len(chunks) == 2
    assert chunks[0] == "1234567890"
    assert chunks[1] == "12345"


def test_split_message_with_newlines() -> None:
    """改行がある場合は改行で分割されること"""
    from utils.text_utils import split_message

    text = "Line 1\nLine 2\nLine 3"
    # "Line 1" is 6 chars. + newline = 7.
    # max_length=10. It should include "Line 1".
    chunks = split_message(text, max_length=10)
    # Expected behavior:
    # 1. "Line 1" (len 6) found \n at 6.
    # 2. "Line 2" (len 6) found \n at 6.
    # 3. "Line 3"
    assert len(chunks) == 3
    assert chunks[0] == "Line 1"
    assert chunks[1] == "Line 2"
    assert chunks[2] == "Line 3"


def test_split_message_long_no_newlines() -> None:
    """改行がない長いメッセージは強制分割されること"""
    from utils.text_utils import split_message

    text = "a" * 25
    chunks = split_message(text, max_length=10)
    assert len(chunks) == 3
    assert chunks[0] == "a" * 10
    assert chunks[1] == "a" * 10
    assert chunks[2] == "a" * 5
