"""The model adapter boundary.

CLAUDE.md section 4: Neutral must work against more than one provider, and no
provider-specific detail may leak past this file. Everything upstream of here speaks in
Completions, not in any vendor's response objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Completion:
    """One model answer, plus what we need to audit and cost it."""

    text: str
    model: str
    # S3 - true when the model declined. A refusal is returned verbatim and never
    # retried, rephrased, or split into pieces.
    refused: bool = False
    stop_reason: str = ""
    refusal_category: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    # Set when the call failed. The caller decides what to do; it never crashes a run.
    error: str | None = None
    # True when the answer hit the token ceiling and was cut off mid-thought. Such an
    # answer must not be scored as if it were complete.
    truncated: bool = False
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error is None and not self.truncated


@runtime_checkable
class ModelAdapter(Protocol):
    """What every provider must offer. Nothing more is assumed anywhere else."""

    name: str
    model: str

    def complete(self, prompt: str, *, system: str | None = None) -> Completion:
        """Send one prompt and return one answer."""
        ...
