"""Core data types for Neutral.

These types exist to make the safety invariants in CLAUDE.md section 3 checkable by a
machine rather than by reading the code and hoping.

The central idea is the *segment*. A rewritten prompt is not free text that some function
produced; it is an ordered list of segments, and every segment must declare where its
characters came from:

    COPY    - characters copied verbatim from a span of the original prompt
    REPLACE - a placeholder substituted for a span of the original prompt
    INJECT  - characters that were NOT in the original prompt

INJECT is the only way to add content, and it is restricted to Mechanism 4 (comparison
framing), the single documented exception in CLAUDE.md section 3. Every other mechanism
can only copy, replace or drop. That makes "Neutral never adds information about a real
person" a property the verifier can prove by reconstruction, instead of a promise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

# The one mechanism permitted to inject content that was not in the original prompt.
# See CLAUDE.md section 3, "The one deliberate exception".
COMPARISON_FRAMING = "comparison_framing"


class SegmentKind(StrEnum):
    COPY = "copy"
    REPLACE = "replace"
    INJECT = "inject"


@dataclass(frozen=True)
class Span:
    """A half-open character range [start, end) in the original prompt."""

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError(f"Invalid span: [{self.start}, {self.end})")

    def text_in(self, source: str) -> str:
        return source[self.start : self.end]


@dataclass(frozen=True)
class Segment:
    """One piece of the rewritten prompt, with its provenance."""

    kind: SegmentKind
    # Where in the ORIGINAL prompt this segment's content came from.
    # Required for COPY and REPLACE. Must be None for INJECT.
    source: Span | None = None
    # The characters this segment contributes to the rewritten prompt.
    # For COPY this must equal the source text; it is stored so that rendering never
    # has to guess.
    text: str = ""
    # Which mechanism produced this segment. None for untouched COPY segments.
    mechanism: str | None = None


@dataclass(frozen=True)
class TransformRecord:
    """S7 - every transformation is logged with its reason.

    This is the audit trail, and it is also the training data that will make the
    relevance classifier better over time. It is a first-class output, not debug noise.
    """

    mechanism: str
    detected: str
    detected_kind: str
    replacement: str
    source: Span | None
    policy: str
    policy_version: str
    reason: str


@dataclass(frozen=True)
class PolicyDecision:
    """The policy engine's answer for one detected span.

    The policy engine holds no transformation logic; it only decides. A decision is data.
    """

    detected: str
    detected_kind: str
    source: Span
    transform_allowed: bool
    reason: str
    # S3 - set when the span was kept because stripping it could change whether the
    # request is harmful. The relevance gate is never asked to judge safety; for that
    # question the answer is always "keep it".
    safety_hold: bool = False


@dataclass(frozen=True)
class NeutralResult:
    """The complete, auditable outcome of one request through Neutral."""

    original_prompt: str
    processed_prompt: str
    # S2 - both responses are always stored and both are always shown to the user.
    original_response: str
    processed_response: str

    segments: tuple[Segment, ...] = ()
    transforms: tuple[TransformRecord, ...] = ()
    decisions: tuple[PolicyDecision, ...] = ()

    # S4 - true when any stage errored, timed out, or produced low-confidence output and
    # we therefore sent the original prompt unmodified.
    passthrough: bool = False
    passthrough_reason: str | None = None

    # S3 - true when the upstream model refused. The refusal is returned verbatim and is
    # never retried, rephrased or split up.
    refused: bool = False

    # Mechanism 4 is off by default and opt-in per request. When it is on the user is
    # told plainly that extra comparison material is being sent.
    comparison_framing_enabled: bool = False

    mechanisms_enabled: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)


def render(segments: tuple[Segment, ...] | list[Segment]) -> str:
    """Build the rewritten prompt from its segments."""
    return "".join(segment.text for segment in segments)
