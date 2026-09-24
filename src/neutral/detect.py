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


# --------------------------------------------------------------------------------------
# Offline detection
# --------------------------------------------------------------------------------------

# Capitalised words that are not people. Far from complete, and it does not need to be:
# this path exists so the rewriting can be shown without calling a model, not so it can
# be relied on.
_NOT_NAMES = frozenset(
    """monday tuesday wednesday thursday friday saturday sunday january february march
    april may june july august september october november december senior junior lead
    principal staff director manager engineer engineering designer design product sales
    marketing finance legal hr operations ops support team teams company north south east
    west api apis sql python java sev ceo cto coo cfo vp svp evp phd mba english spanish
    french german write writing review reviews notes rate please assess draft summary
    section quarter q1 q2 q3 q4 the this that these those they their there here when what
    how why should would could must
    give given tell explain describe list provide consider imagine suppose create make
    help can does did is are was were i we you my our your if as at in on for with an and
    but or so then now also however based using it its from about after before during
    while because although unless until since each every some any all both either neither
    one two three first second third last next previous another other same different
    following above below here yes no ok okay thanks thank hello hi dear regards sincerely
    imagine assume note draft edit revise improve shorten lengthen compare contrast""".split()
) | set(PRONOUNS)  # a pronoun is never a name; they are found by lookup instead

_CANDIDATE = re.compile(r"\b[A-Z][a-z]{1,}(?:'s)?(?:\s+[A-Z][a-z]{1,}(?:'s)?){0,2}\b")
_SENTENCE_START = re.compile(r"(?:^|[.!?]\s+|\n\s*(?:[-*]\s*)?)$")


def detect_names_offline(prompt: str) -> list[Finding]:
    """Find likely personal names with rules only, making no network call.

    This is deliberately not the detector the product uses. Capitalisation is a poor
    signal for names in English and this will both miss real ones and flag words that are
    not names. It exists so the interface can show what Neutral does to a prompt when
    there is no API credit, clearly labelled as an approximation.
    """
    findings: list[Finding] = []
    for match in _CANDIDATE.finditer(prompt):
        text = match.group(0)
        parts = text.split()
        # re.sub, not strip: "Operations".strip("'s") is "Operation", which then misses a
        # stoplist entry spelled "operations".
        plain = [re.sub(r"'s$", "", w).lower() for w in parts]

        # Trim stopwords off each end rather than rejecting the whole candidate. Without
        # this, "Tell Mark how..." loses Mark because Tell opens the sentence.
        first, last = 0, len(parts)
        while first < last and plain[first] in _NOT_NAMES:
            first += 1
        while last > first and plain[last - 1] in _NOT_NAMES:
            last -= 1
        if first >= last:
            continue

        kept = " ".join(parts[first:last])
        offset = match.start() + len(text) - len(text.lstrip()) if first == 0 else None
        if offset is None:
            offset = match.start() + text.index(
                parts[first], sum(len(p) + 1 for p in parts[:first]) - 1 if first else 0
            )
        start = prompt.index(kept, match.start(), match.end())
        findings.append(Finding(Span(start, start + len(kept)), kept, "person_name"))
    return findings
