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

from neutral.core import Segment, SegmentKind, TransformRecord
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


def _is_person(segment: Segment) -> bool:
    return segment.kind is SegmentKind.REPLACE and segment.mechanism == "identity_substitution"


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
