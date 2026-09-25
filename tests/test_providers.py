"""Every provider must look the same from above the adapter boundary.

CLAUDE.md section 4 asks for an interface that more than one provider implements, and
that no provider-specific detail gets past. An interface with one implementation behind
it proves neither. These tests drive three more of them against recorded response shapes,
and check that what comes out the other side is identical in structure and vocabulary.
"""

from __future__ import annotations

import json

import httpx
import pytest

from neutral import errors
from neutral.adapters.base import Completion, ModelAdapter
from neutral.adapters.providers import PROVIDERS, build

PROMPT = "Assess Person A for promotion."


class _Response:
    """Stands in for an httpx response."""

    def __init__(self, status: int, payload: dict | str):
        self.status_code = status
        self._payload = payload
        self.text = payload if isinstance(payload, str) else json.dumps(payload)

    def json(self):
        return self._payload if isinstance(self._payload, dict) else {}


@pytest.fixture
def capture(monkeypatch):
    """Intercept the outbound request and reply with whatever the test wants."""
    sent: dict = {}

    def fake_post(url, *, headers=None, json=None, timeout=None):
        sent.update(url=url, headers=headers or {}, body=json or {})
        return sent["reply"]

    monkeypatch.setattr(httpx, "post", fake_post)
    return sent


OPENAI_OK = {
    "model": "gpt-5",
    "choices": [{"message": {"content": "Person A is ready."}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 40, "completion_tokens": 12},
}
GEMINI_OK = {
    "candidates": [
        {"content": {"parts": [{"text": "Person A is ready."}]}, "finishReason": "STOP"}
    ],
    "usageMetadata": {"promptTokenCount": 40, "candidatesTokenCount": 12},
}


class TestEveryProviderIsAnAdapter:
    @pytest.mark.parametrize("provider", sorted(PROVIDERS))
    def test_it_satisfies_the_interface(self, provider):
        assert isinstance(build(provider, "test-key"), ModelAdapter)

    @pytest.mark.parametrize("provider", sorted(PROVIDERS))
    def test_it_has_a_default_model_and_somewhere_to_get_a_key(self, provider):
        spec = PROVIDERS[provider]
        assert spec.default_model in spec.models
        assert spec.key_url.startswith("https://")


class TestAnswersComeBackTheSameShape:
    def test_openai(self, capture):
        capture["reply"] = _Response(200, OPENAI_OK)
        reply = build("openai", "k").complete(PROMPT)
        assert reply.text == "Person A is ready."
        assert reply.ok and not reply.refused
        assert (reply.input_tokens, reply.output_tokens) == (40, 12)

    def test_gemini(self, capture):
        capture["reply"] = _Response(200, GEMINI_OK)
        reply = build("google", "k").complete(PROMPT)
        assert reply.text == "Person A is ready."
        assert reply.ok and not reply.refused
        assert (reply.input_tokens, reply.output_tokens) == (40, 12)

    @pytest.mark.parametrize(
        ("provider", "host"),
        [("openai", "api.openai.com"), ("xai", "api.x.ai"), ("deepseek", "api.deepseek.com")],
    )
    def test_each_compatible_provider_goes_to_its_own_host(self, capture, provider, host):
        """They share a request shape, so the base URL is the only thing keeping them apart."""
        capture["reply"] = _Response(200, OPENAI_OK)
        build(provider, "k").complete(PROMPT)
        assert host in capture["url"]

    def test_history_is_sent_in_each_providers_own_shape(self, capture):
        history = [("user", "Earlier question"), ("assistant", "Earlier answer")]

        capture["reply"] = _Response(200, OPENAI_OK)
        build("openai", "k").complete(PROMPT, history=history)
        assert [m["role"] for m in capture["body"]["messages"]] == [
            "user",
            "assistant",
            "user",
        ]

        capture["reply"] = _Response(200, GEMINI_OK)
        build("google", "k").complete(PROMPT, history=history)
        # Gemini calls the assistant "model".
        assert [c["role"] for c in capture["body"]["contents"]] == ["user", "model", "user"]

    def test_a_system_prompt_goes_where_each_provider_expects_it(self, capture):
        capture["reply"] = _Response(200, OPENAI_OK)
        build("openai", "k").complete(PROMPT, system="Score this.")
        assert capture["body"]["messages"][0]["role"] == "system"

        capture["reply"] = _Response(200, GEMINI_OK)
        build("google", "k").complete(PROMPT, system="Score this.")
        assert "systemInstruction" in capture["body"]
        assert all(c["role"] != "system" for c in capture["body"]["contents"])


class TestRefusalsAreRecognisedWhateverTheyAreCalled:
    def test_openai_content_filter(self, capture):
        capture["reply"] = _Response(
            200, {"choices": [{"message": {"content": ""}, "finish_reason": "content_filter"}]}
        )
        assert build("openai", "k").complete(PROMPT).refused

    def test_gemini_safety_finish_reason(self, capture):
        """Gemini reports a blocked answer as a finish reason, not as an error."""
        capture["reply"] = _Response(
            200, {"candidates": [{"content": {"parts": []}, "finishReason": "SAFETY"}]}
        )
        assert build("google", "k").complete(PROMPT).refused

    def test_a_truncated_answer_is_not_mistaken_for_a_good_one(self, capture):
        capture["reply"] = _Response(
            200, {"choices": [{"message": {"content": "half a th"}, "finish_reason": "length"}]}
        )
        reply = build("openai", "k").complete(PROMPT)
        assert reply.truncated and not reply.ok


class TestFailuresSpeakTheNeutralVocabulary:
    @pytest.mark.parametrize(
        ("status", "body", "kind"),
        [
            (401, "invalid api key", errors.AUTH),
            (429, "rate limit reached", errors.RATE_LIMITED),
            (500, "internal error", errors.SERVER_ERROR),
            (400, "You exceeded your current quota", errors.NO_CREDIT),
            (400, "unsupported parameter", errors.BAD_REQUEST),
        ],
    )
    @pytest.mark.parametrize("provider", ["openai", "google", "xai"])
    def test_every_provider_maps_onto_the_same_list(self, capture, provider, status, body, kind):
        capture["reply"] = _Response(status, body)
        reply = build(provider, "k").complete(PROMPT)
        assert reply.error_kind == kind

    def test_running_out_of_money_is_not_reported_as_a_bad_request(self, capture):
        """DeepSeek answers 402 with "Insufficient Balance" where others say "quota".

        Both mean the same thing to the person reading it, and "the model rejected the
        request" would send them looking for a fault in their prompt.
        """
        capture["reply"] = _Response(402, "Insufficient Balance")
        assert build("deepseek", "k").complete(PROMPT).error_kind == errors.NO_CREDIT

        capture["reply"] = _Response(400, "Insufficient Balance")
        assert build("deepseek", "k").complete(PROMPT).error_kind == errors.NO_CREDIT

    @pytest.mark.parametrize(
        ("status", "body"),
        [
            # Gemini answers a bad key with 400, not 401. Reading the status alone told
            # somebody whose key was wrong that the model had rejected their request,
            # which sent them to look at their prompt.
            (
                400,
                '{"error":{"code":400,"message":"API key not valid. Please pass a valid API key.","status":"INVALID_ARGUMENT"}}',
            ),
            # Grok does the same, with different wording.
            (400, '{"code":"invalid-argument","error":"Incorrect API key provided."}'),
            (400, '{"error":{"message":"Authentication Fails, your api key is invalid"}}'),
            (400, "invalid_api_key"),
            (400, "Missing API key in request"),
            (401, "unauthorized"),
        ],
    )
    def test_a_bad_key_reads_as_a_bad_key_whatever_status_it_arrives_with(
        self, capture, status, body
    ):
        capture["reply"] = _Response(status, body)
        reply = build("google", "k").complete(PROMPT)
        assert reply.error_kind == errors.AUTH, (
            f"a {status} saying {body[:40]!r} was classified as {reply.error_kind}, so "
            f"the person would be told their request was rejected, not their key"
        )

    def test_an_ordinary_bad_request_is_still_a_bad_request(self):
        """The fix must not turn every 400 into an authentication problem."""
        from neutral.adapters.providers import _classify

        assert _classify(400, "unsupported parameter: top_k") == errors.BAD_REQUEST
        assert _classify(400, "messages must not be empty") == errors.BAD_REQUEST

    @pytest.mark.parametrize("provider", ["openai", "google", "xai", "deepseek"])
    def test_a_network_failure_is_returned_not_raised(self, provider, monkeypatch):
        def boom(*a, **k):
            raise httpx.ConnectError("no route to host")

        monkeypatch.setattr(httpx, "post", boom)
        reply = build(provider, "k").complete(PROMPT)
        assert reply.error_kind == errors.UNREACHABLE
        assert isinstance(reply, Completion)

    @pytest.mark.parametrize("provider", ["openai", "google", "xai", "deepseek"])
    def test_the_providers_own_wording_never_becomes_the_users_message(self, capture, provider):
        capture["reply"] = _Response(429, "OpenAI: slow down, see platform.openai.com")
        reply = build(provider, "k").complete(PROMPT)
        assert "openai" not in errors.user_message(reply.error_kind).lower()


def test_an_unknown_provider_is_refused_rather_than_guessed_at():
    with pytest.raises(ValueError, match="unknown provider"):
        build("definitely-not-a-provider", "k")


class TestEveryOfferedModelGetsARequestItAccepts:
    """A model on the picker that the adapter cannot call is a broken product.

    Sending output_config.effort to a model that does not take it comes back as a 400,
    which the interface rendered as "The connected model rejected the request" - true,
    unhelpful, and it hit anyone who chose Haiku.
    """

    def test_effort_is_only_sent_to_models_that_take_it(self):
        from neutral.adapters.anthropic_api import AnthropicAdapter, supports_adaptive_thinking
        from neutral.adapters.providers import PROVIDERS

        for model in PROVIDERS["anthropic"].models:
            kwargs = AnthropicAdapter(api_key="x", model=model)._request_kwargs()
            if supports_adaptive_thinking(model):
                assert kwargs["output_config"]["effort"], model
            else:
                assert "output_config" not in kwargs, (
                    f"{model} does not accept effort, but the request would send it"
                )

    def test_no_request_carries_thinking_without_support(self):
        from neutral.adapters.anthropic_api import AnthropicAdapter, supports_adaptive_thinking
        from neutral.adapters.providers import PROVIDERS

        for model in PROVIDERS["anthropic"].models:
            kwargs = AnthropicAdapter(api_key="x", model=model)._request_kwargs()
            if not supports_adaptive_thinking(model):
                assert "thinking" not in kwargs, model

    def test_the_model_and_token_limit_are_always_present(self):
        from neutral.adapters.anthropic_api import AnthropicAdapter
        from neutral.adapters.providers import PROVIDERS

        for model in PROVIDERS["anthropic"].models:
            kwargs = AnthropicAdapter(api_key="x", model=model, max_tokens=123)._request_kwargs()
            assert kwargs["model"] == model
            assert kwargs["max_tokens"] == 123
