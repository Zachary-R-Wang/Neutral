"""The mechanism plugin interface.

CLAUDE.md section 4: mechanisms are plugins. Each implements this interface, can be
enabled, disabled and evaluated independently, and no mechanism may call another directly.

A mechanism is handed the original prompt and the segments produced so far, and returns a
new list of segments. It never returns free text. That is what makes S1 checkable: a
mechanism has no way to emit a character that is not traceable to the original, unless it
emits an INJECT segment, which only Mechanism 4 may do and only when opted in.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from neutral.core import PolicyDecision, Segment, TransformRecord


@runtime_checkable
class Mechanism(Protocol):
    name: str

    def apply(
        self,
        original: str,
        segments: tuple[Segment, ...],
        decisions: tuple[PolicyDecision, ...],
    ) -> tuple[tuple[Segment, ...], tuple[TransformRecord, ...]]:
        """Rewrite the segments, returning the new segments and what was logged."""
        ...
