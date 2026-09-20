"""Executable form of the safety invariants in CLAUDE.md section 3.

Each function here answers one question: does this result satisfy the invariant? They are
pure functions over data, with no model calls and no I/O, so they are cheap enough to run
as assertions inside the pipeline as well as in the test suite.

A violation raises InvariantViolation. That is deliberate: these are build failures, not
warnings. Nothing in this module downgrades a violation to a log line.
"""

from __future__ import annotations

from neutral.core import COMPARISON_FRAMING, NeutralResult, Segment, SegmentKind, render


class InvariantViolation(AssertionError):
    """A safety invariant from CLAUDE.md section 3 was broken.

    The message names the invariant and says what was expected, so that a failure is
    readable without opening the source.
    """

    def __init__(self, invariant: str, problem: str, detail: str = "") -> None:
        message = f"{invariant} violated: {problem}"
        if detail:
            message += f"\n  {detail}"
        super().__init__(message)
        self.invariant = invariant
        self.problem = problem


# --------------------------------------------------------------------------------------
# S1 - Neutral never adds information about a real person
# --------------------------------------------------------------------------------------


def verify_no_added_information(
    original_prompt: str,
    processed_prompt: str,
    segments: tuple[Segment, ...] | list[Segment],
    *,
    comparison_framing_enabled: bool = False,
) -> None:
    """S1. Prove the rewritten prompt adds nothing, by reconstructing it.

    Every character of the rewritten prompt must be traceable to a segment, and every
    segment must either copy from the original, replace a span of the original, or be an
    explicitly flagged injection from Mechanism 4 (the one documented exception).

    This is stronger than inspecting the output for invented details: content that was
    never in the original simply has nowhere to come from.
    """
    segments = tuple(segments)

    for index, segment in enumerate(segments):
        where = f"segment {index} ({segment.kind.value})"

        if segment.kind is SegmentKind.INJECT:
            if not comparison_framing_enabled:
                raise InvariantViolation(
                    "S1",
                    "content was added to the prompt that was not in the original",
                    f"{where} injects text while comparison framing is off. Injection is "
                    f"only ever permitted for Mechanism 4, and only when the user has "
                    f"opted in. Added text: {segment.text!r}",
                )
            if segment.mechanism != COMPARISON_FRAMING:
                raise InvariantViolation(
                    "S1",
                    "a mechanism other than comparison framing added content",
                    f"{where} was produced by {segment.mechanism!r}. Only "
                    f"{COMPARISON_FRAMING!r} may add content, per CLAUDE.md section 3.",
                )
            if segment.source is not None:
                raise InvariantViolation(
                    "S1",
                    "an injected segment claims a source span in the original",
                    f"{where} is an injection, so it cannot have come from the original "
                    f"prompt. Injected segments must have source=None.",
                )
            continue

        if segment.source is None:
            raise InvariantViolation(
                "S1",
                "a segment does not say where its content came from",
                f"{where} has no source span. Every copied or replaced segment must "
                f"point at the span of the original prompt it came from.",
            )

        if segment.source.end > len(original_prompt):
            raise InvariantViolation(
                "S1",
                "a segment points outside the original prompt",
                f"{where} claims characters [{segment.source.start}, "
                f"{segment.source.end}) but the original prompt is only "
                f"{len(original_prompt)} characters long.",
            )

        source_text = segment.source.text_in(original_prompt)

        if segment.kind is SegmentKind.COPY and segment.text != source_text:
            raise InvariantViolation(
                "S1",
                "a segment marked as copied does not match the original",
                f"{where} claims to copy {source_text!r} but contributes "
                f"{segment.text!r}. A copy must be verbatim; use REPLACE instead.",
            )

    rebuilt = render(segments)
    if rebuilt != processed_prompt:
        raise InvariantViolation(
            "S1",
            "the rewritten prompt does not match its own audit trail",
            f"Rebuilding the prompt from its {len(segments)} recorded segments produced "
            f"different text than the prompt that would be sent. Something changed the "
            f"prompt without recording it.\n"
            f"  rebuilt from segments: {rebuilt!r}\n"
            f"  prompt to be sent:     {processed_prompt!r}",
        )


def verify_result_adds_nothing(result: NeutralResult) -> None:
    """S1, applied to a complete result."""
    verify_no_added_information(
        result.original_prompt,
        result.processed_prompt,
        result.segments,
        comparison_framing_enabled=result.comparison_framing_enabled,
    )


# --------------------------------------------------------------------------------------
# S2 - The original response is always retrievable
# --------------------------------------------------------------------------------------


def verify_both_responses_present(result: NeutralResult) -> None:
    """S2. Both the unmodified and the processed response must exist on every result."""
    if result.original_response is None:
        raise InvariantViolation(
            "S2",
            "the unmodified model response was not stored",
            "Every request must keep what the model would have said to the raw prompt, "
            "so the interface can always show it. Nothing is hidden from the user.",
        )
    if result.processed_response is None:
        raise InvariantViolation(
            "S2",
            "the Neutral-processed response was not stored",
            "Both responses are required on every result.",
        )


# --------------------------------------------------------------------------------------
# S3 - Neutral is never a route around a model's safety systems
# --------------------------------------------------------------------------------------


def verify_refusal_returned_verbatim(
    upstream_response: str,
    returned_response: str,
) -> None:
    """S3. A refusal from the upstream model passes through byte-identical."""
    if upstream_response != returned_response:
        raise InvariantViolation(
            "S3",
            "a model refusal was altered before being returned",
            "When the upstream model refuses, that refusal is returned exactly as it was "
            "received. Neutral never retries, rephrases, or splits a refused prompt.\n"
            f"  model said: {upstream_response!r}\n"
            f"  returned:   {returned_response!r}",
        )


def verify_safety_relevant_prompt_untouched(result: NeutralResult) -> None:
    """S3. If identity is safety-relevant, the prompt goes through unmodified.

    The relevance gate decides whether an attribute is load-bearing for the *task*. It is
    never given the job of deciding whether an attribute is load-bearing for *safety* -
    for that question the answer is always "yes, keep it".
    """
    held = [d for d in result.decisions if d.safety_hold]
    if not held:
        return

    if result.processed_prompt != result.original_prompt:
        changed = ", ".join(repr(d.detected) for d in held)
        raise InvariantViolation(
            "S3",
            "a prompt was rewritten even though stripping identity could change whether "
            "the request is harmful",
            f"The policy engine placed a safety hold on: {changed}. A safety hold means "
            f"the prompt must be passed through unmodified and the decision logged.",
        )

    for decision in held:
        if decision.transform_allowed:
            raise InvariantViolation(
                "S3",
                "the policy engine allowed a transform on a span it had flagged for safety",
                f"{decision.detected!r} was marked safety_hold but also "
                f"transform_allowed. A safety hold is absolute.",
            )


# --------------------------------------------------------------------------------------
# S4 - Fail open to the original, never to a mangled prompt
# --------------------------------------------------------------------------------------


def verify_failed_open_cleanly(result: NeutralResult) -> None:
    """S4. A passthrough sends the original prompt, unmodified, and says why."""
    if not result.passthrough:
        return

    if result.processed_prompt != result.original_prompt:
        raise InvariantViolation(
            "S4",
            "a failed request sent a partly-rewritten prompt to the model",
            "When any stage errors, times out, or produces low-confidence output, the "
            "ORIGINAL prompt is sent unmodified. A half-rewritten prompt is worse than "
            "no rewriting.",
        )

    if not result.passthrough_reason:
        raise InvariantViolation(
            "S4",
            "a request failed open without recording why",
            "The response is flagged as unprocessed, so the reason must be recorded.",
        )


# --------------------------------------------------------------------------------------
# S5 - No persistence of personal data by default
# --------------------------------------------------------------------------------------


def verify_identity_map_discarded(identity_map: dict[str, str] | None) -> None:
    """S5. Identity mappings live for one request and are then discarded."""
    if identity_map:
        leaked = ", ".join(sorted(identity_map)[:3])
        raise InvariantViolation(
            "S5",
            "the real-name to placeholder mapping outlived the request",
            f"Identity mappings are held in memory for the duration of a single request "
            f"and discarded. Still present after the request: {leaked}",
        )


def verify_no_identifying_data_persisted(
    persisted: object,
    identifiers: list[str],
    *,
    audit_retain: bool = False,
) -> None:
    """S5. Nothing identifying is written to disk unless AUDIT_RETAIN=true."""
    if audit_retain:
        return

    blob = repr(persisted)
    for identifier in identifiers:
        if identifier and identifier in blob:
            raise InvariantViolation(
                "S5",
                "identifying data was written to storage with AUDIT_RETAIN unset",
                f"Found {identifier!r} in the record that was about to be persisted. "
                f"With AUDIT_RETAIN unset, nothing identifying is written to disk.",
            )


# --------------------------------------------------------------------------------------
# S6 - Not for live decisions
# --------------------------------------------------------------------------------------

BANNER = "evaluation use only - do not use this output as the basis of an employment decision"


def verify_banner_present(rendered_page: str) -> None:
    """S6. The MVP displays a persistent banner."""
    if BANNER.lower() not in rendered_page.lower():
        raise InvariantViolation(
            "S6",
            "the evaluation-use-only banner is missing",
            f"Every page must display: {BANNER!r}. It is removed only when instructed in writing.",
        )


# --------------------------------------------------------------------------------------
# S7 - Every transformation is logged with its reason
# --------------------------------------------------------------------------------------


def verify_every_transformation_logged(result: NeutralResult) -> None:
    """S7. Each change carries what fired, what it produced, and why it was allowed."""
    changed = [s for s in result.segments if s.kind is not SegmentKind.COPY]

    if changed and not result.transforms:
        raise InvariantViolation(
            "S7",
            "the prompt was changed but nothing was written to the audit log",
            f"{len(changed)} segment(s) were altered. Every change must record what was "
            f"detected, what replaced it, which mechanism fired, and why the relevance "
            f"gate allowed it.",
        )

    for record in result.transforms:
        missing = [
            name
            for name in ("mechanism", "detected", "replacement", "policy", "reason")
            if not getattr(record, name)
        ]
        if missing:
            raise InvariantViolation(
                "S7",
                "an audit log entry is incomplete",
                f"Entry for {record.detected!r} is missing: {', '.join(missing)}. The "
                f"audit log is a first-class output, not debug noise.",
            )


# --------------------------------------------------------------------------------------
# All of them at once
# --------------------------------------------------------------------------------------


def verify_all(result: NeutralResult) -> None:
    """Run every invariant that can be checked from a result alone.

    The pipeline calls this before returning. If it raises, the caller fails open to the
    original prompt (S4) rather than returning a result that broke an invariant.
    """
    verify_result_adds_nothing(result)
    verify_both_responses_present(result)
    verify_safety_relevant_prompt_untouched(result)
    verify_failed_open_cleanly(result)
    verify_every_transformation_logged(result)
