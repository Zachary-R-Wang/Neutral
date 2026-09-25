"""Providers other than Anthropic, and the registry that picks between them.

CLAUDE.md section 4: "The model adapter is an interface. Neutral must work against more
than one provider. Never let provider-specific details leak past the adapter boundary."

Until now that was an interface with one implementation behind it, which proves nothing.
These are the others.

**Why these speak HTTP rather than each vendor's SDK.** Anthropic keeps its official SDK,
because that is what its own guidance calls for and because the evaluation harness leans
on structured output and refusal detection that the SDK models properly. For the rest,
each SDK would add a dependency tree to use perhaps thirty lines of it, and every one
would need its own error taxonomy mapped back to neutral/errors.py anyway. The request
shapes below are small enough to read in full, which is worth more here than a wrapper.

**OpenAI-compatible covers more than OpenAI.** xAI, Groq, Together, Fireworks, OpenRouter
and most self-hosted servers all speak the same /chat/completions shape, so one adapter
and a base URL reaches all of them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from neutral import errors
from neutral.adapters.base import Completion

TIMEOUT = httpx.Timeout(300.0, connect=10.0, read=300.0, write=30.0, pool=10.0)


@dataclass(frozen=True)
class Provider:
    """One place a prompt can be sent, and what a person needs to know to choose it."""

    key: str
    label: str
    default_model: str
    # Flagship first - it is also the default. This list is a convenience for picking,
    # never a restriction: the connect page lets a person type any model name, because a
    # hardcoded list of five vendors' model names is stale the week after it is written,
    # and an enterprise on a custom deployment would never find itself on it.
    models: tuple[str, ...]
    key_hint: str
    key_url: str


PROVIDERS: dict[str, Provider] = {
    "anthropic": Provider(
        key="anthropic",
        label="Claude",
        default_model="claude-opus-5-5",
        models=(
            "claude-opus-5-5",
            "claude-fable-5-1",
            "claude-sonnet-5",
            "claude-haiku-4-5-20251001",
        ),
        key_hint="starts sk-ant-",
        key_url="https://console.anthropic.com/settings/keys",
    ),
    "openai": Provider(
        key="openai",
        label="OpenAI",
        default_model="gpt-6-astra",
        models=("gpt-6-astra", "gpt-6-sol", "gpt-6-luna"),
        key_hint="starts sk-",
        key_url="https://platform.openai.com/api-keys",
    ),
    "google": Provider(
        key="google",
        label="Gemini",
        default_model="gemini-3.8-flash",
        models=(
            "gemini-3.8-flash",
            "gemini-3.1-pro-preview",
            "gemini-3.7-flash",
            "gemini-3.5-flash-lite",
        ),
        key_hint="from Google AI Studio",
        key_url="https://aistudio.google.com/apikey",
    ),
    "xai": Provider(
        key="xai",
        label="Grok",
        default_model="grok-4.7",
        models=("grok-4.7", "grok-4.6", "grok-4.5", "grok-4.3"),
        key_hint="starts xai-",
        key_url="https://console.x.ai",
    ),
    "deepseek": Provider(
        key="deepseek",
        label="DeepSeek",
        default_model="deepseek-flash",
        models=("deepseek-flash", "deepseek-v4-pro"),
        key_hint="starts sk-",
        key_url="https://platform.deepseek.com/api_keys",
    ),
}

# Dollars per million tokens, (input, output), checked against each vendor's own pricing
# page on 2026-09-25. Only the flagships are here, because those are what the harness
# measures. A model missing from this table makes the cost estimate say so out loud
# rather than quietly report the judge's cost as the whole bill.
PRICING: dict[str, tuple[float, float]] = {
    "gpt-6-astra": (10.00, 50.00),
    "gemini-3.8-flash": (0.75, 3.75),
    "grok-4.7": (2.00, 6.00),
    # DeepSeek charges less off-peak; the peak rate is used so an estimate is never
    # lower than the bill.
    "deepseek-flash": (0.30, 1.20),
}


def price_of(model: str) -> tuple[float, float] | None:
    """Input and output dollars per million tokens, or None if nobody has told us."""
    from neutral.adapters.anthropic_api import PRICING as ANTHROPIC_PRICING

    return ANTHROPIC_PRICING.get(model) or PRICING.get(model)


_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}$")


def looks_like_model(name: str) -> bool:
    """Whether a string could plausibly be a model identifier.

    Written after a browser's autofill put the account holder's email address into the
    custom model box, where it was sent to the provider as the model name, saved as their
    preference, and put back into the box on every later visit.

    Model identifiers have no spaces and no @, and in practice always carry a version
    number or a separator - gpt-6-astra, grok-4.7, claude-sonnet-5, ft:my-tune. That last
    rule is what catches a bare username like "jack", which autofill also produced.
    """
    name = (name or "").strip()
    if not _MODEL_ID.match(name):
        return False
    return any(ch.isdigit() or ch in "-._:/" for ch in name)


# Where each provider's key is read from when the evaluation harness measures it. The
# website never uses these - there every person brings their own key, in the browser.
KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "xai": "XAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}


def key_from_env(provider: str) -> str:
    """The configured key for this provider, or empty. Never logged, never printed."""
    import os

    return os.environ.get(KEY_ENV.get(provider, ""), "").strip()


ORDER = ("anthropic", "openai", "google", "xai", "deepseek")


def default_model_for(provider: str) -> str:
    """The model to use when the person has not picked one. Empty for an unknown key."""
    spec = PROVIDERS.get(provider)
    return spec.default_model if spec else ""


def label_for(provider: str) -> str:
    """What to call this provider in the interface."""
    spec = PROVIDERS.get(provider)
    return spec.label if spec else provider


# Where the OpenAI-compatible adapter points for each provider that speaks that shape.
_OPENAI_COMPATIBLE = {
    "openai": "https://api.openai.com/v1",
    "xai": "https://api.x.ai/v1",
    "deepseek": "https://api.deepseek.com/v1",
}


def _classify(status: int, body: str) -> str:
    """Map any provider's failure onto the neutral list in neutral/errors.py.

    Every provider words these differently; none of that wording reaches a person.
    """
    lowered = body.lower()
    if status in (401, 403):
        return errors.AUTH

    # Status alone is not enough. Gemini and Grok answer a bad API key with 400, not 401,
    # so reading only the code reported "the model rejected the request" to somebody whose
    # key was simply wrong - sending them to look at their prompt instead of their
    # credentials. Every provider says so in words even when the number disagrees.
    if any(
        phrase in lowered
        for phrase in (
            "api key not valid",
            "invalid api key",
            "incorrect api key",
            "api key is invalid",
            "invalid_api_key",
            "invalid authentication",
            "authentication fails",
            "unauthorized",
            "no auth credentials",
            "missing api key",
        )
    ):
        return errors.AUTH

    if status == 429:
        return errors.RATE_LIMITED
    if status >= 500:
        return errors.SERVER_ERROR
    # A wrong model name is the likeliest mistake now that the model field takes
    # anything typed into it, and "the model rejected the request" is no help with it.
    if errors.is_model_missing(status, body):
        return errors.MODEL_NOT_FOUND
    if status == 402:
        return errors.NO_CREDIT
    if any(
        phrase in lowered
        for phrase in (
            "credit",
            "quota",
            "billing",
            "insufficient_quota",
            "insufficient balance",
            "exceeded",
        )
    ):
        return errors.NO_CREDIT
    return errors.BAD_REQUEST


class OpenAICompatibleAdapter:
    """OpenAI's /chat/completions shape, which many providers implement."""

    name = "openai-compatible"

    def __init__(self, api_key: str, model: str, *, base_url: str, max_tokens: int = 4000):
        self.model = model
        self.max_tokens = max_tokens
        self._key = api_key
        self._base = base_url.rstrip("/")

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        history: list[tuple[str, str]] | None = None,
    ) -> Completion:
        messages = [{"role": "system", "content": system}] if system else []
        messages += [{"role": role, "content": text} for role, text in (history or [])]
        messages.append({"role": "user", "content": prompt})

        try:
            response = httpx.post(
                f"{self._base}/chat/completions",
                headers={"Authorization": f"Bearer {self._key}"},
                json={
                    "model": self.model,
                    "messages": messages,
                    "max_completion_tokens": self.max_tokens,
                },
                timeout=TIMEOUT,
            )
        except httpx.HTTPError as exc:
            return Completion(
                text="", model=self.model, error_kind=errors.UNREACHABLE, error=str(exc)
            )

        if response.status_code >= 400:
            return Completion(
                text="",
                model=self.model,
                error_kind=_classify(response.status_code, response.text),
                error=response.text[:400],
            )

        data = response.json()
        choice = (data.get("choices") or [{}])[0]
        usage = data.get("usage") or {}
        finish = choice.get("finish_reason", "")
        return Completion(
            text=(choice.get("message") or {}).get("content") or "",
            model=data.get("model", self.model),
            stop_reason=finish,
            refused=finish == "content_filter",
            truncated=finish == "length",
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )


class GeminiAdapter:
    """Google's generateContent shape.

    Two differences worth naming: the assistant role is called "model", and the system
    prompt is a separate field rather than a message.
    """

    name = "google"

    def __init__(self, api_key: str, model: str, *, max_tokens: int = 4000):
        self.model = model
        self.max_tokens = max_tokens
        self._key = api_key

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        history: list[tuple[str, str]] | None = None,
    ) -> Completion:
        contents = [
            {"role": "model" if role == "assistant" else "user", "parts": [{"text": text}]}
            for role, text in (history or [])
        ]
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        payload: dict = {
            "contents": contents,
            "generationConfig": {"maxOutputTokens": self.max_tokens},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        try:
            response = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{self.model}:generateContent",
                headers={"x-goog-api-key": self._key},
                json=payload,
                timeout=TIMEOUT,
            )
        except httpx.HTTPError as exc:
            return Completion(
                text="", model=self.model, error_kind=errors.UNREACHABLE, error=str(exc)
            )

        if response.status_code >= 400:
            return Completion(
                text="",
                model=self.model,
                error_kind=_classify(response.status_code, response.text),
                error=response.text[:400],
            )

        data = response.json()
        candidates = data.get("candidates") or []
        reason = candidates[0].get("finishReason", "") if candidates else "SAFETY"
        parts = (candidates[0].get("content", {}) if candidates else {}).get("parts") or []
        usage = data.get("usageMetadata") or {}
        return Completion(
            text="".join(part.get("text", "") for part in parts),
            model=self.model,
            stop_reason=reason,
            # Gemini reports a blocked answer as a finish reason, not as an error.
            refused=reason in ("SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT"),
            truncated=reason == "MAX_TOKENS",
            input_tokens=usage.get("promptTokenCount", 0),
            output_tokens=usage.get("candidatesTokenCount", 0),
        )


def build(provider: str, api_key: str, model: str = "", *, max_tokens: int = 4000):
    """The adapter for a provider. Nothing above this line knows which one it got."""
    spec = PROVIDERS.get(provider)
    if spec is None:
        raise ValueError(f"unknown provider {provider!r}")
    model = model or spec.default_model

    if provider == "anthropic":
        from neutral.adapters.anthropic_api import AnthropicAdapter

        return AnthropicAdapter(api_key=api_key, model=model, max_tokens=max_tokens)
    if provider in _OPENAI_COMPATIBLE:
        return OpenAICompatibleAdapter(
            api_key, model, base_url=_OPENAI_COMPATIBLE[provider], max_tokens=max_tokens
        )
    return GeminiAdapter(api_key, model, max_tokens=max_tokens)
