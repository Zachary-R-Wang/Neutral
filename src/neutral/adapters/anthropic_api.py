"""Anthropic implementation of the model adapter.

Everything provider-specific lives here: model ids, request shape, refusal detection,
token accounting, pricing. Nothing outside this file imports the anthropic package.

Two API facts shape the design and are worth stating, because they are easy to get wrong
from memory:

  * `temperature` is rejected by the current models. The model's run-to-run variation
    therefore cannot be dialled up or down. That is why the harness measures the noise
    floor empirically instead of assuming it - see eval/scoring.py.

  * A refusal arrives as HTTP 200 with stop_reason "refusal", not as an exception. Code
    that only checks for errors will silently treat a refusal as an answer.
"""

from __future__ import annotations

import anthropic

from neutral.adapters.base import Completion

# US dollars per million tokens. Used only to estimate what a run will cost before it is
# started, so nobody spends money by accident.
PRICING: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.00, 50.00),
    "claude-fable-5": (10.00, 50.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

# Models that take adaptive thinking. Older models use a token budget instead, which this
# project does not need.
_ADAPTIVE_THINKING_PREFIXES = (
    "claude-fable-5",
    "claude-mythos-5",
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
)


def supports_adaptive_thinking(model: str) -> bool:
    return model.startswith(_ADAPTIVE_THINKING_PREFIXES)


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Dollars for a given token count. Unknown models cost 0 and say so upstream."""
    if model not in PRICING:
        return 0.0
    in_rate, out_rate = PRICING[model]
    return (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate


class AnthropicAdapter:
    """Calls a Claude model and returns a provider-neutral Completion."""

    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        max_tokens: int = 8000,
        effort: str = "high",
        thinking: bool = True,
        timeout: float = 600.0,
        max_retries: int = 3,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.effort = effort
        self.thinking = thinking
        self._client = anthropic.Anthropic(
            api_key=api_key, timeout=timeout, max_retries=max_retries
        )

    def _request_kwargs(self) -> dict:
        kwargs: dict = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "output_config": {"effort": self.effort},
        }
        if self.thinking and supports_adaptive_thinking(self.model):
            kwargs["thinking"] = {"type": "adaptive"}
        return kwargs

    def complete(self, prompt: str, *, system: str | None = None) -> Completion:
        kwargs = self._request_kwargs()
        if system:
            kwargs["system"] = system

        try:
            response = self._client.messages.create(
                messages=[{"role": "user", "content": prompt}], **kwargs
            )
        except anthropic.AuthenticationError:
            return Completion(
                text="",
                model=self.model,
                error=(
                    "The Anthropic API rejected your key. Check ANTHROPIC_API_KEY in "
                    ".env, and that the key has not been revoked."
                ),
            )
        except anthropic.NotFoundError:
            return Completion(
                text="",
                model=self.model,
                error=(
                    f"The model {self.model!r} does not exist or is not available to "
                    f"your account. Check NEUTRAL_SUBJECT_MODEL and NEUTRAL_JUDGE_MODEL "
                    f"in .env."
                ),
            )
        except anthropic.RateLimitError:
            return Completion(
                text="",
                model=self.model,
                error=(
                    "Rate limited by the API after several retries. Lower "
                    "NEUTRAL_CONCURRENCY in .env and run it again."
                ),
            )
        except anthropic.APIConnectionError:
            return Completion(
                text="",
                model=self.model,
                error="Could not reach the Anthropic API. Check your internet connection.",
            )
        except anthropic.APIStatusError as exc:
            return Completion(
                text="",
                model=self.model,
                error=f"The API returned an error ({exc.status_code}): {exc.message}",
            )

        return self._to_completion(response)

    def _to_completion(self, response) -> Completion:
        stop_reason = response.stop_reason or ""

        text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )

        refusal_category = None
        if stop_reason == "refusal" and response.stop_details is not None:
            refusal_category = getattr(response.stop_details, "category", None)

        return Completion(
            text=text,
            model=response.model,
            refused=stop_reason == "refusal",
            stop_reason=stop_reason,
            refusal_category=refusal_category,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            truncated=stop_reason == "max_tokens",
        )

    def parse(self, prompt: str, output_format, *, system: str | None = None):
        """Ask for a validated structured answer.

        Used by the judge so a score can never arrive as unparseable prose.
        Returns (parsed_or_None, Completion).
        """
        kwargs = self._request_kwargs()
        if system:
            kwargs["system"] = system

        try:
            response = self._client.messages.parse(
                messages=[{"role": "user", "content": prompt}],
                output_format=output_format,
                **kwargs,
            )
        except anthropic.APIStatusError as exc:
            return None, Completion(
                text="", model=self.model, error=f"Judge call failed: {exc.message}"
            )
        except anthropic.APIConnectionError:
            return None, Completion(
                text="", model=self.model, error="Could not reach the API for the judge call."
            )

        completion = self._to_completion(response)
        if completion.refused or completion.truncated:
            return None, completion
        return response.parsed_output, completion
