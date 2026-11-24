"""インタラクションモックのヘルパー"""

from unittest.mock import AsyncMock, MagicMock


def attach_response_state(interaction: MagicMock) -> MagicMock:
    """応答済み状態 (is_done) を再現する response / followup をモックに付ける

    Discord と同様に、defer() / send_message() / edit_message() の後は is_done() が True になり、
    以降の送信は followup.send で行われる。

    Args:
        interaction: インタラクションのモック

    Returns:
        同じモック（呼び出しを連結できるよう返す）
    """
    state = {"done": False}

    def _mark_done(*_args: object, **_kwargs: object) -> None:
        state["done"] = True

    interaction.response.is_done = MagicMock(side_effect=lambda: state["done"])
    interaction.response.defer = AsyncMock(side_effect=_mark_done)
    interaction.response.send_message = AsyncMock(side_effect=_mark_done)
    interaction.response.edit_message = AsyncMock(side_effect=_mark_done)
    interaction.followup.send = AsyncMock()
    return interaction
