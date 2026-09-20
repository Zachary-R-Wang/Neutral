"""A deterministic stand-in model, for tests that must not call a real API."""

from __future__ import annotations

from collections.abc import Callable

from neutral.adapters.base import Completion

REFUSAL = "I can't help with that."


class FakeAdapter:
    """Returns scripted answers. Records every prompt it was given."""

    name = "fake"

    def __init__(
        self,
        reply: str | Callable[[str], str] = "A perfectly ordinary answer.",
        *,
        model: str = "fake-model-1",
        refuse: bool = False,
        fail_with: Exception | None = None,
    ) -> None:
        self._reply = reply
        self.model = model
        self._refuse = refuse
        self._fail_with = fail_with
        self.prompts_seen: list[str] = []

    def complete(self, prompt: str, *, system: str | None = None) -> Completion:
        self.prompts_seen.append(prompt)

        if self._fail_with is not None:
            return Completion(text="", model=self.model, error=str(self._fail_with))

        if self._refuse:
            return Completion(
                text=REFUSAL,
                model=self.model,
                refused=True,
                stop_reason="refusal",
                refusal_category="test",
            )

        text = self._reply(prompt) if callable(self._reply) else self._reply
        return Completion(
            text=text,
            model=self.model,
            stop_reason="end_turn",
            input_tokens=len(prompt) // 4,
            output_tokens=len(text) // 4,
        )
