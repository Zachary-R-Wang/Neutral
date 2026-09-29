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

**One model call per turn.** The control under an answer reveals the same reply with the
placeholders still in it - what the model actually wrote, before names were put back. That
shows exactly what Neutral did and costs nothing extra.

CLAUDE.md S2 asks for something different: the answer the model would have given to the
raw prompt, which means asking twice. The evaluation harness needs that, because comparing
the two is the entire measurement. A person having a conversation does not, and charging
them double for a comparison they did not ask for is not transparency. The eval path in
neutral/pipeline.py still sends both; this one does not. See DECISIONS.md, 2026-09-24.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from neutral import errors
from neutral.core import TransformRecord
from neutral.invariants import InvariantViolation
from neutral.policy import safety_hold
from neutral.restore import restore
from neutral.rewrite import rewrite
from neutral.work import TURN_SEPARATOR

# Chosen to contain no letters, so name detection cannot see a name across the join and no
# substitution can ever land on it.
SEPARATOR = TURN_SEPARATOR


@dataclass
class Turn:
    """One exchange, from one model call.

    The interface shows `answer` and offers `neutral_answer` behind a control. They are
    the same reply: one before names were put back, one after. Nothing is asked twice.
    """

    asked: str
    # What the user reads: the model's reply with names and pronouns restored.
    answer: str = ""
    # The same reply as the model wrote it, with placeholders still in place. This is what
    # the control below an answer reveals - it shows what Neutral did, at no extra cost.
    neutral_answer: str = ""
    # Only set when the prompt went to the model untouched, in which case it is the same
    # text as `answer` and there is nothing to compare.
    original_answer: str = ""
    # Word for word what the model received for this turn, so the person can see what
    # Neutral did to their prompt (CLAUDE.md §5, Phase 5). In memory only, like `asked`.
    sent: str = ""
    changes: tuple[TransformRecord, ...] = ()
    # What Neutral found and deliberately left, with why: ("67-year-old", "the request is
    # about the law"). Without it, a description the task needed looked like one missed.
    kept: tuple[tuple[str, str], ...] = ()
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


def _rewrite_all(
    prompts: list[str],
) -> tuple[list[str], dict[str, str], dict[str, str], tuple, dict[str, str]]:
    """Rewrite every turn in one pass, so the placeholders agree across all of them.

    Goes through neutral.rewrite, which is the same orchestrator the evaluation harness
    measures. Returns the rewritten prompts, the map for putting the answer back, the
    pronoun style, and the audit records for the newest turn only - the earlier turns
    were already recorded when they happened.
    """
    joined = SEPARATOR.join(prompts)
    done = rewrite(joined)

    if not done.changed:
        return list(prompts), {}, {}, (), {}

    parts = done.processed.split(SEPARATOR)
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
    newest = tuple(r for r in done.transforms if r.source and r.source.start >= last_start)
    return parts, done.identity_map, done.pronoun_style, newest, done.asker


def _kept(prompt: str) -> tuple[tuple[str, str], ...]:
    """What the relevance gate found in this prompt and chose to leave, and why."""
    try:
        decisions = rewrite(prompt).decisions
    except Exception:  # noqa: BLE001 - an explanation is not worth failing a turn over
        return ()
    out: list[tuple[str, str]] = []
    for d in decisions:
        if d.transform_allowed or d.safety_hold:
            continue
        why = d.reason.split("kept: ", 1)[-1].rstrip(".")
        if (d.detected, why) not in out:
            out.append((d.detected, why))
    return tuple(out)


def ask(conversation: Conversation, prompt: str, adapter) -> Turn:
    """Add one turn. Two model calls: the prompt as written, and the rewritten one."""
    turn = Turn(asked=prompt)
    prompts = [t.asked for t in conversation.turns] + [prompt]

    def send_unchanged(note: str, *, refused: bool = False) -> Turn:
        """Send the prompt as written. Used when there is nothing safe or useful to change."""
        history = [
            part
            for past in conversation.turns
            if past.answer
            for part in (("user", past.asked), ("assistant", past.answer))
        ]
        reply = adapter.complete(prompt, history=history)
        if reply.error:
            turn.failed = True
            print(f"[model] {reply.error_kind or 'error'}: {reply.error}")
            turn.note = errors.user_message(reply.error_kind or errors.BAD_REQUEST)
        else:
            turn.answer = reply.text
            turn.original_answer = reply.text
            turn.untouched = True
            turn.note = (
                "The model declined this request. Its refusal is shown exactly as given; "
                "it was not rewritten, retried or resent."
                if reply.refused
                else note
            )
        conversation.turns.append(turn)
        return turn

    # S3: identity that is load-bearing for safety is never stripped.
    hold = safety_hold(prompt)
    if hold.held:
        return send_unchanged(hold.reason)

    try:
        rewritten, identity_map, pronoun_style, changes, asker = _rewrite_all(prompts)
    except (InvariantViolation, Exception):  # noqa: BLE001 - fail open to the original
        return send_unchanged(
            "The rewritten prompt could not be proved faithful to what you wrote, so it "
            "was sent unchanged."
        )

    turn.kept = _kept(prompt)

    # Everything in the message was about the person asking - "I spent three weeks on it
    # and I think it's the best thing I've written" - so nothing is left to send. An empty
    # message is refused by providers, and sending the original would put back exactly
    # what was removed. Say so instead, and send nothing.
    if not rewritten[-1].strip():
        turn.sent = ""
        turn.changes = changes
        turn.note = (
            "Everything in this message was about you rather than the work - how you feel "
            "about it, what you put into it, what others thought - so Neutral removed it and "
            "there was nothing left to send. Ask what you want to know about the work and "
            "it will go to the model."
        )
        conversation.turns.append(turn)
        return turn

    # Nothing was found to change, so the rewritten prompt IS the prompt. Asking the
    # model the same question a second time would cost another call and return a
    # different answer - models do not repeat themselves - and the interface would show
    # two answers side by side as though Neutral had done something. It did not.
    if rewritten[-1] == prompt and not changes:
        if turn.kept:
            left = "; ".join(f"\u201c{text}\u201d, because {why}" for text, why in turn.kept)
            return send_unchanged(f"Sent as written. Neutral found and deliberately kept {left}.")
        return send_unchanged(
            "Nothing in this needed changing, so it went to the model exactly as you wrote it."
        )

    # A turn with no reply - one that failed, or one with nothing left to send - is left
    # out: an empty message in the history makes providers refuse every later turn too.
    history = [
        part
        for past, past_rewritten in zip(conversation.turns, rewritten[:-1], strict=False)
        if (past.neutral_answer or past.answer) and past_rewritten.strip()
        for part in (
            ("user", past_rewritten),
            ("assistant", past.neutral_answer or past.answer),
        )
    ]

    processed = adapter.complete(rewritten[-1], history=history)
    if processed.error:
        turn.failed = True
        # To the terminal, never to the page: the interface stays provider-neutral, and
        # the actual reason stops being invisible to whoever has to fix it.
        print(f"[model] {processed.error_kind or 'error'}: {processed.error}")
        turn.note = errors.user_message(processed.error_kind or errors.BAD_REQUEST)
        turn.sent = rewritten[-1]
        turn.changes = changes
        conversation.turns.append(turn)
        return turn

    if processed.refused:
        turn.answer = processed.text
        turn.untouched = True
        turn.note = (
            "The model declined this request. Its refusal is shown exactly as given; "
            "it was not retried or resent."
        )
        conversation.turns.append(turn)
        return turn

    turn.neutral_answer = processed.text
    turn.answer = restore(processed.text, identity_map, pronoun_style, asker)
    turn.sent = rewritten[-1]
    turn.changes = changes
    conversation.turns.append(turn)
    # identity_map is a local. It goes out of scope here, as S5 requires.
    return turn
