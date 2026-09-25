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
    models: tuple[str, ...]
    key_hint: str
    key_url: str


PROVIDERS: dict[str, Provider] = {
    "anthropic": Provider(
        key="anthropic",
        label="Claude",
        default_model="claude-sonnet-5",
        models=("claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"),
        key_hint="starts sk-ant-",
        key_url="https://console.anthropic.com/settings/keys",
    ),
    "openai": Provider(
        key="openai",
        label="OpenAI",
        default_model="gpt-5",
        models=("gpt-5", "gpt-5-mini", "gpt-4.1"),
        key_hint="starts sk-",
        key_url="https://platform.openai.com/api-keys",
    ),
    "google": Provider(
        key="google",
        label="Gemini",
        default_model="gemini-2.5-pro",
        models=("gemini-2.5-pro", "gemini-2.5-flash"),
        key_hint="from Google AI Studio",
        key_url="https://aistudio.google.com/apikey",
    ),
    "xai": Provider(
        key="xai",
        label="Grok",
        default_model="grok-4",
        models=("grok-4", "grok-3"),
        key_hint="starts xai-",
        key_url="https://console.x.ai",
    ),
}

# Where the OpenAI-compatible adapter points for each provider that speaks that shape.
_OPENAI_COMPATIBLE = {
    "openai": "https://api.openai.com/v1",
    "xai": "https://api.x.ai/v1",
}


def _classify(status: int, body: str) -> str:
    """Map any provider's failure onto the neutral list in neutral/errors.py.

    Every provider words these differently; none of that wording reaches a person.
    """
    lowered = body.lower()
    if status in (401, 403):
        return errors.AUTH
    if status == 429:
        return errors.RATE_LIMITED
    if status >= 500:
        return errors.SERVER_ERROR
    if any(
        phrase in lowered
        for phrase in ("credit", "quota", "billing", "insufficient_quota", "exceeded")
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
