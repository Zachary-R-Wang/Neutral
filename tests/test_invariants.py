"""The safety invariants of CLAUDE.md section 3, in executable form.

These tests are never skipped, never marked xfail, and never mocked around.

The file has two halves, and the difference matters when you read the output:

  PART 1 - the enforcement machinery.
      Does the verifier actually catch a violation? These test real, finished code in
      neutral/invariants.py. They pass today. If one of them fails, the safety net
      itself is broken and nothing else in the project can be trusted.

  PART 2 - the pipeline.
      Does the rewriting pipeline obey the invariants? The pipeline does not exist yet
      (Phase 0 builds the measurement first), so every test in this half FAILS today,
      deliberately. They are the constraints Phase 1 has to satisfy, written down first
      so they cannot be quietly relaxed later to make a feature fit.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from neutral import accounts
from neutral.adapters.base import Completion
from neutral.core import (
    COMPARISON_FRAMING,
    NeutralResult,
    PolicyDecision,
    Segment,
    SegmentKind,
    Span,
    TransformRecord,
)
from neutral.detect import DetectedSpan, Detection
from neutral.invariants import (
    BANNER,
    InvariantViolation,
    verify_account_store_columns,
    verify_banner_present,
    verify_both_responses_present,
    verify_every_transformation_logged,
    verify_failed_open_cleanly,
    verify_identity_map_discarded,
    verify_no_added_information,
    verify_no_identifying_data_persisted,
    verify_nothing_identifying_on_disk,
    verify_refusal_returned_verbatim,
    verify_result_adds_nothing,
    verify_safety_relevant_prompt_untouched,
)
from neutral.pipeline import process
from neutral.web import app as web_app
from neutral.web.sessions import Sessions

pytestmark = pytest.mark.invariant


ORIGINAL = "Priya Raman missed two deadlines this quarter. Write her review."


# ======================================================================================
# PART 1 - the enforcement machinery works
# ======================================================================================


class TestS1EnforcementWorks:
    """S1 - Neutral never adds information about a real person."""

    def test_accepts_a_faithful_substitution(self):
        # "Priya Raman" -> "Person A", everything else copied verbatim.
        segments = (
            Segment(SegmentKind.REPLACE, Span(0, 11), "Person A", "identity_substitution"),
            Segment(SegmentKind.COPY, Span(11, len(ORIGINAL)), ORIGINAL[11:]),
        )
        processed = "Person A" + ORIGINAL[11:]
        verify_no_added_information(ORIGINAL, processed, segments)

    def test_accepts_a_deletion(self):
        # Dropping a span is just declining to emit a segment for it.
        segments = (Segment(SegmentKind.COPY, Span(12, len(ORIGINAL)), ORIGINAL[12:]),)
        verify_no_added_information(ORIGINAL, ORIGINAL[12:], segments)

    def test_rejects_an_invented_credential(self):
        """The failure this invariant exists to prevent."""
        segments = (
            Segment(SegmentKind.COPY, Span(0, len(ORIGINAL)), ORIGINAL),
            Segment(SegmentKind.INJECT, None, " She has a PhD in statistics.", "helpful"),
        )
        processed = ORIGINAL + " She has a PhD in statistics."
        with pytest.raises(InvariantViolation) as caught:
            verify_no_added_information(ORIGINAL, processed, segments)
        assert caught.value.invariant == "S1"

    def test_rejects_silent_edits_that_bypass_the_audit_trail(self):
        """Text changed without a segment recording it is the subtle failure mode."""
        segments = (Segment(SegmentKind.COPY, Span(0, len(ORIGINAL)), ORIGINAL),)
        with pytest.raises(InvariantViolation) as caught:
            verify_no_added_information(ORIGINAL, ORIGINAL + " Also, she is 52.", segments)
        assert caught.value.invariant == "S1"

    def test_rejects_a_copy_that_does_not_match_the_original(self):
        segments = (Segment(SegmentKind.COPY, Span(0, 11), "Paul Raman"),)
        with pytest.raises(InvariantViolation):
            verify_no_added_information(ORIGINAL, "Paul Raman", segments)

    def test_rejects_a_span_pointing_outside_the_original(self):
        segments = (Segment(SegmentKind.COPY, Span(0, len(ORIGINAL) + 40), ORIGINAL),)
        with pytest.raises(InvariantViolation):
            verify_no_added_information(ORIGINAL, ORIGINAL, segments)


class TestS1ComparisonFramingException:
    """The single documented exception in CLAUDE.md section 3, and its limits."""

    def test_comparison_framing_may_add_material_when_opted_in(self):
        segments = (
            Segment(SegmentKind.COPY, Span(0, len(ORIGINAL)), ORIGINAL),
            Segment(
                SegmentKind.INJECT,
                None,
                "\n\nAlso assess this second, unrelated draft review: [...]",
                COMPARISON_FRAMING,
            ),
        )
        processed = ORIGINAL + "\n\nAlso assess this second, unrelated draft review: [...]"
        verify_no_added_information(ORIGINAL, processed, segments, comparison_framing_enabled=True)

    def test_comparison_framing_is_off_by_default(self):
        """Opt-in per request. Off by default means the same segments are refused."""
        segments = (
            Segment(SegmentKind.COPY, Span(0, len(ORIGINAL)), ORIGINAL),
            Segment(SegmentKind.INJECT, None, "\n\nSecond draft: [...]", COMPARISON_FRAMING),
        )
        with pytest.raises(InvariantViolation):
            verify_no_added_information(ORIGINAL, ORIGINAL + "\n\nSecond draft: [...]", segments)

    def test_no_other_mechanism_may_borrow_the_exception(self):
        """S1 still holds absolutely for the user's own content."""
        segments = (
            Segment(SegmentKind.COPY, Span(0, len(ORIGINAL)), ORIGINAL),
            Segment(SegmentKind.INJECT, None, " She is well regarded.", "person_neutralisation"),
        )
        with pytest.raises(InvariantViolation) as caught:
            verify_no_added_information(
                ORIGINAL,
                ORIGINAL + " She is well regarded.",
                segments,
                comparison_framing_enabled=True,
            )
        assert "comparison framing" in str(caught.value)


class TestS2EnforcementWorks:
    """S2 - the original response is always retrievable."""

    def test_rejects_a_result_missing_the_unmodified_response(self):
        result = NeutralResult(ORIGINAL, ORIGINAL, None, "processed answer")
        with pytest.raises(InvariantViolation) as caught:
            verify_both_responses_present(result)
        assert caught.value.invariant == "S2"


class TestS3EnforcementWorks:
    """S3 - Neutral is never a route around a model's safety system."""

    def test_refusal_must_pass_through_byte_identical(self):
        refusal = "I can't help with that request."
        verify_refusal_returned_verbatim(refusal, refusal)

    def test_rejects_a_softened_refusal(self):
        with pytest.raises(InvariantViolation) as caught:
            verify_refusal_returned_verbatim(
                "I can't help with that request.",
                "I can't help with that request, but here is a partial answer.",
            )
        assert caught.value.invariant == "S3"

    def test_rejects_rewriting_a_prompt_under_a_safety_hold(self):
        decision = PolicyDecision(
            detected="15-year-old",
            detected_kind="age",
            source=Span(0, 11),
            transform_allowed=False,
            reason="age changes whether this request is harmful",
            safety_hold=True,
        )
        result = NeutralResult(
            original_prompt="15-year-old asking about X",
            processed_prompt="Person A asking about X",
            original_response="",
            processed_response="",
            decisions=(decision,),
        )
        with pytest.raises(InvariantViolation) as caught:
            verify_safety_relevant_prompt_untouched(result)
        assert caught.value.invariant == "S3"

    def test_a_safety_hold_can_never_also_allow_a_transform(self):
        decision = PolicyDecision(
            detected="15-year-old",
            detected_kind="age",
            source=Span(0, 11),
            transform_allowed=True,
            reason="not load-bearing for the task",
            safety_hold=True,
        )
        result = NeutralResult("same", "same", "", "", decisions=(decision,))
        with pytest.raises(InvariantViolation):
            verify_safety_relevant_prompt_untouched(result)


class TestS4EnforcementWorks:
    """S4 - fail open to the original, never to a mangled prompt."""

    def test_rejects_a_half_rewritten_prompt_on_failure(self):
        result = NeutralResult(
            original_prompt=ORIGINAL,
            processed_prompt="Person A missed two deadlines this quarter. Write her rev",
            original_response="",
            processed_response="",
            passthrough=True,
            passthrough_reason="detector timed out",
        )
        with pytest.raises(InvariantViolation) as caught:
            verify_failed_open_cleanly(result)
        assert caught.value.invariant == "S4"

    def test_rejects_a_passthrough_with_no_recorded_reason(self):
        result = NeutralResult(ORIGINAL, ORIGINAL, "", "", passthrough=True)
        with pytest.raises(InvariantViolation):
            verify_failed_open_cleanly(result)

    def test_accepts_a_clean_passthrough(self):
        result = NeutralResult(
            ORIGINAL, ORIGINAL, "", "", passthrough=True, passthrough_reason="low confidence"
        )
        verify_failed_open_cleanly(result)


class TestS5EnforcementWorks:
    """S5 - no persistence of personal data by default."""

    def test_rejects_an_identity_map_that_outlived_the_request(self):
        with pytest.raises(InvariantViolation) as caught:
            verify_identity_map_discarded({"Priya Raman": "Person A"})
        assert caught.value.invariant == "S5"

    def test_accepts_a_discarded_identity_map(self):
        verify_identity_map_discarded({})

    def test_rejects_writing_a_real_name_to_storage(self):
        record = {"prompt": ORIGINAL, "verdict": "ok"}
        with pytest.raises(InvariantViolation):
            verify_no_identifying_data_persisted(record, ["Priya Raman"])

    def test_allows_retention_only_behind_the_explicit_flag(self):
        record = {"prompt": ORIGINAL}
        verify_no_identifying_data_persisted(record, ["Priya Raman"], audit_retain=True)


class _SilentAdapter:
    """Answers without a network, so the S5 disk check needs no key and no credit."""

    def complete(self, prompt, *, system="", history=()):
        return Completion(text="Person A is ready for promotion.", model="stand-in")


class TestS5HoldsNowThatAccountsExist:
    """S5 - the storage boundary that arrived with accounts on 2026-09-24.

    Accounts mean Neutral writes to disk for the first time. S5 was clarified rather than
    weakened: the account holder's own login may be stored, nothing about the people
    inside a prompt may be, and the API key is not stored at all.

    The last test here is the one that matters. It runs a real conversation through the
    real app and then reads the bytes of the database file, because a rule that is only
    checked on the way in would not notice a write-ahead log or a leftover free page.
    """

    def test_the_real_account_table_has_no_column_it_should_not(self):
        verify_account_store_columns(accounts.COLUMNS)

    @pytest.mark.parametrize(
        "added", ["api_key", "apikey", "token", "secret", "prompt", "conversation", "name"]
    )
    def test_a_column_for_a_credential_or_a_prompt_is_a_violation(self, added):
        with pytest.raises(InvariantViolation) as caught:
            verify_account_store_columns([*accounts.COLUMNS, added])
        assert caught.value.invariant == "S5"

    def test_the_declared_columns_are_the_ones_the_database_actually_makes(self, tmp_path):
        """The declaration is only worth testing if it matches what gets created."""
        db = accounts.connect(tmp_path / "accounts.db")
        made = tuple(r["name"] for r in db.execute("PRAGMA table_info(accounts)"))
        assert made == accounts.COLUMNS

    def test_bytes_on_disk_are_checked_not_just_the_object(self):
        verify_nothing_identifying_on_disk(b"provider=openai", ["Priya Raman"])
        with pytest.raises(InvariantViolation) as caught:
            verify_nothing_identifying_on_disk(b"...Priya Raman...", ["Priya Raman"])
        assert caught.value.invariant == "S5"

    def test_a_real_conversation_leaves_nothing_identifying_in_the_file(self, tmp_path):
        """End to end, through the actual app: sign up, connect, ask, then read the file.

        If somebody later adds a column that remembers a key, or starts logging prompts
        to the account database, this is the test that fails.
        """
        key = "sk-ant-thiskeymustnevertouchthedisk"
        prompt = "Assess whether Priya Raman is ready for promotion. I wrote her review."

        monkey = pytest.MonkeyPatch()
        try:
            path = tmp_path / "accounts.db"
            monkey.setenv("NEUTRAL_ACCOUNTS_DB", str(path))
            monkey.setattr(web_app, "_db", None)
            monkey.setattr(web_app, "sessions", Sessions())
            monkey.setattr(
                web_app,
                "build",
                lambda provider, api_key, model="", **kw: _SilentAdapter(),
            )

            client = TestClient(web_app.app)
            client.post("/signup", data={"email": "hr@example.com", "password": "long-enough-pw"})
            client.post(
                "/connect",
                data={
                    "provider": "anthropic",
                    "model_anthropic": "claude-sonnet-5",
                    "api_key": key,
                },
            )
            client.post("/", data={"prompt": prompt})
        finally:
            monkey.undo()

        written = b"".join(
            found.read_bytes() for found in tmp_path.glob("accounts.db*") if found.is_file()
        )
        verify_nothing_identifying_on_disk(
            written,
            [key, prompt, "Priya", "Raman", "Person A", "promotion"],
        )
        # Not vacuous: the account itself did get written.
        assert b"hr@example.com" in written


class TestS6EnforcementWorks:
    """S6 - not for live decisions."""

    def test_rejects_a_page_without_the_banner(self):
        with pytest.raises(InvariantViolation) as caught:
            verify_banner_present("<html><body>Neutral</body></html>")
        assert caught.value.invariant == "S6"

    def test_accepts_a_page_with_the_banner(self):
        verify_banner_present(f"<html><body><div>{BANNER}</div></body></html>")


class TestS7EnforcementWorks:
    """S7 - every transformation is logged with its reason."""

    def test_rejects_a_change_with_an_empty_audit_log(self):
        result = NeutralResult(
            ORIGINAL,
            "Person A" + ORIGINAL[11:],
            "",
            "",
            segments=(Segment(SegmentKind.REPLACE, Span(0, 11), "Person A", "identity"),),
            transforms=(),
        )
        with pytest.raises(InvariantViolation) as caught:
            verify_every_transformation_logged(result)
        assert caught.value.invariant == "S7"

    def test_rejects_an_audit_entry_missing_its_reason(self):
        record = TransformRecord(
            mechanism="identity_substitution",
            detected="Priya Raman",
            detected_kind="person_name",
            replacement="Person A",
            source=Span(0, 11),
            policy="hr-default",
            policy_version="v1",
            reason="",
        )
        result = NeutralResult(
            ORIGINAL,
            "Person A" + ORIGINAL[11:],
            "",
            "",
            segments=(Segment(SegmentKind.REPLACE, Span(0, 11), "Person A", "identity"),),
            transforms=(record,),
        )
        with pytest.raises(InvariantViolation):
            verify_every_transformation_logged(result)


# ======================================================================================
# PART 2 - the pipeline obeys the invariants
#
# Every test below fails today. The pipeline does not exist yet; Phase 0 builds the
# measurement first. These are the constraints Phase 1 must satisfy.
# ======================================================================================


class _RecordingAdapter:
    """A stand-in model.

    This was a bare stub when these tests were written, before the adapter interface
    existed - it returned a plain string and had no way to signal a refusal or to run
    detection. It now matches the real interface. None of the assertions below changed.
    """

    name = "recording"
    model = "recording-1"

    def __init__(self, reply: str = "Here is the review.", *, refuse: bool = False) -> None:
        self.reply = reply
        self.refuse = refuse
        self.prompts_seen: list[str] = []

    def complete(self, prompt: str, *, system: str | None = None) -> Completion:
        self.prompts_seen.append(prompt)
        return Completion(
            text=self.reply,
            model=self.model,
            refused=self.refuse,
            stop_reason="refusal" if self.refuse else "end_turn",
        )

    def parse(self, prompt: str, output_format, *, system: str | None = None):
        """Stand in for the name detector. Finds the names this dataset actually uses."""
        found = [
            DetectedSpan(text=name, kind="person_name")
            for name in ("Priya Raman", "Emily Carter", "Ethan Carter")
            if name in prompt
        ]
        return Detection(spans=found), Completion(text="", model=self.model)


def _run(prompt: str = ORIGINAL, **kwargs) -> NeutralResult:
    return process(prompt, adapter=_RecordingAdapter(), **kwargs)


class TestPipelineSatisfiesInvariants:
    def test_s1_pipeline_output_adds_nothing(self):
        verify_result_adds_nothing(_run())

    def test_s2_pipeline_keeps_both_responses(self):
        verify_both_responses_present(_run())

    def test_s3_pipeline_leaves_safety_relevant_prompts_untouched(self):
        prompt = "My 15-year-old daughter asked me how to buy alcohol. What do I say?"
        result = _run(prompt)
        assert result.processed_prompt == prompt, (
            "S3: identity is load-bearing for safety here, so the prompt must reach the "
            "model unmodified."
        )
        verify_safety_relevant_prompt_untouched(result)

    def test_s3_pipeline_returns_refusals_verbatim(self):
        refusal = "I can't help with that."
        adapter = _RecordingAdapter(reply=refusal, refuse=True)
        result = process(ORIGINAL, adapter=adapter)
        verify_refusal_returned_verbatim(refusal, result.processed_response)
        assert result.refused is True

    def test_s4_pipeline_fails_open_to_the_original(self):
        class BrokenAdapter:
            model = "broken"

            def complete(self, prompt: str, *, system: str | None = None):
                raise TimeoutError("upstream timed out")

        result = process(ORIGINAL, adapter=BrokenAdapter())
        verify_failed_open_cleanly(result)
        assert result.passthrough is True

    def test_s5_pipeline_discards_the_identity_map(self):
        result = _run()
        seen = repr(result.metadata)
        leftovers = {r.detected: r.replacement for r in result.transforms if r.detected in seen}
        verify_identity_map_discarded(leftovers)

    def test_s7_pipeline_logs_every_transformation(self):
        verify_every_transformation_logged(_run())
