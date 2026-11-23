"""Gen AI API リトライ設定（RetryPolicy）のテスト"""

import time
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from google.api_core import exceptions as google_exceptions
from google.genai import errors as genai_errors
from google.genai import types

import config
from ai.api import (
    RetryPolicy,
    _is_timeout_error,
    call_genai_with_tools,
    generate_content_with_retry,
    light_retry_policy,
    main_retry_policy,
)


def _policy(**overrides: Any) -> RetryPolicy:
    values: dict[str, Any] = {
        "max_attempts": 5,
        "timeout_retries": 1,
        "request_timeout_seconds": 300,
        "total_timeout_seconds": 600,
    }
    values.update(overrides)
    return RetryPolicy(**values)


def _call(client: MagicMock, **kwargs: Any) -> Any:
    return generate_content_with_retry(
        client=client,
        model="test-model",
        contents=[],
        config=types.GenerateContentConfig(temperature=0.0),
        **kwargs,
    )


@pytest.fixture(autouse=True)
def _no_sleep():
    with patch("time.sleep", return_value=None):
        yield


class TestPolicyFromConfig:
    def test_main_policy_reads_config(self) -> None:
        with patch.object(config, "GENAI_MAIN_MAX_ATTEMPTS", 3), patch.object(
            config, "GENAI_MAIN_TIMEOUT_RETRIES", 2
        ), patch.object(config, "GENAI_REQUEST_TIMEOUT_SECONDS", 120), patch.object(
            config, "GENAI_MAIN_TOTAL_TIMEOUT_SECONDS", 400
        ):
            assert main_retry_policy() == RetryPolicy(3, 2, 120, 400)

    def test_light_policy_reads_config(self) -> None:
        with patch.object(config, "GENAI_LIGHT_MAX_ATTEMPTS", 4), patch.object(
            config, "GENAI_LIGHT_TIMEOUT_RETRIES", 1
        ), patch.object(config, "GENAI_LIGHT_REQUEST_TIMEOUT_SECONDS", 10), patch.object(
            config, "GENAI_LIGHT_TOTAL_TIMEOUT_SECONDS", 20
        ):
            assert light_retry_policy() == RetryPolicy(4, 1, 10, 20)

    def test_light_defaults_are_shorter_than_main(self) -> None:
        main, light = main_retry_policy(), light_retry_policy()
        assert light.request_timeout_seconds < main.request_timeout_seconds
        assert light.max_attempts <= main.max_attempts
        assert light.total_timeout_seconds < main.total_timeout_seconds


class TestIsTimeoutError:
    @pytest.mark.parametrize(
        "error",
        [
            httpx.ReadTimeout("timeout"),
            TimeoutError(),
            google_exceptions.DeadlineExceeded("deadline"),
            genai_errors.APIError(504, {}),
            genai_errors.APIError(408, {}),
        ],
    )
    def test_timeout_errors(self, error: BaseException) -> None:
        assert _is_timeout_error(error) is True

    @pytest.mark.parametrize(
        "error",
        [
            genai_errors.APIError(429, {}),
            genai_errors.APIError(503, {}),
            httpx.ConnectError("refused"),
            google_exceptions.TooManyRequests("busy"),
        ],
    )
    def test_non_timeout_errors(self, error: BaseException) -> None:
        assert _is_timeout_error(error) is False


class TestTimeoutRetries:
    def test_timeout_retried_only_timeout_retries_times(self) -> None:
        client = MagicMock()
        client.models.generate_content.side_effect = httpx.ReadTimeout("timeout")

        with pytest.raises(httpx.ReadTimeout):
            _call(client, policy=_policy(timeout_retries=1))

        assert client.models.generate_content.call_count == 2

    def test_no_timeout_retry_when_zero(self) -> None:
        client = MagicMock()
        client.models.generate_content.side_effect = httpx.ReadTimeout("timeout")

        with pytest.raises(httpx.ReadTimeout):
            _call(client, policy=_policy(timeout_retries=0))

        assert client.models.generate_content.call_count == 1

    def test_rate_limit_still_retried_up_to_max_attempts(self) -> None:
        client = MagicMock()
        client.models.generate_content.side_effect = genai_errors.APIError(429, {})

        with pytest.raises(genai_errors.APIError):
            _call(client, policy=_policy(max_attempts=3, timeout_retries=0))

        assert client.models.generate_content.call_count == 3

    def test_timeout_count_shared_with_other_errors(self) -> None:
        """429 を挟んでもタイムアウト系の再試行回数は通算で数える"""
        client = MagicMock()
        client.models.generate_content.side_effect = [
            httpx.ReadTimeout("t1"),
            genai_errors.APIError(503, {}),
            httpx.ReadTimeout("t2"),
            "never",
        ]

        with pytest.raises(httpx.ReadTimeout):
            _call(client, policy=_policy(timeout_retries=1))

        assert client.models.generate_content.call_count == 3

    def test_non_retryable_not_retried(self) -> None:
        client = MagicMock()
        client.models.generate_content.side_effect = genai_errors.APIError(400, {})

        with pytest.raises(genai_errors.APIError):
            _call(client, policy=_policy())

        assert client.models.generate_content.call_count == 1


class TestDeadline:
    def test_passed_deadline_raises_without_calling(self) -> None:
        client = MagicMock()

        with pytest.raises(TimeoutError):
            _call(client, policy=_policy(), deadline=time.monotonic() - 1)

        client.models.generate_content.assert_not_called()

    def test_too_little_remaining_raises_without_calling(self) -> None:
        """残り時間が最低ラインを下回るならリクエストを送らない"""
        client = MagicMock()

        with patch.object(config, "GENAI_MIN_REQUEST_TIMEOUT_SECONDS", 5):
            with pytest.raises(TimeoutError):
                _call(client, policy=_policy(), deadline=time.monotonic() + 3)

        client.models.generate_content.assert_not_called()

    def test_remaining_above_minimum_is_sent(self) -> None:
        client = MagicMock()
        client.models.generate_content.return_value = "ok"

        with patch.object(config, "GENAI_MIN_REQUEST_TIMEOUT_SECONDS", 5):
            _call(client, policy=_policy(), deadline=time.monotonic() + 8)

        client.models.generate_content.assert_called_once()

    def test_stops_retrying_when_wait_exceeds_deadline(self) -> None:
        """次の待機（最低2秒）で上限を超えるなら再試行しない"""
        client = MagicMock()
        client.models.generate_content.side_effect = genai_errors.APIError(503, {})

        with patch.object(config, "GENAI_MIN_REQUEST_TIMEOUT_SECONDS", 0):
            with pytest.raises(genai_errors.APIError):
                _call(client, policy=_policy(), deadline=time.monotonic() + 1)

        assert client.models.generate_content.call_count == 1

    def test_request_timeout_capped_by_remaining_time(self) -> None:
        client = MagicMock()
        client.models.generate_content.return_value = "ok"

        _call(client, policy=_policy(request_timeout_seconds=300), deadline=time.monotonic() + 10)

        sent = client.models.generate_content.call_args.kwargs["config"]
        assert 0 < sent.http_options.timeout <= 10_000

    def test_request_timeout_uses_policy_value(self) -> None:
        client = MagicMock()
        client.models.generate_content.return_value = "ok"

        _call(client, policy=_policy(request_timeout_seconds=30))

        sent = client.models.generate_content.call_args.kwargs["config"]
        assert sent.http_options.timeout == 30_000
        assert sent.temperature == 0.0

    def test_existing_http_options_preserved(self) -> None:
        client = MagicMock()
        client.models.generate_content.return_value = "ok"
        original = types.GenerateContentConfig(
            http_options=types.HttpOptions(headers={"X-Test": "1"})
        )

        generate_content_with_retry(
            client=client, model="m", contents=[], config=original, policy=_policy()
        )

        sent = client.models.generate_content.call_args.kwargs["config"]
        assert sent.http_options.headers == {"X-Test": "1"}
        assert sent.http_options.timeout == 300_000
        assert original.http_options is not None
        assert original.http_options.timeout is None  # 元の config は変更しない

    def test_default_policy_is_main(self) -> None:
        client = MagicMock()
        client.models.generate_content.return_value = "ok"

        with patch.object(config, "GENAI_REQUEST_TIMEOUT_SECONDS", 123):
            _call(client)

        sent = client.models.generate_content.call_args.kwargs["config"]
        assert sent.http_options.timeout == 123_000


class TestToolLoopSharesDeadline:
    @patch("ai.api.get_tools", return_value=[])
    @patch("ai.api.get_model_name", return_value="test-model")
    @patch("ai.api._get_genai_client")
    @patch("ai.api.generate_content_with_retry")
    def test_all_rounds_share_one_deadline(
        self,
        mock_generate: MagicMock,
        _mock_client: MagicMock,
        _mock_model: MagicMock,
        _mock_tools: MagicMock,
    ) -> None:
        call_part = types.Part(function_call=types.FunctionCall(name="unknown_fn", args={}))
        text_part = types.Part.from_text(text="done")

        def _response(part: types.Part) -> MagicMock:
            resp = MagicMock()
            resp.candidates = [MagicMock(content=types.Content(role="model", parts=[part]))]
            resp.candidates[0].grounding_metadata = None
            return resp

        mock_generate.side_effect = [_response(call_part), _response(text_part)]

        ok, text, _ = call_genai_with_tools([], "sys", tool_mode="function_calling")

        assert ok is True and text == "done"
        deadlines = {c.kwargs["deadline"] for c in mock_generate.call_args_list}
        policies = {c.kwargs["policy"] for c in mock_generate.call_args_list}
        assert len(deadlines) == 1
        assert policies == {main_retry_policy()}

    @patch("ai.api.get_model_name", return_value="test-model")
    @patch("ai.api._get_genai_client")
    @patch("ai.api.generate_content_with_retry", side_effect=TimeoutError("budget"))
    def test_budget_exhausted_returns_timeout_message(
        self, _mock_generate: MagicMock, _mock_client: MagicMock, _mock_model: MagicMock
    ) -> None:
        ok, text, _ = call_genai_with_tools([], "sys", tool_mode="none")

        assert ok is False
        assert "時間内" in text


class TestLightPolicyApplied:
    @patch("ai.router._generate_content_with_retry")
    def test_router_uses_light_policy(self, mock_generate: MagicMock) -> None:
        from ai.router import _call_router_llm

        mock_generate.return_value = MagicMock(text='{"tool_mode": "none"}')
        with patch("ai.router._get_genai_client"):
            _call_router_llm("hello", None)

        assert mock_generate.call_args.kwargs["policy"] == light_retry_policy()

    @patch("memory.llm_judge._generate_content_with_retry")
    def test_llm_judge_uses_light_policy(self, mock_generate: MagicMock) -> None:
        from memory.llm_judge import LLMJudge

        mock_generate.return_value = MagicMock(text='{"respond": false}')
        with patch("memory.llm_judge._get_genai_client"):
            LLMJudge()._call_llm("hello", "ctx", "bot")

        assert mock_generate.call_args.kwargs["policy"] == light_retry_policy()

    @patch("ai.conversation.load_system_prompt", return_value="sys")
    @patch("ai.conversation._get_genai_client")
    @patch("ai.conversation._generate_content_with_retry")
    def test_short_ack_uses_light_policy(
        self, mock_generate: MagicMock, _mock_client: MagicMock, _mock_prompt: MagicMock
    ) -> None:
        from ai.conversation import generate_short_ack

        mock_generate.return_value = MagicMock(candidates=[])
        generate_short_ack(channel_context="ctx", trigger_message="hi")

        assert mock_generate.call_args.kwargs["policy"] == light_retry_policy()
