"""Mechanism 1 - identity substitution.

Personal names and the gendered pronouns bound to them are replaced with neutral,
consistent placeholders, so the model cannot condition on who the people are. Reversed on
the way out.

Two details matter more than they look.

**Names are grouped before they are replaced.** A prompt that says "Emily Carter" once and
"Emily" three times is talking about one person, and must produce one placeholder. Giving
those two spellings separate placeholders would tell the model there are two people, which
is inventing a fact - exactly what S1 forbids.

**Every character of the output is emitted as a segment.** Nothing is produced by string
replacement on the original. The rewritten prompt is built from segments that each declare
where they came from, so S1 can be proved by reconstruction rather than trusted.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass, field

from neutral.core import Segment, SegmentKind, Span, TransformRecord
from neutral.detect import TITLES, Finding
from neutral.policy import POLICY_NAME, POLICY_VERSION

MECHANISM = "identity_substitution"

NEUTRAL_PRONOUN = {
    "subject": "they",
    "object": "them",
    "possessive": "their",
    "possessive_noun": "theirs",
    "reflexive": "themselves",
}

_FORM = {
    "he": "subject",
    "she": "subject",
    "him": "object",
    "his": "possessive",
    "her": "ambiguous",
    "hers": "possessive_noun",
    "himself": "reflexive",
    "herself": "reflexive",
}

# "her" is two different words. After one of these, it is the object ("tell her", "for
# her"); before a noun it is possessive ("her review"). This is a heuristic, not grammar,
# and its failures are a Phase 3 problem - restoration quality - not a Phase 1 one.
_TAKES_OBJECT = {
    "tell",
    "told",
    "give",
    "gave",
    "ask",
    "asked",
    "offer",
    "offered",
    "show",
    "showed",
    "advise",
    "advised",
    "pay",
    "paid",
    "send",
    "sent",
    "help",
    "helped",
    "email",
    "to",
    "for",
    "with",
    "at",
    "by",
    "from",
    "about",
    "of",
    "on",
    "let",
    "made",
    "make",
}

_WORD = re.compile(r"\b[\w']+\b")


@dataclass
class Substitution:
    segments: tuple[Segment, ...] = ()
    transforms: tuple[TransformRecord, ...] = ()
    # placeholder -> the real name. In memory for one request only, then discarded (S5).
    identity_map: dict[str, str] = field(default_factory=dict)
    # placeholder -> which pronoun set the original used, so restoration can put it back.
    pronoun_style: dict[str, str] = field(default_factory=dict)


def _key(name: str) -> frozenset[str]:
    """The word-parts of a name, for deciding whether two spellings are one person.

    Titles are excluded. "Mr Smith" and "Mr Jones" share the word "mr" and nothing else;
    keeping it would merge two people into one placeholder, which tells the model they
    are the same person - inventing a fact rather than removing one.
    """
    cleaned = name.strip(string.punctuation + string.whitespace)
    cleaned = re.sub(r"'s$", "", cleaned, flags=re.I)
    return frozenset(
        w.lower() for w in _WORD.findall(cleaned) if len(w) > 1 and w.lower() not in TITLES
    )


def group_people(findings: list[Finding]) -> dict[int, str]:
    """Map each name finding to a placeholder, merging spellings of the same person."""
    groups: list[set[str]] = []
    assignment: dict[int, int] = {}

    for index, finding in enumerate(findings):
        if finding.kind != "person_name":
            continue
        key = _key(finding.text)
        if not key:
            continue
        for group_index, group in enumerate(groups):
            if key & group:
                group |= key
                assignment[index] = group_index
                break
        else:
            groups.append(set(key))
            assignment[index] = len(groups) - 1

    labels = {g: f"Person {string.ascii_uppercase[g]}" for g in range(len(groups))}
    return {i: labels[g] for i, g in assignment.items()}


def _pronoun_replacement(prompt: str, span: Span, word: str) -> str:
    form = _FORM.get(word.lower(), "subject")
    if form == "ambiguous":
        before = _WORD.findall(prompt[: span.start])
        previous = before[-1].lower() if before else ""
        after = prompt[span.end :].lstrip()
        form = "object" if previous in _TAKES_OBJECT or not after[:1].isalpha() else "possessive"
    replacement = NEUTRAL_PRONOUN[form]
    return replacement.capitalize() if word[:1].isupper() else replacement


def apply(prompt: str, findings: list[Finding], allowed: set[int]) -> Substitution:
    """Rewrite the allowed spans, emitting a segment for every character of the result."""
    people = group_people(findings)
    segments: list[Segment] = []
    transforms: list[TransformRecord] = []
    identity_map: dict[str, str] = {}
    pronoun_style: dict[str, str] = {}

    cursor = 0
    for index, finding in enumerate(findings):
        if index not in allowed:
            continue
        span = finding.span
        if span.start < cursor:
            continue

        if span.start > cursor:
            untouched = Span(cursor, span.start)
            segments.append(Segment(SegmentKind.COPY, untouched, untouched.text_in(prompt)))

        if finding.kind == "person_name":
            placeholder = people.get(index, "Person A")
            trailing = "'s" if re.search(r"'s$", finding.text, re.I) else ""
            replacement = placeholder + trailing
            identity_map.setdefault(placeholder, finding.text.rstrip("'s").rstrip("'"))
            reason = "a personal name carries ethnicity, gender and social expectation"
        else:
            replacement = _pronoun_replacement(prompt, span, finding.text)
            placeholder = ""
            reason = "a gendered pronoun states the gender of the person it refers to"
            pronoun_style["*"] = (
                "feminine"
                if finding.text.lower() in ("she", "her", "hers", "herself")
                else "masculine"
            )

        segments.append(Segment(SegmentKind.REPLACE, span, replacement, MECHANISM))
        transforms.append(
            TransformRecord(
                mechanism=MECHANISM,
                detected=finding.text,
                detected_kind=finding.kind,
                replacement=replacement,
                source=span,
                policy=POLICY_NAME,
                policy_version=POLICY_VERSION,
                reason=reason,
            )
        )
        cursor = span.end

    if cursor < len(prompt):
        tail = Span(cursor, len(prompt))
        segments.append(Segment(SegmentKind.COPY, tail, tail.text_in(prompt)))

    return Substitution(
        segments=tuple(segments),
        transforms=tuple(transforms),
        identity_map=identity_map,
        pronoun_style=pronoun_style,
    )
