"""
ai/conversation.py の広範なテスト
"""

# type: ignore
# mypy: ignore-errors

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from google.genai import types, errors as genai_errors
from google.api_core import exceptions as google_exceptions

from ai.api import _flatten_function_parts
from ai.conversation import (
    Sphene,
    _call_genai_with_tools,
    _execute_tool_calls,
    _handle_api_error,
    cleanup_expired_conversations,
    load_system_prompt,
    channel_conversations,
    _prompt_cache,
)


class TestConversationExtensive:
    """Spheneクラスと関連機能の広範なテスト"""

    def setup_method(self):
        """テストごとのセットアップ"""
        _prompt_cache.clear()
        channel_conversations.clear()

    @patch("ai.conversation._load_prompt_from_local")
    def test_load_system_prompt_cache(self, mock_load_local):
        """システムプロンプトのキャッシュ動作テスト"""
        mock_load_local.return_value = "Custom Prompt"

        # 1回目：ロードされる
        p1 = load_system_prompt()
        assert p1 == "Custom Prompt"
        assert mock_load_local.call_count == 1

        # 2回目：キャッシュから返される
        p2 = load_system_prompt()
        assert p2 == "Custom Prompt"
        assert mock_load_local.call_count == 1

        # 強制リロード
        p3 = load_system_prompt(force_reload=True)
        assert p3 == "Custom Prompt"
        assert mock_load_local.call_count == 2

    def test_trim_conversation_history_safety(self):
        """トリミング時の安全な切断ポイントのテスト"""
        sphene = Sphene("System")

        # 往復上限を超えるメッセージを追加
        for i in range(30):
            content = MagicMock()
            content.role = "user" if i % 2 == 0 else "model"
            sphene.history.append(content)

        sphene.trim_conversation_history()

        # MAX_CONVERSATION_TURNS * 2 以下であること
        assert len(sphene.history) <= 20
        # 先頭がuserメッセージであること
        assert sphene.history[0].role == "user"

    def test_handle_api_error_mapping(self):
        """APIエラーハンドリングのマッピングテスト"""
        errors = [
            (genai_errors.APIError(code=404, response_json={}), "AIモデル"),
            (google_exceptions.NotFound("not found"), "AIモデル"),
            (genai_errors.APIError(code=429, response_json={}), "混み合ってる"),
            (google_exceptions.TooManyRequests("rate limited"), "混み合ってる"),
            (Exception("General Error"), "通信中にエラー"),
        ]

        for err, expected_part in errors:
            msg = _handle_api_error(err)
            assert expected_part in msg

    @patch("ai.api.TOOL_FUNCTIONS")
    def test_execute_tool_calls_success(self, mock_tools):
        """ツール呼び出し実行の成功テスト"""
        mock_func = MagicMock(return_value={"result": "success"})
        mock_tools.get.return_value = mock_func

        mock_call = MagicMock()
        mock_call.name = "test_tool"
        mock_call.args = {"arg": "val"}

        results = _execute_tool_calls([mock_call])

        assert len(results) == 1
        mock_func.assert_called_once_with(arg="val")

    @patch("ai.api.TOOL_FUNCTIONS")
    def test_execute_tool_calls_unknown_function(self, mock_tools):
        """未知のツール関数の呼び出しテスト"""
        mock_tools.get.return_value = None

        mock_call = MagicMock()
        mock_call.name = "unknown_tool"
        mock_call.args = {}

        results = _execute_tool_calls([mock_call])

        assert len(results) == 1
        # エラーは発生せず、結果が返される

    @patch("ai.api.TOOL_FUNCTIONS")
    def test_execute_tool_calls_function_error(self, mock_tools):
        """ツール関数がエラーを投げた場合のテスト"""
        mock_func = MagicMock(side_effect=Exception("ツール内部エラー"))
        mock_tools.get.return_value = mock_func

        mock_call = MagicMock()
        mock_call.name = "error_tool"
        mock_call.args = {"key": "value"}

        results = _execute_tool_calls([mock_call])

        assert len(results) == 1
        # エラーは捕捉されて結果が返される

    @patch("ai.api.get_model_name")
    @patch("ai.api._get_genai_client")
    def test_call_genai_with_tools_max_rounds(
        self, mock_get_client, mock_model_name
    ):
        """ツール呼び出しの無限ループ防止テスト"""
        mock_model_name.return_value = "gemini-4-hydrogen"

        # 常にfunction_callを返すレスポンスを作成
        mock_fc = MagicMock()
        mock_fc.name = "loop_tool"
        mock_fc.args = {}

        mock_part = MagicMock()
        mock_part.function_call = mock_fc
        mock_part.text = None

        mock_content = MagicMock()
        mock_content.parts = [mock_part]

        mock_response = MagicMock()
        mock_response.candidates = [MagicMock(content=mock_content)]
        mock_get_client.return_value.models.generate_content.return_value = (
            mock_response
        )

        # 実際のtypes.Partオブジェクトを使う（pydanticバリデーション対策）
        fn_response_part = types.Part.from_function_response(
            name="loop_tool", response={"result": "ok"}
        )
        with patch(
            "ai.api._execute_tool_calls",
            return_value=[fn_response_part],
        ):
            success, msg, _ = _call_genai_with_tools([], "system")

        assert success is False
        assert "複雑すぎて" in msg

    @patch("ai.api.MAX_TOOL_CALL_ROUNDS", 1)
    @patch("ai.api.get_model_name")
    @patch("ai.api._get_genai_client")
    def test_call_genai_with_tools_final_call_without_tools(
        self, mock_get_client, mock_model_name
    ):
        """ツール呼び出しラウンド上限到達後、ツールなし最終コールでテキスト応答を返すテスト"""
        mock_model_name.return_value = "gemini-4-hydrogen"

        # ツール呼び出しを返すレスポンス
        mock_fc = MagicMock()
        mock_fc.name = "search_item"
        mock_fc.args = {"query": "test"}

        mock_tool_part = MagicMock()
        mock_tool_part.function_call = mock_fc
        mock_tool_part.text = None

        mock_tool_content = MagicMock()
        mock_tool_content.parts = [mock_tool_part]

        mock_tool_response = MagicMock()
        mock_tool_response.candidates = [MagicMock(content=mock_tool_content)]

        # テキスト応答を返すレスポンス（最終コール用）
        mock_text_part = MagicMock()
        mock_text_part.function_call = None
        mock_text_part.text = "調べた結果をまとめるね！"

        mock_text_content = MagicMock()
        mock_text_content.parts = [mock_text_part]

        mock_text_response = MagicMock()
        mock_text_response.candidates = [MagicMock(content=mock_text_content)]

        # MAX_TOOL_CALL_ROUNDS=1 → ループ2回 + 最終コール1回 = 3回
        mock_client = mock_get_client.return_value
        mock_client.models.generate_content.side_effect = [
            mock_tool_response,  # ラウンド1: ツール呼び出し
            mock_tool_response,  # ラウンド2: ツール呼び出し（ループ上限）
            mock_text_response,  # 最終コール: テキスト応答
        ]

        fn_response_part = types.Part.from_function_response(
            name="search_item", response={"result": "ok"}
        )
        with patch(
            "ai.api._execute_tool_calls",
            return_value=[fn_response_part],
        ):
            success, msg, _ = _call_genai_with_tools([], "system")

        assert success is True
        assert msg == "調べた結果をまとめるね！"
        assert mock_client.models.generate_content.call_count == 3

    @patch("ai.api.MAX_TOOL_CALL_ROUNDS", 1)
    @patch("ai.api.get_model_name")
    @patch("ai.api._get_genai_client")
    def test_call_genai_with_tools_final_call_api_error(
        self, mock_get_client, mock_model_name
    ):
        """ツールなし最終コールでAPI例外が発生した場合のテスト"""
        mock_model_name.return_value = "gemini-4-hydrogen"

        # ツール呼び出しを返すレスポンス
        mock_fc = MagicMock()
        mock_fc.name = "search_item"
        mock_fc.args = {}

        mock_part = MagicMock()
        mock_part.function_call = mock_fc
        mock_part.text = None

        mock_content = MagicMock()
        mock_content.parts = [mock_part]

        mock_tool_response = MagicMock()
        mock_tool_response.candidates = [MagicMock(content=mock_content)]

        # MAX_TOOL_CALL_ROUNDS=1 → ループ2回 + 最終コール(例外)
        # @retry(stop_after_attempt(5)) なので、最終コールで5回失敗させる
        api_error = genai_errors.APIError(code=429, response_json={"error": "rate limited"})
        mock_client = mock_get_client.return_value
        mock_client.models.generate_content.side_effect = [
            mock_tool_response,  # ラウンド1: ツール呼び出し
            mock_tool_response,  # ラウンド2: ツール呼び出し（ループ上限）
            api_error,  # 最終コール：試行1
            api_error,  # 最終コール：試行2
            api_error,  # 最終コール：試行3
            api_error,  # 最終コール：試行4
            api_error,  # 最終コール：試行5（ここで終了）
        ]

        # tenacityのsleepをスキップして高速化
        with patch("time.sleep", return_value=None):
            fn_response_part = types.Part.from_function_response(
                name="search_item", response={"result": "ok"}
            )
            with patch(
                "ai.api._execute_tool_calls",
                return_value=[fn_response_part],
            ):
                success, msg, _ = _call_genai_with_tools([], "system")

        assert success is False
        assert "混み合ってる" in msg

    def test_cleanup_expired_conversations(self):
        """期限切れ会話のクリーンアップテスト"""
        # 有効な会話
        s1 = Sphene("S1")
        channel_conversations["u1"] = s1

        # 期限切れの会話
        s2 = Sphene("S2")
        s2.last_interaction = datetime.now() - timedelta(hours=1)
        channel_conversations["u2"] = s2

        count = cleanup_expired_conversations()
        assert count == 1
        assert "u1" in channel_conversations
        assert "u2" not in channel_conversations

    @patch("ai.api.get_model_name")
    @patch("ai.api._get_genai_client")
    def test_call_genai_with_tools_text_response(
        self, mock_get_client, mock_model_name
    ):
        """テキスト応答の正常処理テスト"""
        mock_model_name.return_value = "gemini-4-hydrogen"

        # テキスト応答のみを返すレスポンス
        mock_part = MagicMock()
        mock_part.function_call = None
        mock_part.text = "Hello from GenAI"

        mock_content = MagicMock()
        mock_content.parts = [mock_part]

        mock_response = MagicMock()
        mock_response.candidates = [MagicMock(content=mock_content)]
        mock_get_client.return_value.models.generate_content.return_value = (
            mock_response
        )

        success, text, history = _call_genai_with_tools([], "system")

        assert success is True
        assert text == "Hello from GenAI"

    @patch("ai.api.get_model_name")
    @patch("ai.api._get_genai_client")
    def test_call_genai_with_tools_empty_candidates(
        self, mock_get_client, mock_model_name
    ):
        """空のcandidatesが返された場合のテスト"""
        mock_model_name.return_value = "gemini-4-hydrogen"

        mock_response = MagicMock()
        mock_response.candidates = []
        mock_get_client.return_value.models.generate_content.return_value = (
            mock_response
        )

        success, text, _ = _call_genai_with_tools([], "system")

        assert success is False
        assert "空" in text

    @patch("ai.api.get_model_name")
    @patch("ai.api._get_genai_client")
    def test_call_genai_with_grounding_config(
        self, mock_get_client, mock_model_name
    ):
        """tool_mode='grounding'の時に正しいツール構成でSDKが呼ばれるかテスト"""
        mock_model_name.return_value = "gemini-4-hydrogen"

        # モックの戻り値設定
        mock_response = MagicMock()
        mock_response.candidates = [MagicMock()]
        mock_response.candidates[0].content.parts = [types.Part.from_text(text="response")]
        mock_get_client.return_value.models.generate_content.return_value = mock_response

        _call_genai_with_tools([], "system_instruction", tool_mode="grounding")

        # generate_content の呼び出し引数を確認
        _, kwargs = mock_get_client.return_value.models.generate_content.call_args
        config = kwargs["config"]

        # toolsの中にgoogle_searchが含まれていること
        grounding_tools = [t for t in config.tools if hasattr(t, "google_search") and t.google_search]
        assert len(grounding_tools) == 1
        assert isinstance(grounding_tools[0].google_search, types.GoogleSearch)

    @patch("ai.conversation.detect_tool_mode", return_value="function_calling")
    @patch("ai.conversation._call_genai_with_tools")
    def test_input_message_includes_tool_instruction(self, mock_call, mock_router):
        """通常の会話入力時にツール使用指示が含まれているかテスト"""
        mock_call.return_value = (True, "Answer", [])
        sphene = Sphene("Base Prompt")

        sphene.input_message("Hello")

        # _call_genai_with_tools の引数を確認
        _, kwargs = mock_call.call_args
        instruction = kwargs["system_instruction"]
        assert "Base Prompt" in instruction
        assert "必ずツールを使って最新データを取得すること" in instruction

    @patch("ai.api.get_model_name")
    @patch("ai.api._get_genai_client")
    def test_call_genai_with_grounding_metadata(
        self, mock_get_client, mock_model_name
    ):
        """Groundingメタデータが含まれるレスポンスの処理テスト"""
        mock_model_name.return_value = "gemini-4-hydrogen"

        candidate = MagicMock()
        candidate.content.parts = [types.Part.from_text(text="grounded response")]
        candidate.grounding_metadata = MagicMock() # メタデータあり
        
        mock_response = MagicMock()
        mock_response.candidates = [candidate]
        mock_get_client.return_value.models.generate_content.return_value = mock_response

        success, text, _ = _call_genai_with_tools([], "system")

        assert success is True
        assert text == "grounded response"
        # ログ出力されるはず（副作用の検証は省略するが、クラッシュしないことが重要）


class TestUndeclaredFunctionCalls:
    """ツール未宣言モードでモデルがfunction_callを返した場合のテスト"""

    @staticmethod
    def _make_response(parts):
        mock_response = MagicMock()
        mock_response.candidates = [MagicMock(content=types.Content(role="model", parts=parts))]
        return mock_response

    @pytest.mark.parametrize("tool_mode", ["none", "grounding"])
    @patch("ai.api._execute_tool_calls")
    @patch("ai.api.get_model_name", return_value="gemini-4-hydrogen")
    @patch("ai.api._get_genai_client")
    def test_ignores_preamble_text_and_retries(
        self, mock_get_client, _model, mock_exec, tool_mode
    ):
        """function_callに添えられた前置きテキストは採用せず、再リクエストの応答を使う"""
        with_preamble = [
            types.Part.from_text(text="調べてみるね！"),
            types.Part.from_function_call(name="search_item", args={"category": "x"}),
        ]
        text_only = [types.Part.from_text(text="こんにちは")]
        generate = mock_get_client.return_value.models.generate_content
        generate.side_effect = [self._make_response(with_preamble), self._make_response(text_only)]

        success, text, history = _call_genai_with_tools([], "system", tool_mode=tool_mode)

        assert success is True
        assert text == "こんにちは"
        mock_exec.assert_not_called()
        assert generate.call_count == 2
        assert len(history) == 1
        assert history[0].parts[0].text == "こんにちは"
        assert all(p.function_call is None for p in history[0].parts)

    @patch("ai.api.MAX_TOOL_CALL_ROUNDS", 0)
    @patch("ai.api._execute_tool_calls")
    @patch("ai.api.get_model_name", return_value="gemini-4-hydrogen")
    @patch("ai.api._get_genai_client")
    def test_final_call_function_call_is_retried(self, mock_get_client, _model, mock_exec):
        """上限到達後の最終コールでfunction_callが返ったら、実行せずテキスト化した履歴で再リクエストする"""
        mock_exec.return_value = [
            types.Part.from_function_response(name="search_recipe", response={"r": 1})
        ]
        call_only = [types.Part.from_function_call(name="search_recipe", args={})]
        text_only = [types.Part.from_text(text="まとめたよ")]
        generate = mock_get_client.return_value.models.generate_content
        generate.side_effect = [
            self._make_response(call_only),  # ラウンド1: ツール呼び出し(実行される)
            self._make_response(call_only),  # 最終コール: 模倣されたfunction_call
            self._make_response(text_only),  # 再リクエスト
        ]
        contents = [types.Content(role="user", parts=[types.Part.from_text(text="User: 集計して")])]

        success, text, history = _call_genai_with_tools(contents, "system")

        assert success is True
        assert text == "まとめたよ"
        assert mock_exec.call_count == 1
        retry_contents = generate.call_args_list[2].kwargs["contents"]
        assert all(
            not p.function_call and not p.function_response
            for c in retry_contents
            for p in c.parts
        )
        # 集めたツール結果はテキストとして渡される
        retry_texts = [p.text for c in retry_contents for p in c.parts]
        assert any("search_recipe" in t and '"r": 1' in t for t in retry_texts)
        assert history[-1].parts[0].text == "まとめたよ"

    @patch("ai.api.MAX_TOOL_CALL_ROUNDS", 0)
    @patch("ai.api._execute_tool_calls")
    @patch("ai.api.get_model_name", return_value="gemini-4-hydrogen")
    @patch("ai.api._get_genai_client")
    def test_final_call_function_call_retry_fails(self, mock_get_client, _model, mock_exec):
        """最終コールの再リクエストでもテキストが無ければ「諦めた」メッセージを返す"""
        mock_exec.return_value = [
            types.Part.from_function_response(name="search_recipe", response={"r": 1})
        ]
        call_only = [types.Part.from_function_call(name="search_recipe", args={})]
        mock_get_client.return_value.models.generate_content.return_value = self._make_response(
            call_only
        )

        success, text, _ = _call_genai_with_tools([], "system")

        assert success is False
        assert "複雑すぎて" in text
        assert mock_exec.call_count == 1
        assert mock_get_client.return_value.models.generate_content.call_count == 3

    def test_flatten_converts_responses_and_merges_roles(self):
        """function_callは除去、function_responseはテキスト化し、同じroleの連続はまとめる"""
        contents = [
            types.Content(role="user", parts=[types.Part.from_text(text="User: 集計して")]),
            types.Content(
                role="model",
                parts=[types.Part.from_function_call(name="search_recipe", args={})],
            ),
            types.Content(
                role="user",
                parts=[
                    types.Part.from_function_response(
                        name="search_recipe", response={"素材": "ダークマター"}
                    )
                ],
            ),
            types.Content(
                role="model",
                parts=[
                    types.Part.from_text(text="調べるね"),
                    types.Part.from_function_call(name="search_item", args={}),
                ],
            ),
            types.Content(
                role="user",
                parts=[types.Part.from_function_response(name="search_item", response={})],
            ),
            types.Content(role="model", parts=[types.Part.from_text(text="結果だよ")]),
        ]

        flattened = _flatten_function_parts(contents)

        assert [c.role for c in flattened] == ["user", "model", "user", "model"]
        assert all(
            not p.function_call and not p.function_response for c in flattened for p in c.parts
        )
        # function_callだけのmodelが消え、ユーザー発言とツール結果がまとまる
        assert flattened[0].parts[0].text == "User: 集計して"
        assert "search_recipe" in flattened[0].parts[1].text
        assert "ダークマター" in flattened[0].parts[1].text
        assert [p.text for p in flattened[1].parts] == ["調べるね"]
        assert "search_item" in flattened[2].parts[0].text
        # 元の履歴は変更しない
        assert contents[1].parts[0].function_call is not None

    @patch("ai.api._execute_tool_calls")
    @patch("ai.api.get_model_name", return_value="gemini-4-hydrogen")
    @patch("ai.api._get_genai_client")
    def test_calls_only_returns_failure(self, mock_get_client, _model, mock_exec):
        """テキストが無ければ失敗扱いにし、function_callを履歴に残さない"""
        parts = [types.Part.from_function_call(name="search_recipe", args={"query": "x"})]
        mock_get_client.return_value.models.generate_content.return_value = self._make_response(parts)

        success, text, history = _call_genai_with_tools([], "system", tool_mode="none")

        assert success is False
        assert "読み取れなかった" in text
        mock_exec.assert_not_called()
        assert history == []
        # 再リクエストは1回だけ
        assert mock_get_client.return_value.models.generate_content.call_count == 2

    @patch("ai.api._execute_tool_calls")
    @patch("ai.api.get_model_name", return_value="gemini-4-hydrogen")
    @patch("ai.api._get_genai_client")
    def test_retry_with_flattened_history_succeeds(self, mock_get_client, _model, mock_exec):
        """function系partをテキスト化した履歴で再リクエストし、その応答を採用する"""
        call_only = [types.Part.from_function_call(name="search_recipe", args={"query": "x"})]
        text_only = [types.Part.from_text(text="ちゃんと答えるね")]
        generate = mock_get_client.return_value.models.generate_content
        generate.side_effect = [self._make_response(call_only), self._make_response(text_only)]
        contents = [
            types.Content(role="user", parts=[types.Part.from_text(text="User: 集計して")]),
            types.Content(
                role="model",
                parts=[types.Part.from_function_call(name="search_recipe", args={})],
            ),
            types.Content(
                role="user",
                parts=[types.Part.from_function_response(name="search_recipe", response={})],
            ),
            types.Content(role="model", parts=[types.Part.from_text(text="集計結果だよ")]),
            types.Content(role="user", parts=[types.Part.from_text(text="User: ありがとう")]),
        ]

        success, text, history = _call_genai_with_tools(contents, "system", tool_mode="none")

        assert success is True
        assert text == "ちゃんと答えるね"
        mock_exec.assert_not_called()
        retry_contents = generate.call_args_list[1].kwargs["contents"]
        # function_callのみのmodelは消え、ツール結果はテキストとしてユーザー発言にまとまる
        assert [c.role for c in retry_contents] == ["user", "model", "user"]
        assert "search_recipe" in retry_contents[0].parts[1].text
        assert all(
            not p.function_call and not p.function_response
            for c in retry_contents
            for p in c.parts
        )
        # 保存用の履歴は元のまま + テキスト応答のみ追加
        assert history[:-1] == contents
        assert history[-1].parts[0].text == "ちゃんと答えるね"

    @patch("ai.api.get_model_name", return_value="gemini-4-hydrogen")
    @patch("ai.api._get_genai_client")
    def test_retry_api_error_returns_failure(self, mock_get_client, _model):
        """再リクエストでAPIエラーが起きたら失敗として返す"""
        call_only = [types.Part.from_function_call(name="search_recipe", args={})]
        mock_get_client.return_value.models.generate_content.side_effect = [
            self._make_response(call_only),
            RuntimeError("boom"),
        ]

        success, text, history = _call_genai_with_tools([], "system", tool_mode="none")

        assert success is False
        assert "エラー" in text
        assert history == []


class TestHistoryRollbackOnFailure:
    """応答生成失敗時の履歴ロールバックのテスト"""

    @patch("ai.conversation.detect_tool_mode", return_value="function_calling")
    @patch("ai.conversation._call_genai_with_tools")
    def test_failure_restores_previous_history(self, mock_call, _router):
        """失敗時はユーザー発言と中間のツール履歴を破棄する"""
        sphene = Sphene("System")
        previous = [
            types.Content(role="user", parts=[types.Part.from_text(text="User: hi")]),
            types.Content(role="model", parts=[types.Part.from_text(text="hello")]),
        ]
        sphene.history = list(previous)
        polluted = previous + [
            types.Content(role="user", parts=[types.Part.from_text(text="User: 集計して")]),
            types.Content(
                role="model",
                parts=[types.Part.from_function_call(name="search_recipe", args={})],
            ),
        ]
        mock_call.return_value = (False, "処理が複雑すぎて諦めちゃった…😢", polluted)

        response = sphene.input_message("集計して")

        assert response == "処理が複雑すぎて諦めちゃった…😢"
        assert sphene.history == previous

    @patch("ai.conversation.detect_tool_mode", side_effect=RuntimeError("router down"))
    def test_exception_restores_previous_history(self, _router):
        """予期せぬ例外でもユーザー発言を履歴に残さない"""
        sphene = Sphene("System")
        previous = [
            types.Content(role="user", parts=[types.Part.from_text(text="User: hi")]),
            types.Content(role="model", parts=[types.Part.from_text(text="hello")]),
        ]
        sphene.history = list(previous)

        response = sphene.input_message("集計して")

        assert "予期せぬエラー" in response
        assert sphene.history == previous

    @patch("ai.conversation.detect_tool_mode", return_value="none")
    @patch("ai.conversation._call_genai_with_tools")
    def test_success_keeps_updated_history(self, mock_call, _router):
        """成功時は更新後の履歴を採用する"""
        sphene = Sphene("System")
        updated = [
            types.Content(role="user", parts=[types.Part.from_text(text="User: hi")]),
            types.Content(role="model", parts=[types.Part.from_text(text="hello")]),
        ]
        mock_call.return_value = (True, "hello", updated)

        sphene.input_message("hi")

        assert sphene.history == updated
