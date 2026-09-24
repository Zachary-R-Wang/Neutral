"""Stage 1 - DETECT. Find the spans in a prompt that carry identity signal.

Detection only finds things. It never decides what to do about them; that is the policy
engine's job, and keeping the two apart is what CLAUDE.md section 4 means by separating
policy from execution.

Phase 1 detects personal names and the pronouns bound to them, and nothing else.

How detection works, and why: a model is asked to list the names, with a fixed prompt and
a structured reply. The obvious alternative - a rule that treats capitalised words as
names - misfires constantly on ordinary prompts ("Senior", "Monday", "Sev-1", "HR"), and
every misfire means a real word replaced by a placeholder in the text sent onward.

Everything the model returns is then verified against the original text. A span it claims
that cannot be found verbatim is discarded rather than trusted. That check is what keeps a
detector hallucination from becoming an S1 violation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

from neutral.core import Span

DETECT_SYSTEM = """You identify personal names in text. You do not rewrite anything.

Return every span that identifies a specific person:
  - personal names, given or family or both, exactly as they are written
  - possessive forms, such as "Emily's"

Do NOT return:
  - job titles, team names, company names, product names
  - days, months, places, or any other capitalised word that is not a person's name
  - pronouns - those are handled separately
  - a name that appears inside a quoted passage being assessed, where it belongs to
    someone other than a participant

Copy each span exactly as it appears, character for character. Do not correct spelling,
expand abbreviations, or change capitalisation. If there are no personal names, return an
empty list."""


class DetectedSpan(BaseModel):
    text: str = Field(description="The span exactly as it appears in the prompt.")
    kind: str = Field(description="Always 'person_name' at this phase.")


class Detection(BaseModel):
    spans: list[DetectedSpan] = Field(description="Every personal name found.")


@dataclass(frozen=True)
class Finding:
    """One detected span, verified to exist at this exact position in the original."""

    span: Span
    text: str
    kind: str


# Pronouns are resolved by rule, not by the model: the set is closed, and a closed set is
# better served by a lookup than by a model that might return something outside it.
PRONOUNS = {
    "he": "they",
    "him": "them",
    "his": "their",
    "himself": "themselves",
    "she": "they",
    "her": "them",
    "hers": "theirs",
    "herself": "themselves",
}

_WORD = re.compile(r"\b\w+(?:'\w+)?\b")


def verify(prompt: str, claimed: list[DetectedSpan]) -> list[Finding]:
    """Keep only the spans that genuinely appear in the prompt, at a real position.

    A detector that invents a span would otherwise let the transform stage replace text
    that was never there, which is how a rewrite stops being traceable to its source.
    """
    findings: list[Finding] = []
    taken: list[tuple[int, int]] = []

    for item in sorted(claimed, key=lambda s: len(s.text), reverse=True):
        if not item.text.strip():
            continue
        for match in re.finditer(re.escape(item.text), prompt):
            start, end = match.start(), match.end()
            if any(start < t_end and end > t_start for t_start, t_end in taken):
                continue
            findings.append(Finding(Span(start, end), item.text, item.kind))
            taken.append((start, end))

    return sorted(findings, key=lambda f: f.span.start)


def find_pronouns(prompt: str, skip: list[Finding]) -> list[Finding]:
    """Gendered pronouns, by lookup. Spans already claimed by a name are left alone."""
    claimed = [(f.span.start, f.span.end) for f in skip]
    findings = []
    for match in _WORD.finditer(prompt):
        word = match.group(0)
        if word.lower() not in PRONOUNS:
            continue
        start, end = match.start(), match.end()
        if any(start < c_end and end > c_start for c_start, c_end in claimed):
            continue
        findings.append(Finding(Span(start, end), word, "pronoun"))
    return findings


def detect_names(prompt: str, adapter) -> tuple[list[Finding], str | None]:
    """Find personal names. Returns (findings, error).

    An error is returned rather than raised: S4 requires the caller to fail open to the
    original prompt, and it cannot do that if detection throws.
    """
    parsed, completion = adapter.parse(
        f"Find the personal names in the text below.\n\n---\n{prompt}\n---",
        Detection,
        system=DETECT_SYSTEM,
    )
    if parsed is None:
        return [], completion.error or "the name detector did not return a usable answer"
    return verify(prompt, parsed.spans), None
