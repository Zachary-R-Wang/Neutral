"""Multi-turn conversations.

One prompt is easy. A conversation adds a requirement that is not obvious until it breaks:
**the placeholders have to mean the same thing in every turn.** If "Emily" is Person A in
the first message and Person B in the third, the model is told a new person has joined,
and the answers stop making sense.

The obvious way to do that is to keep the name-to-placeholder map alive for the whole
conversation. S5 says the opposite: those mappings live for one request and are discarded.

So they are not kept. Instead, every turn re-derives the mapping from scratch over the
whole conversation at once - the user's turns joined into a single document, substituted
in one pass, then split apart again. Placeholders are assigned in order of first
appearance, so the same document always yields the same mapping. It is created, used, and
gone before the request returns, exactly as S5 requires, and it costs about six
milliseconds because detection runs locally.

Two conversations are kept in step, not one: what the model was asked without Neutral, and
what it was asked with it. That is what makes the comparison in the interface honest - both
answers come from the same conversation at the same point, not from different histories.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from neutral import errors
from neutral.core import TransformRecord
from neutral.detect import detect_names_local, find_pronouns
from neutral.invariants import InvariantViolation, verify_no_added_information
from neutral.mechanisms.identity_substitution import apply as substitute
from neutral.policy import decide, safety_hold
from neutral.restore import restore

# Chosen to contain no letters, so name detection cannot see a name across the join and no
# substitution can ever land on it.
SEPARATOR = "\n\n@@@@\n\n"


@dataclass
class Turn:
    """One exchange. Both answers are kept; the interface shows one and offers the other."""

    asked: str
    # What the user reads: the answer to the rewritten prompt, with names put back.
    answer: str = ""
    # What the model said to the prompt exactly as written. S2 - always retrievable.
    original_answer: str = ""
    # The answer in placeholder form. Not shown; it is what the model is given as history,
    # so its own context stays in the terms it was answering in.
    neutral_answer: str = ""
    changes: tuple[TransformRecord, ...] = ()
    untouched: bool = False
    note: str = ""
    failed: bool = False


@dataclass
class Conversation:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    turns: list[Turn] = field(default_factory=list)

    @property
    def started(self) -> bool:
        return bool(self.turns)


def _rewrite_all(prompts: list[str]) -> tuple[list[str], dict[str, str], dict[str, str], tuple]:
    """Rewrite every turn in one pass, so the placeholders agree across all of them.

    Returns the rewritten prompts, the name map, the pronoun style, and the audit records
    for the newest turn only - the earlier turns were already recorded when they happened.
    """
    joined = SEPARATOR.join(prompts)

    names = detect_names_local(joined)
    findings = sorted(names + find_pronouns(joined, names), key=lambda f: f.span.start)
    if not findings:
        return list(prompts), {}, {}, ()

    decisions = decide(joined, findings)
    allowed = {i for i, d in enumerate(decisions) if d.transform_allowed}
    result = substitute(joined, findings, allowed)
    rewritten = "".join(s.text for s in result.segments)

    # The same S1 proof the single-prompt path runs, before anything is sent.
    verify_no_added_information(joined, rewritten, result.segments)

    parts = rewritten.split(SEPARATOR)
    if len(parts) != len(prompts):
        # A split that does not line up means the separator was disturbed. Rather than
        # send something that might not correspond to what the user wrote, send nothing.
        raise InvariantViolation(
            "S1",
            "the rewritten conversation did not split back into the same number of turns",
            "Sending it would risk attributing one turn's text to another.",
        )

    # Only the final turn's changes are new; the rest were recorded when they were asked.
    last_start = len(SEPARATOR.join(prompts[:-1])) + (len(SEPARATOR) if len(prompts) > 1 else 0)
    newest = tuple(r for r in result.transforms if r.source and r.source.start >= last_start)
    return parts, result.identity_map, result.pronoun_style, newest


def ask(conversation: Conversation, prompt: str, adapter) -> Turn:
    """Add one turn. Two model calls: the prompt as written, and the rewritten one."""
    turn = Turn(asked=prompt)
    prompts = [t.asked for t in conversation.turns] + [prompt]

    original_history: list[tuple[str, str]] = []
    for past in conversation.turns:
        original_history.append(("user", past.asked))
        original_history.append(("assistant", past.original_answer or past.answer))

    # S2 first: whatever else fails, the unmodified answer exists.
    unmodified = adapter.complete(prompt, history=original_history)
    if unmodified.error:
        turn.failed = True
        turn.note = errors.user_message(unmodified.error_kind or errors.BAD_REQUEST)
        # No answer to show, but the rewriting is local and costs nothing, so show what
        # would have been removed rather than an empty turn.
        try:
            _, _, _, turn.changes = _rewrite_all(prompts)
        except Exception:  # noqa: BLE001
            pass
        conversation.turns.append(turn)
        return turn

    turn.original_answer = unmodified.text

    if unmodified.refused:
        turn.answer = unmodified.text
        turn.untouched = True
        turn.note = (
            "The model declined this request. Its refusal is shown exactly as given; "
            "the prompt was not rewritten, retried or resent."
        )
        conversation.turns.append(turn)
        return turn

    hold = safety_hold(prompt)
    if hold.held:
        turn.answer = unmodified.text
        turn.untouched = True
        turn.note = hold.reason
        conversation.turns.append(turn)
        return turn

    try:
        rewritten, identity_map, pronoun_style, changes = _rewrite_all(prompts)
    except (InvariantViolation, Exception):  # noqa: BLE001 - fail open to the original
        turn.answer = unmodified.text
        turn.untouched = True
        turn.note = (
            "The rewritten prompt could not be proved faithful to what you wrote, so your "
            "prompt was sent unchanged."
        )
        conversation.turns.append(turn)
        return turn

    # Nothing was found to change, so the rewritten prompt IS the prompt. Asking the
    # model the same question a second time would cost another call and return a
    # different answer - models do not repeat themselves - and the interface would show
    # two answers side by side as though Neutral had done something. It did not.
    if rewritten[-1] == prompt and not changes:
        turn.answer = unmodified.text
        turn.untouched = True
        turn.note = (
            "Nothing in this needed changing, so it went to the model exactly as you "
            "wrote it. There is only one answer because there was only one prompt."
        )
        conversation.turns.append(turn)
        return turn

    neutral_history: list[tuple[str, str]] = []
    for past, past_rewritten in zip(conversation.turns, rewritten[:-1], strict=False):
        neutral_history.append(("user", past_rewritten))
        neutral_history.append(("assistant", past.neutral_answer or past.answer))

    processed = adapter.complete(rewritten[-1], history=neutral_history)
    if processed.error or processed.refused:
        turn.answer = unmodified.text
        turn.untouched = True
        turn.note = (
            "The model declined the rewritten request, so the answer to your prompt as "
            "written is shown instead."
            if processed.refused
            else errors.user_message(processed.error_kind or errors.BAD_REQUEST)
        )
        conversation.turns.append(turn)
        return turn

    turn.neutral_answer = processed.text
    turn.answer = restore(processed.text, identity_map, pronoun_style)
    turn.changes = changes
    conversation.turns.append(turn)
    # identity_map is a local. It goes out of scope here, as S5 requires.
    return turn
