# 定数の定義
PREVIEW_LENGTH = 30  # プレビュー表示時の文字数上限


def truncate_text(text: str, max_length: int = PREVIEW_LENGTH) -> str:
    """テキストを指定された長さに切り詰めて表示用のプレビューを作成する

    Args:
        text: 元のテキスト
        max_length: 最大長さ

    Returns:
        str: 切り詰められたテキスト（長い場合は...付き）
    """
    if not text:
        return ""
    return text[:max_length] + "..." if len(text) > max_length else text
