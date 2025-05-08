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
@patch("utils.text_utils.aiclient")
async def test_translate_to_english_success(mock_aiclient: MagicMock) -> None:
    """英語翻訳が成功するケース"""
    # aiクライアントのモック設定
    mock_completion = MagicMock()
    mock_completion.choices[0].message.content = "This is a translation test."
    mock_aiclient.chat.completions.create.return_value = mock_completion

    # 関数実行
    result = await translate_to_english("これは翻訳テストです")

    # アサーション
    assert result == "This is a translation test."
    mock_aiclient.chat.completions.create.assert_called_once()


@pytest.mark.asyncio
@patch("utils.text_utils.aiclient")
async def test_translate_to_english_error(mock_aiclient: MagicMock) -> None:
    """英語翻訳中にエラーが発生するケース"""
    # aiクライアントのモック設定
    mock_aiclient.chat.completions.create.side_effect = Exception("API error")

    # 関数実行
    result = await translate_to_english("エラーになるテキスト")

    # アサーション
    assert result is None


@pytest.mark.asyncio
@patch("utils.text_utils.aiclient")
async def test_translate_to_japanese_success(mock_aiclient: MagicMock) -> None:
    """日本語翻訳が成功するケース"""
    # aiクライアントのモック設定
    mock_completion = MagicMock()
    mock_completion.choices[0].message.content = "これは翻訳されたテキストです。"
    mock_aiclient.chat.completions.create.return_value = mock_completion

    # 関数実行
    result = await translate_to_japanese("This is a test for translation.")

    # アサーション
    assert result == "これは翻訳されたテキストです。"
    mock_aiclient.chat.completions.create.assert_called_once()


@pytest.mark.asyncio
@patch("utils.text_utils.aiclient")
async def test_translate_to_japanese_error(mock_aiclient: MagicMock) -> None:
    """日本語翻訳中にエラーが発生するケース"""
    # aiクライアントのモック設定
    mock_aiclient.chat.completions.create.side_effect = Exception("API error")

    # 関数実行
    result = await translate_to_japanese("Error causing text")

    # アサーション
    assert result is None
