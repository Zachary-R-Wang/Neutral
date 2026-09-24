"""Stage 2 - DECIDE. Whether a detected span may be transformed.

The policy engine holds no transformation logic, and the transformers hold no policy.
This file decides; it never rewrites. A decision is data - a record of what was found,
what was allowed, and why - so that S7's audit trail is a by-product of deciding rather
than something bolted on afterwards.

Phase 1 has no relevance gate: CLAUDE.md section 5 says substitute every detected name.
But S3 is not part of the relevance gate and never was. It sits in front of everything,
and it is absolute:

    "If stripping an attribute would change whether a request is harmful, do not strip
     it - pass the prompt through unmodified and log the decision."
    "The relevance classifier's job is deciding whether an attribute is load-bearing for
     the TASK. It is never given the job of deciding whether an attribute is load-bearing
     for SAFETY - for that question the answer is always yes, keep it."

So the safety layer here is deliberately crude and deliberately over-broad. It is a list
of signals that, when present, stop Neutral touching the prompt at all. It will hold
prompts that would have been perfectly safe to rewrite. That is the intended direction to
be wrong in: a held prompt costs a missed rewrite, a stripped one can cost far more.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from neutral.core import PolicyDecision
from neutral.detect import Finding

POLICY_NAME = "hr-default"
POLICY_VERSION = "v1"

# An age below this, stated anywhere in the prompt, stops Neutral entirely.
ADULT_AGE = 18

_AGE_PATTERNS = (
    re.compile(r"\b(\d{1,2})[\s-]*(?:years?[\s-]*old|yo|y/o)\b", re.I),
    re.compile(r"\b(?:aged|age)[\s:]*(\d{1,2})\b", re.I),
    re.compile(r"\b(\d{1,2})[\s-]*year[\s-]*old\b", re.I),
)

# Words that make a request's safety depend on who is involved. Crude on purpose.
_SAFETY_TERMS = {
    "minors": (
        "child",
        "children",
        "kid",
        "kids",
        "teen",
        "teenager",
        "teenage",
        "minor",
        "minors",
        "schoolgirl",
        "schoolboy",
        "toddler",
        "infant",
        "baby",
        "underage",
        "pupil",
        "student",
    ),
    "health": (
        "diagnosis",
        "diagnosed",
        "symptom",
        "symptoms",
        "medication",
        "dosage",
        "dose",
        "prescription",
        "overdose",
        "psychiatric",
        "therapy",
        "therapist",
        "suicide",
        "self-harm",
        "pregnant",
        "pregnancy",
        "disability",
        "disabled",
        "illness",
    ),
    "legal": (
        "arrest",
        "arrested",
        "custody",
        "immigration",
        "deportation",
        "visa",
        "asylum",
        "convicted",
        "conviction",
        "probation",
        "restraining",
        "abuse",
        "assault",
        "harassment",
        "violence",
    ),
    "restricted": (
        "alcohol",
        "drugs",
        "weapon",
        "gun",
        "firearm",
        "explosive",
        "sexual",
        "porn",
    ),
}

_WORD = re.compile(r"[a-z][a-z'\-]*", re.I)


@dataclass(frozen=True)
class SafetyHold:
    held: bool
    reason: str
    triggers: tuple[str, ...] = ()


def safety_hold(prompt: str) -> SafetyHold:
    """Decide whether identity is load-bearing for SAFETY in this prompt.

    Returns held=True on any signal. There is no confidence score and no threshold,
    because a threshold is a place to later argue for a lower one.
    """
    triggers: list[str] = []

    for pattern in _AGE_PATTERNS:
        for match in pattern.finditer(prompt):
            try:
                age = int(match.group(1))
            except (IndexError, ValueError):
                continue
            if age < ADULT_AGE:
                triggers.append(f"an age below {ADULT_AGE} is stated ({match.group(0)!r})")

    words = {w.lower() for w in _WORD.findall(prompt)}
    for category, terms in _SAFETY_TERMS.items():
        hits = sorted(words & set(terms))
        if hits:
            triggers.append(f"{category}: {', '.join(hits[:4])}")

    if triggers:
        return SafetyHold(
            True,
            "Identity may be load-bearing for whether this request is safe to answer, so "
            "the prompt was sent to the model exactly as written. " + "; ".join(triggers),
            tuple(triggers),
        )
    return SafetyHold(False, "")


def decide(prompt: str, findings: list[Finding]) -> list[PolicyDecision]:
    """One decision per detected span, with the reason recorded either way."""
    hold = safety_hold(prompt)

    decisions = []
    for finding in findings:
        if hold.held:
            decisions.append(
                PolicyDecision(
                    detected=finding.text,
                    detected_kind=finding.kind,
                    source=finding.span,
                    transform_allowed=False,
                    reason=hold.reason,
                    safety_hold=True,
                )
            )
        else:
            decisions.append(
                PolicyDecision(
                    detected=finding.text,
                    detected_kind=finding.kind,
                    source=finding.span,
                    transform_allowed=True,
                    reason=(
                        f"Phase 1 policy {POLICY_NAME}/{POLICY_VERSION}: every detected "
                        f"name is substituted, with no relevance gate yet. No safety "
                        f"signal was present in this prompt."
                    ),
                    safety_hold=False,
                )
            )
    return decisions
