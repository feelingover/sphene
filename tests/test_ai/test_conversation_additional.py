"""
ai/conversation.py の追加テスト
"""

import asyncio
from unittest.mock import MagicMock, patch
import pytest
import requests
from google.genai import types
from ai.conversation import (
    Sphene,
    generate_proactive_message,
    _load_prompt_from_local,
    MAX_IMAGE_BYTES,
    MAX_CONVERSATION_TURNS,
)

@pytest.mark.asyncio
async def test_async_input_message():
    """async_input_message のテスト"""
    sphene = Sphene("System")
    
    with patch("ai.conversation._call_genai_with_tools") as mock_call:
        mock_call.return_value = (True, "Async response", [])
        
        result = await sphene.async_input_message("Hello")
        
        assert result == "Async response"
        mock_call.assert_called_once()

def test_generate_proactive_message_success():
    """generate_proactive_message の成功テスト"""
    with (
        patch("ai.conversation._get_genai_client") as mock_client_fn,
        patch("ai.conversation.get_model_name", return_value="test-model"),
        patch("ai.conversation.load_system_prompt", return_value="System"),
    ):
        
        mock_part = MagicMock()
        mock_part.text = "そういえば、最近どう？"
        
        mock_content = MagicMock()
        mock_content.parts = [mock_part]
        
        mock_candidate = MagicMock()
        mock_candidate.content = mock_content
        
        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]
        
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_client_fn.return_value = mock_client
        
        result = generate_proactive_message("最近の話題", channel_context="User: Hello")
        
        assert result == "そういえば、最近どう？"

def test_generate_proactive_message_error():
    """generate_proactive_message のエラーテスト"""
    with patch("ai.conversation._get_genai_client") as mock_client_fn:
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("API error")
        mock_client_fn.return_value = mock_client
        
        result = generate_proactive_message("Fact")
        assert result is None

def test_load_prompt_from_local_fail_on_error():
    """_load_prompt_from_local の fail_on_error=True のテスト"""
    with patch("pathlib.Path.read_text", side_effect=Exception("Read error")):
        with pytest.raises(RuntimeError, match="システムプロンプトの読み込みに失敗しました"):
            _load_prompt_from_local(fail_on_error=True)

class TestInputMessageImageErrors:
    """input_message での画像処理エラーのテスト"""

    def setup_method(self):
        self.sphene = Sphene("System")

    @patch("ai.conversation._call_genai_with_tools")
    @patch("ai.conversation.requests.get")
    def test_image_http_error(self, mock_get, mock_call):
        """HTTPエラー発生時"""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("404 Not Found")
        mock_resp.__enter__.return_value = mock_resp
        mock_get.return_value = mock_resp
        
        mock_call.return_value = (True, "Response", [])
        
        result = self.sphene.input_message("Check this", image_urls=["https://cdn.discordapp.com/image.jpg"])
        
        assert result == "Response"
        call_kwargs = mock_call.call_args[1]
        assert len(call_kwargs["contents"][0].parts) == 1

    @patch("ai.conversation._call_genai_with_tools")
    @patch("ai.conversation.requests.get")
    def test_image_invalid_content_type(self, mock_get, mock_call):
        """画像以外のContent-Type"""
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.__enter__.return_value = mock_resp
        mock_get.return_value = mock_resp
        
        mock_call.return_value = (True, "Response", [])
        
        self.sphene.input_message("Check this", image_urls=["https://cdn.discordapp.com/image.jpg"])
        
        call_kwargs = mock_call.call_args[1]
        assert len(call_kwargs["contents"][0].parts) == 1

    @patch("ai.conversation._call_genai_with_tools")
    @patch("ai.conversation.requests.get")
    def test_image_oversized_header(self, mock_get, mock_call):
        """ヘッダーでサイズ超過を検知"""
        mock_resp = MagicMock()
        mock_resp.headers = {
            "Content-Type": "image/jpeg",
            "Content-Length": str(MAX_IMAGE_BYTES + 1)
        }
        mock_resp.__enter__.return_value = mock_resp
        mock_get.return_value = mock_resp
        
        mock_call.return_value = (True, "Response", [])
        
        self.sphene.input_message("Check this", image_urls=["https://cdn.discordapp.com/image.jpg"])
        
        call_kwargs = mock_call.call_args[1]
        assert len(call_kwargs["contents"][0].parts) == 1

    @patch("ai.conversation._call_genai_with_tools")
    @patch("ai.conversation.requests.get")
    def test_image_oversized_streaming(self, mock_get, mock_call):
        """ストリーミング中にサイズ超過を検知"""
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "image/jpeg"}
        mock_resp.iter_content.return_value = [b"a" * (MAX_IMAGE_BYTES + 1)]
        mock_resp.__enter__.return_value = mock_resp
        mock_get.return_value = mock_resp
        
        mock_call.return_value = (True, "Response", [])
        
        self.sphene.input_message("Check this", image_urls=["https://cdn.discordapp.com/image.jpg"])
        
        call_kwargs = mock_call.call_args[1]
        assert len(call_kwargs["contents"][0].parts) == 1

def test_sphene_trim_history_find_user_message():
    """trim_conversation_history で最初のメッセージが user になるように調整されることをテスト"""
    sphene = Sphene("System")
    
    history = []
    for i in range(MAX_CONVERSATION_TURNS * 2 + 5):
        role = "model"
        if i == MAX_CONVERSATION_TURNS * 2 + 2: 
            role = "user"
        history.append(types.Content(role=role, parts=[types.Part.from_text(text=f"msg {i}")]))
    
    sphene.history = history
    sphene.trim_conversation_history()
    
    assert sphene.history[0].role == "user"
    assert "msg 22" in sphene.history[0].parts[0].text
