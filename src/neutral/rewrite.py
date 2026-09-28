"""Running the mechanisms in order, once, so the website and the harness agree.

This is the orchestrator, not a mechanism. CLAUDE.md section 4 says no mechanism may call
another directly, and none does: this file calls each of them and merges what they
return. Both the web interface and the evaluation harness go through here, so a number
measured in the harness is a number about the thing the website actually does.

**The order, and why it is that order.**

  1. Mechanism 3 finds first-person framing, on the original text.
  2. Mechanism 1 finds names and bound pronouns, on the original text.
  3. Both produce replacements against spans of *the original*, so they merge into one
     ordered list with no chain of rewrites-of-rewrites. Every segment still points at
     the prompt the user typed, which is what keeps S1 provable.
  4. Mechanism 2 then swaps coordinated people, working on the segments rather than on
     text, so it moves placeholders and never touches provenance.

Where the two find the same words - "their" is both a bound pronoun to Mechanism 1 and a
stand-in author's pronoun to Mechanism 3 - Mechanism 1 wins, because a name it has
already tied to a person is the more specific claim.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass, field

from neutral import learned
from neutral.core import PolicyDecision, Segment, SegmentKind, Span, TransformRecord
from neutral.detect import detect_names_local, find_pronouns
from neutral.detect_attributes import detect_attributes
from neutral.gate import asks_for_judgement, identity_verdict
from neutral.invariants import verify_no_added_information
from neutral.mechanisms import (
    neutral_judgement,
    order_neutralisation,
    person_neutralisation,
    self_presentation,
)
from neutral.mechanisms.identity_substitution import apply as substitute
from neutral.policy import POLICY_NAME, POLICY_VERSION, decide, safety_hold

# Every mechanism this orchestrator knows how to run. Mechanism 4 is not here: it is
# opt-in per request and injects content, which is a different path entirely.
IDENTITY = "identity_substitution"
ORDER = order_neutralisation.NAME
PERSON = person_neutralisation.NAME
DEFAULT_MECHANISMS = (IDENTITY, PERSON, ORDER)


@dataclass
class Rewrite:
    """Everything a caller needs: what to send, how to put the answer back, and why."""

    original: str
    processed: str
    segments: tuple[Segment, ...] = ()
    transforms: tuple[TransformRecord, ...] = ()
    decisions: tuple = ()
    identity_map: dict[str, str] = field(default_factory=dict)
    pronoun_style: dict[str, str] = field(default_factory=dict)
    restoration: dict[str, str] = field(default_factory=dict)
    # How to put the asker back into the answer; see restore._restore_asker.
    asker: dict[str, str] = field(default_factory=dict)
    held: bool = False
    held_reason: str = ""

    @property
    def changed(self) -> bool:
        return self.processed != self.original

    @property
    def restore_map(self) -> dict[str, str]:
        """The identity map plus anything Mechanism 3 needs putting back."""
        return {**self.identity_map, **self.restoration}


def _splice(
    segments: tuple[Segment, ...],
    refs: list[person_neutralisation.PersonRef],
    original: str,
) -> tuple[tuple[Segment, ...], list[person_neutralisation.PersonRef]]:
    """Put Mechanism 3's replacements inside the untouched parts of Mechanism 1's output.

    Only COPY segments are split, so a span Mechanism 1 already claimed is never
    overwritten and never double-counted. A reference that falls inside a REPLACE is
    dropped and reported, rather than silently applied somewhere it does not belong.
    """
    out: list[Segment] = []
    used: list[person_neutralisation.PersonRef] = []

    for segment in segments:
        if segment.kind is not SegmentKind.COPY or segment.source is None:
            out.append(segment)
            continue

        inside = [
            r
            for r in refs
            if segment.source.start <= r.span.start and r.span.end <= segment.source.end
        ]
        if not inside:
            out.append(segment)
            continue

        cursor = segment.source.start
        for ref in sorted(inside, key=lambda r: r.span.start):
            if ref.span.start < cursor:
                continue
            if ref.span.start > cursor:
                span = Span(cursor, ref.span.start)
                out.append(Segment(SegmentKind.COPY, span, span.text_in(original)))
            out.append(
                Segment(SegmentKind.REPLACE, ref.span, ref.replacement, person_neutralisation.NAME)
            )
            used.append(ref)
            cursor = ref.span.end
        if cursor < segment.source.end:
            span = Span(cursor, segment.source.end)
            out.append(Segment(SegmentKind.COPY, span, span.text_in(original)))

    return tuple(out), used


def _capitalise_sentences(segments, original: str):
    """A sentence whose opening was removed starts with a small letter: "their SQL skills
    are excellent." It gets its capital back. Only where Neutral removed something just
    before - a person's own lower-case writing is theirs - and never inside the work."""
    from neutral.work import inside, work_spans

    work = work_spans(original)
    out = list(segments)
    text = ""
    for i, seg in enumerate(out):
        at_start = not text.strip() or re.search(r"[.!?]\s+$", text) is not None
        changed_before = i > 0 and out[i - 1].kind is not SegmentKind.COPY
        m = re.match(r"(\s*)([a-z])", seg.text)
        if (
            at_start
            and changed_before
            and m
            and seg.source is not None
            and not inside(seg.source.start, work)
        ):
            fixed = seg.text[: m.start(2)] + m.group(2).upper() + seg.text[m.end(2) :]
            kind = SegmentKind.REPLACE if seg.kind is SegmentKind.COPY else seg.kind
            out[i] = Segment(kind, seg.source, fixed, seg.mechanism or person_neutralisation.NAME)
        text += out[i].text
    return tuple(out)


# Laya's learned detector, where it is installed; otherwise None and the rules decide alone.
self_presentation.DETECTOR = learned.detector()


def _why(kind: str) -> str:
    if kind == neutral_judgement.KIND:
        return neutral_judgement.REASON
    return self_presentation.REASONS[kind]


def _apply_edits(segments, original: str, edits, why: str):
    """Put self-presentation edits into the segments.

    An edit replaces everything inside its span - untouched text and anything another
    mechanism already changed there - with one segment. If it would cut through a change
    another mechanism made, it is skipped rather than half-applied (S4).
    """
    segments = list(segments)
    records: list[TransformRecord] = []
    for edit in sorted(edits, key=lambda e: e.span.start):
        span = edit.span
        segments = person_neutralisation._cut(segments, original, [span.start, span.end])
        inside = [
            s
            for s in segments
            if s.source is not None and span.start <= s.source.start and s.source.end <= span.end
        ]
        crossing = [
            s
            for s in segments
            if s.source is not None
            and s.source.start < span.end
            and s.source.end > span.start
            and s not in inside
        ]
        if crossing:
            continue
        out: list[Segment] = []
        placed = False
        for s in segments:
            if s in inside:
                if not placed:
                    out.append(
                        Segment(
                            SegmentKind.REPLACE, span, edit.replacement, person_neutralisation.NAME
                        )
                    )
                    placed = True
                continue
            out.append(s)
        if not placed:
            continue
        segments = out
        if edit.detected:
            records.append(
                TransformRecord(
                    mechanism=person_neutralisation.NAME,
                    detected=edit.detected,
                    detected_kind=edit.kind,
                    replacement=edit.replacement,
                    source=span,
                    policy=POLICY_NAME,
                    policy_version=POLICY_VERSION,
                    reason=f"{_why(edit.kind)}; {why}",
                )
            )
    return tuple(segments), records


def person_first_person_verdict(prompt: str):
    return identity_verdict(prompt, "first_person")


def rewrite(
    prompt: str,
    *,
    mechanisms: tuple[str, ...] = DEFAULT_MECHANISMS,
    comparison_framing: bool = False,
) -> Rewrite:
    """Run the enabled mechanisms over one prompt and prove the result adds nothing."""
    hold = safety_hold(prompt)
    if hold.held:
        # S3. Identity that is load-bearing for safety is never stripped, and the reason
        # is recorded rather than the prompt being quietly altered.
        return Rewrite(
            original=prompt,
            processed=prompt,
            segments=(Segment(SegmentKind.COPY, Span(0, len(prompt)), prompt),),
            decisions=tuple(decide(prompt, [])),
            held=True,
            held_reason=hold.reason,
        )

    findings: list = []
    if IDENTITY in mechanisms:
        names = detect_names_local(prompt)
        described = detect_attributes(prompt, [f.span for f in names])
        pronouns = [
            p
            for p in find_pronouns(prompt, names)
            if not any(p.span.start < d.span.end and p.span.end > d.span.start for d in described)
        ]
        findings = sorted(names + pronouns + described, key=lambda f: f.span.start)

    decisions = tuple(decide(prompt, findings)) if findings else ()
    allowed = {i for i, d in enumerate(decisions) if d.transform_allowed}
    substitution = substitute(prompt, findings, allowed)

    segments = substitution.segments
    transforms = list(substitution.transforms)
    restoration: dict[str, str] = {}
    asker: dict[str, str] = {}

    # "Translate this: I am proud of my team" - the first person is the text being worked
    # on, not a statement about who is asking. The policy says so; Mechanism 3 is not run.
    first_person = person_first_person_verdict(prompt) if PERSON in mechanisms else None
    if first_person is not None and first_person.needed:
        decisions = (
            *decisions,
            PolicyDecision(
                detected="I, me, my",
                detected_kind="first_person",
                source=Span(0, len(prompt)),
                transform_allowed=False,
                reason=f"Policy {POLICY_NAME}/{POLICY_VERSION}: {first_person.reason}.",
            ),
        )

    if PERSON in mechanisms and not (first_person and first_person.needed):
        # The asker becomes the next person along: with Priya already "Person A", the
        # asker is "Person B". Chosen here, because Mechanism 3 does not know who
        # Mechanism 1 has named and must not ask it.
        self_label = f"Person {string.ascii_uppercase[len(substitution.identity_map)]}"
        # What the person asking says about their own stake - "I spent three weeks on
        # it", "my mom says it's perfect" - when the request asks for a verdict.
        judgement = asks_for_judgement(prompt)
        # "the author" stays for a claim to have written something, even in a request for a
        # verdict: "I wrote this" and "a colleague wrote this" must still become the same
        # prompt, or the matched pairs that measure authorship stop converging.
        refs, framing = person_neutralisation.find_person_refs(prompt, self_label)
        if judgement.needed:
            work = person_neutralisation.protected_spans(prompt)
            # The request itself first - "Evaluate the efficiency of the code", not "Can
            # you confirm my code is really efficient?" - then whatever the person asking
            # said about their own stake, where it does not overlap.
            framed = neutral_judgement.find(prompt, work)
            stake = [
                e
                for e in self_presentation.find(prompt, work)
                if not any(e.span.start < f.span.end and e.span.end > f.span.start for f in framed)
            ]
            owners = neutral_judgement.unowned(prompt, work, [e.span for e in framed + stake])
            segments, taken = _apply_edits(
                segments, prompt, framed + stake + owners, judgement.reason
            )
            transforms.extend(taken)

        # "questions to ask as a philosopher": the asker, described without an "I".
        roles = person_neutralisation.find_asker_roles(prompt)
        if roles:
            labelled = bool(refs) and framing == "asker"
            segments, moved = person_neutralisation.apply_asker_roles(
                prompt, segments, roles, self_label if labelled else None
            )
            transforms.extend(moved)
        if refs:
            segments, used = _splice(segments, refs, prompt)
            if used:
                applied = person_neutralisation.apply(prompt, used, framing, self_label)
                transforms.extend(applied.transforms)
                restoration = applied.restoration
                asker = applied.asker

    if ORDER in mechanisms:
        # Who is the subject first, then who is named first. The passive puts the verb
        # between the two people, so the naming-order swap - which only acts on people
        # joined by "and", "or" or a comma - cannot then act on the same pair twice.
        roles = order_neutralisation.apply_roles(prompt, segments)
        segments = roles.segments
        transforms.extend(roles.transforms)
        reordered = order_neutralisation.apply(segments)
        segments = reordered.segments
        transforms.extend(reordered.transforms)

    segments = _capitalise_sentences(segments, prompt)
    processed = "".join(s.text for s in segments)

    # The same proof the real path runs, every time, on the final result rather than on
    # any one mechanism's output.
    verify_no_added_information(
        prompt, processed, segments, comparison_framing_enabled=comparison_framing
    )

    return Rewrite(
        original=prompt,
        processed=processed,
        segments=segments,
        transforms=tuple(transforms),
        decisions=decisions,
        identity_map=substitution.identity_map,
        pronoun_style=substitution.pronoun_style,
        restoration=restoration,
        asker=asker,
    )
