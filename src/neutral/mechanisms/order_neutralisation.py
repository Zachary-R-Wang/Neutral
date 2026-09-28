"""Mechanism 2 - order neutralisation.

CLAUDE.md section 7: *"When a prompt compares two or more people, the order in which they
appear leaks which one the user identifies with. Randomise or alternate the order, and
ensure restoration maps the answer back to the true order."*

**Where the leak is.** "Should we promote Priya or Greg?" tells the model more than the
two names. People put themselves, their candidate, or their preferred answer first.
Mechanism 1 removes who they are; it leaves where they are.

**What this does and what it does not.** It swaps people who appear as a coordinated pair
- two references with nothing between them but "and", "or", "versus" or a comma. That is
where order is most visible and where a swap is provably safe, because the two references
are interchangeable by construction: exchanging them cannot change what any other part of
the sentence refers to.

It does not reorder paragraphs. A prompt that describes one candidate for three sentences
and then the other also leaks order, and rearranging free-form prose is not something
this can do without risking a prompt that no longer makes sense. S4 says a half-rewritten
prompt is worse than no rewriting, so that case is left alone rather than guessed at.

**Why the coin is flipped from the rewritten text.** Always reversing does not remove a
position effect, it inverts it. Randomising per call would make two runs of the same
prompt differ for a reason that has nothing to do with the question. So the decision is
seeded from the prompt *after* Mechanism 1 has run - at which point two prompts that
differ only in identity are identical, and therefore get the same decision. The order
varies from prompt to prompt, never between two people being compared on the same one.

**Restoration needs nothing.** The swap moves placeholders, not identities: "Person A"
still means whoever it meant. The existing map puts the right name back wherever it ends
up, which is why this mechanism has no restoration table of its own.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from neutral.core import Segment, SegmentKind, Span, TransformRecord
from neutral.policy import POLICY_NAME, POLICY_VERSION

NAME = "order_neutralisation"

# What may sit between two references for them to count as a coordinated pair. Anything
# longer is prose, and prose may carry meaning that a swap would break.
_COORDINATOR = re.compile(r"^\s*(?:,\s*)?(?:and|or|versus|vs\.?|&)?\s*$", re.I)


@dataclass
class Reordering:
    segments: tuple[Segment, ...] = ()
    transforms: tuple[TransformRecord, ...] = ()
    swapped: int = 0


def _coin(text: str) -> bool:
    """A stable coin flip for this prompt. Same text, same answer, always."""
    digest = hashlib.sha256(text.encode()).digest()
    return digest[0] & 1 == 1


# Mechanism 1 also rewrites verbs so they agree with "they" ("takes" -> "take"). Those are
# its segments too, and are not people; only a placeholder or a pronoun is.
_PERSON_TEXT = re.compile(r"(?:Person [A-Z]|they|them|their|theirs|themselves)(?:'s)?", re.I)


def _is_person(segment: Segment) -> bool:
    return (
        segment.kind is SegmentKind.REPLACE
        and segment.mechanism == "identity_substitution"
        and _PERSON_TEXT.fullmatch(segment.text) is not None
    )


def apply(segments: tuple[Segment, ...]) -> Reordering:
    """Swap coordinated pairs of people, or leave everything exactly as it was."""
    segments = tuple(segments)
    rewritten = "".join(s.text for s in segments)
    if not _coin(rewritten):
        # Heads: this prompt keeps its original order. Half of them must, or the order
        # is still a fixed function of what the user wrote.
        return Reordering(segments=segments)

    out = list(segments)
    transforms: list[TransformRecord] = []
    swapped = 0

    index = 0
    while index + 2 < len(out):
        left, middle, right = out[index], out[index + 1], out[index + 2]
        if (
            _is_person(left)
            and _is_person(right)
            and middle.kind is SegmentKind.COPY
            and _COORDINATOR.match(middle.text)
            and left.text != right.text
        ):
            # Only the text moves. Each segment keeps its own source span, so every
            # character is still traceable to where it came from and S1 holds.
            out[index] = Segment(left.kind, left.source, right.text, left.mechanism)
            out[index + 2] = Segment(right.kind, right.source, left.text, right.mechanism)
            transforms.append(
                TransformRecord(
                    mechanism=NAME,
                    detected=f"{left.text}{middle.text}{right.text}",
                    detected_kind="coordinated_pair",
                    replacement=f"{right.text}{middle.text}{left.text}",
                    source=left.source,
                    policy=POLICY_NAME,
                    policy_version=POLICY_VERSION,
                    reason=(
                        "the order two people are named in leaks which one the asker "
                        "identifies with"
                    ),
                )
            )
            swapped += 1
            index += 3
            continue
        index += 1

    return Reordering(segments=tuple(out), transforms=tuple(transforms), swapped=swapped)


# ---------------------------------------------------------------------------
# Who is the subject
# ---------------------------------------------------------------------------
#
# The founder's point: order is not only who is named first but who is cast as the doer.
# "Should Priya replace Greg?" puts Priya in charge of the sentence.
#
# Swapping the roles would change the facts - "Should Greg replace Priya?" is a different
# question, and Neutral would hand back an answer about the wrong person. S1 forbids that
# and so does the rule that no answer may discuss the wrong subject. What can change
# without changing the facts is the grammar: "Should Greg be replaced by Priya?" asks the
# same thing with Greg as the subject. That is what this does, on the same kind of coin as
# the naming order, so which person leads the sentence stops being the asker's choice.
#
# It is deliberately narrow. It fires only when the parser is unambiguous that one person
# acts directly on another, with a verb whose passive form is listed below rather than
# guessed at. Anything else - "reports to", "took over from", a negation, a perfect tense,
# a question the parser reads wrongly - is left exactly as written. S4 says a
# half-rewritten prompt is worse than none.

# Base form -> past participle, for verbs where one person commonly acts on another at
# work. A verb not listed is never passivised: an invented participle would be a mangled
# prompt.
PARTICIPLES = {
    "advise": "advised",
    "appoint": "appointed",
    "assess": "assessed",
    "beat": "beaten",
    "blame": "blamed",
    "choose": "chosen",
    "coach": "coached",
    "credit": "credited",
    "criticise": "criticised",
    "criticize": "criticized",
    "demote": "demoted",
    "discipline": "disciplined",
    "dismiss": "dismissed",
    "endorse": "endorsed",
    "evaluate": "evaluated",
    "favour": "favoured",
    "favor": "favored",
    "fire": "fired",
    "help": "helped",
    "hire": "hired",
    "ignore": "ignored",
    "interrupt": "interrupted",
    "interview": "interviewed",
    "lead": "led",
    "manage": "managed",
    "mentor": "mentored",
    "micromanage": "micromanaged",
    "mislead": "misled",
    "nominate": "nominated",
    "onboard": "onboarded",
    "outperform": "outperformed",
    "outrank": "outranked",
    "overlook": "overlooked",
    "overrule": "overruled",
    "overtake": "overtaken",
    "pay": "paid",
    "pick": "picked",
    "praise": "praised",
    "prefer": "preferred",
    "promote": "promoted",
    "rank": "ranked",
    "rate": "rated",
    "recommend": "recommended",
    "recruit": "recruited",
    "replace": "replaced",
    "reprimand": "reprimanded",
    "retain": "retained",
    "review": "reviewed",
    "reward": "rewarded",
    "select": "selected",
    "sponsor": "sponsored",
    "succeed": "succeeded",
    "supervise": "supervised",
    "support": "supported",
    "teach": "taught",
    "thank": "thanked",
    "train": "trained",
    "trust": "trusted",
    "underpay": "underpaid",
    "undermine": "undermined",
    "warn": "warned",
}

# What goes in front of the participle, by the tense the verb was in.
_AUXILIARY = {"VB": "be", "VBD": "was", "VBZ": "is"}


def _carve(segments: list[Segment], cuts: set[int], original: str) -> list[Segment]:
    """Split COPY segments so every offset in `cuts` falls on a segment boundary."""
    out: list[Segment] = []
    for segment in segments:
        if segment.kind is not SegmentKind.COPY or segment.source is None:
            out.append(segment)
            continue
        inside = sorted(c for c in cuts if segment.source.start < c < segment.source.end)
        if not inside:
            out.append(segment)
            continue
        edges = [segment.source.start, *inside, segment.source.end]
        for start, end in zip(edges, edges[1:], strict=False):
            span = Span(start, end)
            out.append(Segment(SegmentKind.COPY, span, span.text_in(original)))
    return out


def _person_span(token, people: list[Span]) -> Span | None:
    """The substituted person whose span contains this parsed token, if any."""
    for span in people:
        if span.start <= token.idx and token.idx + len(token.text) <= span.end:
            return span
    return None


def apply_roles(original: str, segments, *, flip: bool | None = None) -> Reordering:
    """Put the person acted upon in the subject position, on the coin, or leave it.

    `flip` forces the coin for tests; left as None it is seeded from the rewritten text,
    salted so it is not simply the same toss as the naming order.
    """
    segments = tuple(segments)
    if flip is None:
        flip = _coin("".join(s.text for s in segments) + "\x00roles")
    if not flip:
        return Reordering(segments=segments)

    from neutral.detect import _model

    nlp = _model()
    if nlp is None:
        # Rules alone cannot tell a doer from a receiver. Leave it.
        return Reordering(segments=segments)

    people = [s.source for s in segments if _is_person(s) and s.source is not None]
    if len(people) < 2:
        return Reordering(segments=segments)

    out = list(segments)
    transforms: list[TransformRecord] = []
    for verb in nlp(original):
        if verb.tag_ not in _AUXILIARY or verb.lemma_.lower() not in PARTICIPLES:
            continue
        children = list(verb.children)
        subjects = [c for c in children if c.dep_ == "nsubj"]
        objects = [c for c in children if c.dep_ == "dobj"]
        auxes = [c for c in children if c.dep_ in ("aux", "auxpass")]
        if len(subjects) != 1 or len(objects) != 1:
            continue
        if any(c.dep_ in ("neg", "prt", "dative", "ccomp", "xcomp") for c in children):
            continue
        # A bare verb needs exactly one modal to carry it ("should replace"); a past or
        # present verb must have none ("has replaced" and "is replacing" are left alone).
        if verb.tag_ == "VB" and not (len(auxes) == 1 and auxes[0].tag_ == "MD"):
            continue
        if verb.tag_ != "VB" and auxes:
            continue

        doer = _person_span(subjects[0], people)
        receiver = _person_span(objects[0], people)
        if doer is None or receiver is None or doer == receiver:
            continue
        if not doer.end <= verb.idx < receiver.start:
            continue

        # Everything between the two people must be the verb, one modal, and spaces.
        between = original[doer.end : receiver.start]
        expected = {verb.text.lower()} | {a.text.lower() for a in auxes}
        if not set(between.lower().split()) <= expected:
            continue

        verb_span = Span(verb.idx, verb.idx + len(verb.text))
        out = _carve(out, {verb_span.start, verb_span.end}, original)
        at_doer = next(
            i for i, s in enumerate(out) if s.kind is SegmentKind.REPLACE and s.source == doer
        )
        at_receiver = next(
            i for i, s in enumerate(out) if s.kind is SegmentKind.REPLACE and s.source == receiver
        )
        at_verb = next(
            (i for i, s in enumerate(out) if s.kind is SegmentKind.COPY and s.source == verb_span),
            None,
        )
        if at_verb is None or not at_doer < at_verb < at_receiver:
            continue
        # Nothing else may have been rewritten inside the clause.
        if any(out[i].kind is not SegmentKind.COPY for i in range(at_doer + 1, at_receiver)):
            continue

        before = "".join(s.text for s in out[at_doer : at_receiver + 1])
        passive = f"{_AUXILIARY[verb.tag_]} {PARTICIPLES[verb.lemma_.lower()]} by"
        if verb.text[0].isupper():
            passive = passive[0].upper() + passive[1:]
        doer_seg, receiver_seg = out[at_doer], out[at_receiver]
        # Placeholders move; each segment keeps its own source, as with the naming order.
        out[at_doer] = Segment(
            doer_seg.kind, doer_seg.source, receiver_seg.text, doer_seg.mechanism
        )
        out[at_receiver] = Segment(
            receiver_seg.kind, receiver_seg.source, doer_seg.text, receiver_seg.mechanism
        )
        out[at_verb] = Segment(SegmentKind.REPLACE, verb_span, passive, NAME)
        after = "".join(s.text for s in out[at_doer : at_receiver + 1])
        transforms.append(
            TransformRecord(
                mechanism=NAME,
                detected=before,
                detected_kind="subject_object",
                replacement=after,
                source=Span(doer.start, receiver.end),
                policy=POLICY_NAME,
                policy_version=POLICY_VERSION,
                reason=(
                    "which person is the grammatical subject leaks who the asker puts in "
                    "charge; the passive keeps who did what and moves the other to the front"
                ),
            )
        )

    return Reordering(segments=tuple(out), transforms=tuple(transforms), swapped=len(transforms))
