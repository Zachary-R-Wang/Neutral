"""Mechanisms 2 and 3.

The test that matters most in this file is the one asserting the quoted artifact comes
back untouched. A prompt asking for a cover letter to be judged contains that cover
letter, and it is full of "I am writing to express my strong interest". Rewriting that
would hand the model a document nobody wrote and judge the user on it.
"""

from __future__ import annotations

from neutral.core import SegmentKind
from neutral.detect import detect_names_local, find_pronouns
from neutral.mechanisms import order_neutralisation as order
from neutral.mechanisms.identity_substitution import apply as substitute
from neutral.policy import decide
from neutral.rewrite import IDENTITY, PERSON, rewrite

COVER_LETTER = """This is my cover letter.

"Dear Hiring Manager, I am writing to express my strong interest in the role.
I believe my background makes me an excellent fit and I am confident I would
bring the same energy to your team."

Give an honest critique."""

CODE = """Here is a function I wrote.

    def add_tag(item, tags=[]):
        tags.append(item)
        return tags

Is there anything wrong with it?"""


def _text(prompt: str, **kw) -> str:
    return rewrite(prompt, **kw).processed


# ---------------------------------------------------------------------------
# Mechanism 3
# ---------------------------------------------------------------------------


class TestTheWorkBeingAssessedIsNeverEdited:
    def test_a_quoted_artifact_survives_word_for_word(self):
        out = _text(COVER_LETTER)
        quoted = COVER_LETTER[COVER_LETTER.index('"') : COVER_LETTER.rindex('"') + 1]
        assert quoted in out, "the cover letter itself was rewritten"

    def test_the_framing_around_it_is_still_neutralised(self):
        out = _text(COVER_LETTER)
        assert out.startswith("This is the author's cover letter.")

    def test_an_indented_code_block_survives(self):
        out = _text(CODE)
        assert "def add_tag(item, tags=[]):" in out
        assert "tags.append(item)" in out
        assert out.startswith("Here is a function the author wrote.")

    def test_first_person_inside_the_artifact_is_left_alone(self):
        out = _text(COVER_LETTER)
        assert "I am writing to express my strong interest" in out
        assert "the author is writing to express" not in out


class TestItOnlyFiresOnAnActualAuthorshipClaim:
    def test_an_ordinary_question_with_i_in_it_is_untouched(self):
        assert not rewrite("How should I structure a performance review?").changed

    def test_my_report_means_a_person_not_a_document(self):
        """In HR "my report" is nearly always somebody, and mangling that is worse."""
        for prompt in (
            "What should I say to my report about their promotion?",
            "My report thinks they are ready for a step up.",
        ):
            assert not rewrite(prompt).changed, prompt

    def test_a_claim_to_have_written_something_does_fire(self):
        for prompt in (
            "I wrote this memo. Is it any good?",
            "Here is my draft. Be honest.",
            "A colleague drafted this email. Rate it.",
            "This passage was written by me. Critique it.",
        ):
            assert rewrite(prompt).changed, prompt

    def test_it_can_be_turned_off(self):
        assert not rewrite("I wrote this memo.", mechanisms=(IDENTITY,)).changed


class TestBothFramingsEndUpIdentical:
    def test_i_wrote_and_a_colleague_wrote_converge(self):
        mine = _text("I wrote the passage below and I am thinking of publishing it.")
        theirs = _text(
            "A colleague wrote the passage below and they are thinking of publishing it."
        )
        assert mine == theirs
        assert mine == (
            "The author wrote the passage below and the author is thinking of publishing it."
        )

    def test_the_verb_agrees_after_the_swap(self):
        assert "the author is" in _text("I drafted it. I am unsure about the tone.").lower()
        assert "the author has" in _text("I drafted it. I have doubts about it.").lower()

    def test_a_contraction_is_handled(self):
        assert "The author is" in _text("I wrote this. I'm unsure about paragraph two.")

    def test_a_sentence_start_is_capitalised_and_mid_sentence_is_not(self):
        out = _text("I wrote this. Tell me what I should change.")
        assert out.startswith("The author wrote")
        assert "what the author should change" in out


class TestPuttingTheAnswerBack:
    def test_first_person_framing_restores_to_you(self):
        done = rewrite("I wrote this memo. Is it any good?")
        assert done.restore_map["the author"] == "you"
        assert done.restore_map["the author's"] == "your"

    def test_a_stand_in_author_restores_to_your_colleague(self):
        done = rewrite("A colleague wrote this memo. Is it any good?")
        assert done.restore_map["the author"] == "your colleague"

    def test_both_cases_are_registered_so_a_sentence_start_maps_back(self):
        done = rewrite("I wrote this memo.")
        assert done.restore_map["The author"] == "You"


# ---------------------------------------------------------------------------
# Mechanism 2
# ---------------------------------------------------------------------------


def _substituted(prompt: str):
    names = detect_names_local(prompt)
    findings = sorted(names + find_pronouns(prompt, names), key=lambda f: f.span.start)
    decisions = decide(prompt, findings)
    allowed = {i for i, d in enumerate(decisions) if d.transform_allowed}
    return substitute(prompt, findings, allowed).segments


class TestOrderNeutralisation:
    def test_a_coordinated_pair_can_be_swapped(self):
        swapped = [
            _text(f"Compare {a} and {b} for the opening number {i}.")
            for i, (a, b) in enumerate(
                [("Anna Schmidt", "Ben Clark"), ("Yusuf Demir", "Kate Wood")] * 6
            )
        ]
        assert any("Person B and Person A" in s for s in swapped), "it never swaps"
        assert any("Person A and Person B" in s for s in swapped), "it always swaps"

    def test_the_same_prompt_always_decides_the_same_way(self):
        prompt = "Should we promote Priya Raman or Greg Miller this cycle?"
        assert len({_text(prompt) for _ in range(6)}) == 1

    def test_the_coin_is_fair(self):
        heads = sum(
            order._coin(f"Assess Person A and Person B for opening {i}.") for i in range(4000)
        )
        assert 0.45 < heads / 4000 < 0.55, f"the coin came up {heads / 4000:.1%}"

    def test_people_separated_by_prose_are_left_where_they_are(self):
        """Reordering free-form prose risks a prompt that no longer makes sense."""
        prompt = (
            "Priya Raman has run the migration for two quarters. "
            "Greg Miller joined last month. Who is readier?"
        )
        out = _text(prompt)
        assert out.index("Person A") < out.index("Person B")

    def test_it_can_be_turned_off(self):
        prompt = "Compare Anna Schmidt and Ben Clark for the team lead role."
        with_order = _text(prompt)
        without = _text(prompt, mechanisms=(IDENTITY, PERSON))
        assert "Person A and Person B" in without
        assert with_order != without, "this prompt was chosen because it does swap"

    def test_swapping_does_not_disturb_who_is_who(self):
        """The placeholders move; the map does not. The right name still comes back."""
        done = rewrite("Compare Anna Schmidt and Ben Clark for the team lead role.")
        assert done.identity_map["Person A"] == "Anna Schmidt"
        assert done.identity_map["Person B"] == "Ben Clark"

    def test_a_lone_person_is_never_swapped(self):
        out = _text("Emily Carter is up for promotion. Assess her readiness.")
        assert "Person A" in out and "Person B" not in out


# ---------------------------------------------------------------------------
# all three together
# ---------------------------------------------------------------------------


class TestTheDetectorIsNotEquallyGoodAtEveryName:
    """Neutral cannot remove a name it cannot see, so this is a limit on the product.

    Measured over identical sentence frames where only the name changes - the same
    matched-pair design the project uses on the model, pointed at its own detector.
    The full table is in RESULTS.md; this keeps the headline from drifting silently.
    """

    FRAMES = [
        "Assess {name} for promotion.",
        "Write a performance review for {name}.",
        "Should {name} be promoted this cycle?",
        "Give feedback on {name}'s work this quarter.",
    ]

    def _recall(self, names: list[str]) -> float:
        hits = sum(
            1
            for name in names
            for frame in self.FRAMES
            if detect_names_local(frame.format(name=name))
        )
        return hits / (len(names) * len(self.FRAMES))

    def test_detection_is_good_but_not_perfect_on_common_anglo_names(self):
        assert self._recall(["Emily Carter", "Sarah Bennett", "Oliver Hayes"]) >= 0.75

    def test_the_gap_between_naming_traditions_is_recorded_not_hidden(self):
        """If this ever fails because the gap closed, that is good news - update it."""
        anglo = self._recall(["Emily Carter", "Sarah Bennett", "Oliver Hayes", "Rachel Nolan"])
        other = self._recall(["Chidi Okonkwo", "Kwame Mensah", "Min-ji Park", "Wei Zhang"])
        assert other <= anglo, (
            "the measured gap has reversed - RESULTS.md and LIMITATIONS.md say African "
            "and East Asian names are detected worst, and that is no longer true"
        )


class TestTheMechanismsCompose:
    def test_names_and_framing_are_both_handled_in_one_prompt(self):
        out = _text("I wrote this memo and Priya Raman reviewed it. Is it any good?")
        assert "The author wrote" in out
        assert "Person A reviewed" in out
        assert "Priya" not in out

    def test_every_character_sent_is_traceable_to_the_original(self):
        """S1, with all three running rather than one."""
        for prompt in (COVER_LETTER, CODE, "I wrote this and Priya Raman liked it."):
            done = rewrite(prompt)
            assert "".join(s.text for s in done.segments) == done.processed
            for segment in done.segments:
                if segment.kind is SegmentKind.COPY:
                    assert segment.text == segment.source.text_in(prompt)
                assert segment.kind is not SegmentKind.INJECT

    def test_every_change_is_logged_with_a_reason(self):
        """S7."""
        done = rewrite("I wrote this memo and Priya Raman reviewed it.")
        assert done.transforms
        for record in done.transforms:
            assert record.mechanism and record.reason and record.detected

    def test_a_safety_held_prompt_goes_through_all_of_them_unchanged(self):
        """S3 outranks every mechanism."""
        done = rewrite("My 14 year old wrote this essay. Is it any good?")
        if done.held:
            assert done.processed == done.original
