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

import string
from dataclasses import dataclass, field

from neutral.core import PolicyDecision, Segment, SegmentKind, Span, TransformRecord
from neutral.detect import detect_names_local, find_pronouns
from neutral.detect_attributes import detect_attributes
from neutral.gate import identity_verdict
from neutral.invariants import verify_no_added_information
from neutral.mechanisms import order_neutralisation, person_neutralisation
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
        pronouns = find_pronouns(prompt, names)
        described = detect_attributes(prompt, [f.span for f in names + pronouns])
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
        refs, framing = person_neutralisation.find_person_refs(prompt, self_label)
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
