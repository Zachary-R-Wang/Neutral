"""The Neutral pipeline: DETECT, DECIDE, TRANSFORM, DISPATCH, RESTORE, RECORD.

Phase 1. Mechanism 1 only - personal names and the gendered pronouns bound to them.

The order of operations here is chosen so that the safety invariants hold by construction
rather than by care:

  * The unmodified response is fetched FIRST, before any rewriting exists to go wrong.
    S2 is then satisfied even if every later stage fails.
  * A refusal short-circuits everything. Nothing is rewritten, retried or resent.
  * The safety hold is consulted before the relevance decision, never after, so no
    ordering change can let a task-relevance judgement overrule a safety one.
  * S1 is verified against the rewritten prompt BEFORE it is sent. If verification fails
    the original goes instead. A prompt that cannot be proved faithful is never
    dispatched.
  * Any exception anywhere falls through to the original prompt with the reason recorded.
    There is no path that sends a half-rewritten prompt.
"""

from __future__ import annotations

from neutral import errors
from neutral.core import NeutralResult, Segment, SegmentKind, Span
from neutral.detect import detect_names, detect_names_offline, find_pronouns
from neutral.invariants import InvariantViolation, verify_no_added_information
from neutral.mechanisms.identity_substitution import MECHANISM as IDENTITY_SUBSTITUTION
from neutral.mechanisms.identity_substitution import apply as substitute
from neutral.policy import decide, safety_hold

DEFAULT_MECHANISMS = (IDENTITY_SUBSTITUTION,)


def _whole(prompt: str) -> tuple[Segment, ...]:
    """The prompt as a single copied segment - what an untouched prompt looks like."""
    return (Segment(SegmentKind.COPY, Span(0, len(prompt)), prompt),)


def _text_of(completion) -> str:
    """Accept either a Completion or a bare string, so test doubles stay simple."""
    return completion if isinstance(completion, str) else completion.text


def _refused(completion) -> bool:
    return not isinstance(completion, str) and bool(getattr(completion, "refused", False))


def _error(completion) -> str | None:
    return None if isinstance(completion, str) else getattr(completion, "error", None)


def _error_kind(completion) -> str:
    return "" if isinstance(completion, str) else getattr(completion, "error_kind", "")


def _passthrough(
    prompt: str, original_response: str, reason: str, *, refused: bool = False, **extra
) -> NeutralResult:
    return NeutralResult(
        original_prompt=prompt,
        processed_prompt=prompt,
        original_response=original_response,
        processed_response=original_response,
        segments=_whole(prompt),
        passthrough=True,
        passthrough_reason=reason,
        refused=refused,
        **extra,
    )


def process(
    prompt: str,
    *,
    adapter,
    mechanisms: tuple[str, ...] = DEFAULT_MECHANISMS,
    comparison_framing: bool = False,
    detector=None,
) -> NeutralResult:
    """Run one prompt through Neutral and return a fully auditable result."""
    detector = detector or adapter

    # --- S2: the unmodified answer, fetched before anything can go wrong -------------
    try:
        original = adapter.complete(prompt)
    except Exception as exc:  # noqa: BLE001 - any failure must fail open, not propagate
        return _passthrough(
            prompt,
            "",
            f"the model could not be reached: {exc}",
            error_kind=errors.UNREACHABLE,
        )

    if _error(original):
        return _passthrough(
            prompt,
            "",
            f"the model returned an error: {_error(original)}",
            error_kind=_error_kind(original) or errors.BAD_REQUEST,
        )

    original_text = _text_of(original)

    # --- S3: a refusal is returned exactly as received, and nothing is retried -------
    if _refused(original):
        return _passthrough(
            prompt,
            original_text,
            "the model declined this request; its refusal is returned unchanged and the "
            "prompt was not rewritten, retried or resent",
            refused=True,
        )

    # --- S3: identity that is load-bearing for safety is never stripped --------------
    hold = safety_hold(prompt)
    if hold.held:
        result = _passthrough(prompt, original_text, hold.reason)
        return NeutralResult(
            original_prompt=result.original_prompt,
            processed_prompt=result.processed_prompt,
            original_response=result.original_response,
            processed_response=result.processed_response,
            segments=result.segments,
            decisions=tuple(decide(prompt, [])),
            passthrough=True,
            passthrough_reason=hold.reason,
            mechanisms_enabled=mechanisms,
        )

    # --- Stage 1, DETECT -------------------------------------------------------------
    try:
        names, detect_error = detect_names(prompt, detector)
    except Exception as exc:  # noqa: BLE001
        names, detect_error = [], f"the name detector failed: {exc}"

    if detect_error:
        return _passthrough(prompt, original_text, detect_error, mechanisms_enabled=mechanisms)

    findings = sorted(names + find_pronouns(prompt, names), key=lambda f: f.span.start)
    if not findings:
        return NeutralResult(
            original_prompt=prompt,
            processed_prompt=prompt,
            original_response=original_text,
            processed_response=original_text,
            segments=_whole(prompt),
            decisions=(),
            mechanisms_enabled=mechanisms,
        )

    # --- Stage 2, DECIDE -------------------------------------------------------------
    decisions = decide(prompt, findings)
    allowed = {i for i, d in enumerate(decisions) if d.transform_allowed}

    # --- Stage 3, TRANSFORM ----------------------------------------------------------
    try:
        substitution = substitute(prompt, findings, allowed)
        processed_prompt = "".join(s.text for s in substitution.segments)
        # S1, checked before dispatch. An unprovable prompt is never sent.
        verify_no_added_information(
            prompt,
            processed_prompt,
            substitution.segments,
            comparison_framing_enabled=comparison_framing,
        )
    except (InvariantViolation, Exception) as exc:  # noqa: BLE001
        return _passthrough(
            prompt,
            original_text,
            f"the rewritten prompt could not be proved faithful to the original, so the "
            f"original was sent instead: {exc}",
            decisions=tuple(decisions),
            mechanisms_enabled=mechanisms,
        )

    # --- Stage 4, DISPATCH -----------------------------------------------------------
    try:
        processed = adapter.complete(processed_prompt)
    except Exception as exc:  # noqa: BLE001
        return _passthrough(
            prompt,
            original_text,
            f"the model could not be reached: {exc}",
            decisions=tuple(decisions),
            mechanisms_enabled=mechanisms,
        )

    if _error(processed):
        return _passthrough(
            prompt,
            original_text,
            f"the model returned an error: {_error(processed)}",
            decisions=tuple(decisions),
            mechanisms_enabled=mechanisms,
        )

    processed_text = _text_of(processed)
    if _refused(processed):
        return _passthrough(
            prompt,
            original_text,
            "the model declined the rewritten request; its refusal is returned unchanged",
            refused=True,
            decisions=tuple(decisions),
            mechanisms_enabled=mechanisms,
        )

    # --- Stage 5, RESTORE ------------------------------------------------------------
    from neutral.restore import restore

    restored = restore(processed_text, substitution.identity_map, substitution.pronoun_style)

    # --- Stage 6, RECORD -------------------------------------------------------------
    # S5: identity_map is a local. It goes out of scope when this function returns, and
    # is deliberately not placed on the result or in metadata.
    return NeutralResult(
        original_prompt=prompt,
        processed_prompt=processed_prompt,
        original_response=original_text,
        processed_response=restored,
        segments=substitution.segments,
        transforms=substitution.transforms,
        decisions=tuple(decisions),
        mechanisms_enabled=mechanisms,
        comparison_framing_enabled=comparison_framing,
        metadata={
            "people_substituted": str(len(substitution.identity_map)),
            "spans_changed": str(len(substitution.transforms)),
        },
    )


def preview(prompt: str, *, comparison_framing: bool = False) -> NeutralResult:
    """Show what Neutral would send, without calling a model at all.

    No network, no cost. Detection falls back to rules, which are worse than the real
    detector and are labelled as such wherever this is displayed - capitalisation is a
    poor signal for names in English.

    The transform, the policy layer and the S1 check are the real ones. Only the detector
    differs, so what this shows is genuinely what Neutral would send, given the names the
    rules happened to find.
    """
    hold = safety_hold(prompt)
    if hold.held:
        return NeutralResult(
            original_prompt=prompt,
            processed_prompt=prompt,
            original_response="",
            processed_response="",
            segments=_whole(prompt),
            decisions=tuple(decide(prompt, [])),
            passthrough=True,
            passthrough_reason=hold.reason,
        )

    names = detect_names_offline(prompt)
    findings = sorted(names + find_pronouns(prompt, names), key=lambda f: f.span.start)
    if not findings:
        return NeutralResult(
            original_prompt=prompt,
            processed_prompt=prompt,
            original_response="",
            processed_response="",
            segments=_whole(prompt),
        )

    decisions = decide(prompt, findings)
    allowed = {i for i, d in enumerate(decisions) if d.transform_allowed}
    substitution = substitute(prompt, findings, allowed)
    processed_prompt = "".join(s.text for s in substitution.segments)

    # The same S1 check the real path runs. A preview that could not be proved faithful
    # would be showing something Neutral would never actually send.
    verify_no_added_information(
        prompt,
        processed_prompt,
        substitution.segments,
        comparison_framing_enabled=comparison_framing,
    )

    return NeutralResult(
        original_prompt=prompt,
        processed_prompt=processed_prompt,
        original_response="",
        processed_response="",
        segments=substitution.segments,
        transforms=substitution.transforms,
        decisions=tuple(decisions),
        mechanisms_enabled=DEFAULT_MECHANISMS,
        metadata={"preview": "true"},
    )
