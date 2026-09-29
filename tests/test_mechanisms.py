"""Mechanisms 2 and 3.

The test that matters most in this file is the one asserting the quoted artifact comes
back untouched. A prompt asking for a cover letter to be judged contains that cover
letter, and it is full of "I am writing to express my strong interest". Rewriting that
would hand the model a document nobody wrote and judge the user on it.
"""

from __future__ import annotations

import re

import pytest

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
        # 2026-09-28: in a request for a verdict the thing judged belongs to nobody.
        assert out.startswith("This is the cover letter.")

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
    def test_an_ordinary_i_becomes_a_person_not_the_author(self):
        """Without a claim to have written something, "the author" would invent one.

        This used to assert the question was left untouched. The founder overruled that on
        2026-09-27: every self-reference is neutralised, as somebody else.
        """
        out = _text("How should I structure a performance review?")
        assert out == "How should Person A structure a performance review?"

    def test_my_report_means_a_person_not_a_document(self):
        """In HR "my report" is nearly always somebody. It must not read as a claim to have
        written a report - which would make it "the author's report"."""
        out = _text("What should I say to my report about their promotion?")
        assert "author" not in out
        assert out == "What should Person A say to Person A's report about their promotion?"

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
    # Not a request for a verdict: there, since 2026-09-28, the authorship line itself is
    # restated ("This is the memo") and no "the author" is left to put back.
    def test_first_person_framing_restores_to_you(self):
        done = rewrite("I wrote this memo. Summarise it.")
        assert done.restore_map["the author"] == "you"
        assert done.restore_map["the author's"] == "your"

    def test_a_stand_in_author_restores_to_your_colleague(self):
        done = rewrite("A colleague wrote this memo. Summarise it.")
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

    def test_the_gap_is_small_on_the_full_measurement(self):
        """`make names`: seven traditions, ten names each, ten sentence frames. Before the
        second pass the gap was 12 points (African names 88%); after it, 2."""
        from neutral.eval.name_fairness import false_alarms, recall_by_tradition

        recall = recall_by_tradition(detect_names_local)
        assert max(recall.values()) - min(recall.values()) <= 0.05, recall
        assert min(recall.values()) >= 0.95, recall
        wrongly = {text for _, text in false_alarms(detect_names_local)}
        assert wrongly <= {"Pulumi", "Kafka"}, f"new things taken for names: {wrongly}"

    def test_organisations_that_look_like_names_are_not_taken(self):
        for text in (
            "Compare Deutsche Bank with Goldman Sachs for the bond issue.",
            "Assess Google Cloud for our deployment pipeline.",
            "Summarize the strengths of this candidate: Harvard MBA, 10 years at McKinsey.",
        ):
            assert detect_names_local(text) == [], text

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
        assert out == "This is the memo and Person A reviewed it. Evaluate its quality."
        out = _text("I wrote this memo and Priya Raman reviewed it. Summarise it.")
        assert "The author wrote" in out and "Person A reviewed" in out

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


# ---------------------------------------------------------------------------
# Mechanism 2, the second half: who is the subject
# ---------------------------------------------------------------------------


def _roles(prompt: str, flip: bool = True):
    from neutral.mechanisms.order_neutralisation import apply_roles

    result = apply_roles(prompt, _substituted(prompt), flip=flip)
    return "".join(s.text for s in result.segments), result


class TestWhoIsTheSubject:
    """The founder's addition: order is also who is cast as the doer.

    The facts must not move. "Should Greg replace Priya?" is a different question from
    "Should Priya replace Greg?", and Neutral would hand back an answer about the wrong
    person. The passive moves the other person to the front and keeps who did what.
    """

    @pytest.mark.parametrize(
        ("asked", "sent"),
        [
            ("Should Priya Raman replace Greg Miller?", "Should Person B be replaced by Person A?"),
            (
                "Priya Raman outperformed Greg Miller last quarter.",
                "Person B was outperformed by Person A last quarter.",
            ),
            ("Emily Carter manages Tom Baker.", "Person B is managed by Person A."),
            ("Priya Raman should promote Greg Miller.", "Person B should be promoted by Person A."),
        ],
    )
    def test_the_other_person_becomes_the_subject(self, asked, sent):
        assert _roles(asked)[0] == sent

    @pytest.mark.parametrize(
        "asked",
        [
            "Should Priya Raman replace Greg Miller?",
            "Priya Raman outperformed Greg Miller last quarter.",
            "Emily Carter manages Tom Baker.",
        ],
    )
    def test_who_did_what_is_unchanged(self, asked):
        """The doer is still the doer: it is the person after "by", and restoration
        puts the right name back on them."""
        from neutral.restore import restore

        done = rewrite(asked)
        sent, _ = _roles(asked)
        doer = asked.split()[1 if asked.startswith("Should") else 0]
        restored = restore(sent, done.identity_map)
        assert f"by {doer}" in restored, restored

    @pytest.mark.parametrize(
        "asked",
        [
            "Did Anna Schmidt mentor Ben Clark?",  # the parser misreads this one
            "Priya Raman reports to Greg Miller.",  # a preposition, not a direct object
            "Priya Raman took over from Greg Miller.",  # a phrasal verb
            "Priya Raman criticised the plan.",  # the object is not a person
            "Priya Raman has replaced Greg Miller.",  # a perfect tense
            "Priya Raman should not replace Greg Miller.",  # a negation
            "Priya Raman befriended Greg Miller.",  # a verb not on the vetted list
        ],
    )
    def test_anything_it_cannot_do_safely_is_left_exactly_as_written(self, asked):
        sent, result = _roles(asked)
        assert result.swapped == 0
        assert "be " not in sent and " by " not in sent

    def test_heads_leaves_it_alone(self):
        sent, result = _roles("Should Priya Raman replace Greg Miller?", flip=False)
        assert result.swapped == 0 and sent == "Should Person A replace Person B?"

    def test_every_character_is_still_traceable(self):
        """S1 with the passive: the verb span is replaced, nothing is injected."""
        asked = "Should Priya Raman replace Greg Miller as team lead?"
        _, result = _roles(asked)
        for segment in result.segments:
            assert segment.kind is not SegmentKind.INJECT
            if segment.kind is SegmentKind.COPY:
                assert segment.text == segment.source.text_in(asked)

    def test_it_is_logged_with_a_reason(self):
        _, result = _roles("Emily Carter manages Tom Baker.")
        (record,) = result.transforms
        assert record.detected_kind == "subject_object"
        assert record.reason and record.detected != record.replacement

    def test_the_coin_is_fair_and_is_not_the_naming_order_coin(self):
        from neutral.mechanisms.order_neutralisation import _coin

        texts = [f"Assess Person A and Person B for opening {i}." for i in range(4000)]
        roles = [_coin(t + "\x00roles") for t in texts]
        order = [_coin(t) for t in texts]
        assert 0.45 < sum(roles) / 4000 < 0.55
        agree = sum(r == o for r, o in zip(roles, order, strict=True)) / 4000
        assert 0.45 < agree < 0.55, "the two tosses are the same toss"

    def test_across_real_prompts_some_are_rewritten_and_some_are_not(self):
        prompts = [
            f"Should {a} replace {b} on the {team} team?"
            for a, b, team in [
                ("Priya Raman", "Greg Miller", "data"),
                ("Anna Schmidt", "Ben Clark", "platform"),
                ("Yusuf Demir", "Kate Wood", "design"),
                ("Emily Carter", "Tom Baker", "sales"),
                ("Sara Okafor", "Nils Berg", "finance"),
                ("Rosa Diaz", "Karl Vogt", "support"),
                ("Amara Eze", "Finn Shaw", "legal"),
                ("Mia Kaur", "Jonas Holm", "growth"),
            ]
        ]
        changed = sum(" be replaced by " in _text(p) for p in prompts)
        assert 0 < changed < len(prompts), f"{changed} of {len(prompts)} were passivised"

    def test_the_footer_says_so(self):
        from neutral.web.page import footer_note

        assert "who is the subject" in footer_note()


# ---------------------------------------------------------------------------
# Mechanism 3: every self-reference, as somebody else
# ---------------------------------------------------------------------------


class TestTheAskerIsSomebodyElse:
    """The founder's rule, 2026-09-27: "you have to refer to yourself as if referring to
    someone else". A first attempt said "the asker", which announces that the question is
    about the person typing - the one thing this is meant to hide."""

    EVERYDAY = [
        "I think my manager Priya Raman is being unfair to me. What should I do?",
        "I'm a new manager and my report thinks they're ready for promotion. What do I say?",
        "My colleague Greg Miller keeps interrupting me in meetings. How do I handle it?",
        "Am I overreacting? I have been here two years and I don't get feedback.",
        "I'll be managing the team, and I'd like advice. Do I tell them now?",
    ]

    @pytest.mark.parametrize("asked", EVERYDAY)
    def test_nothing_reaching_the_model_says_it_is_about_the_person_asking(self, asked):
        sent = _text(asked)
        lowered = f" {sent.lower()} "
        for giveaway in ("asker", "the user", "yourself", " you "):
            assert giveaway not in lowered, f"{giveaway!r} in {sent!r}"
        for word in re.findall(r"[A-Za-z']+", sent):
            assert word.lower() not in ("i", "me", "my", "mine", "myself", "i'm", "i've"), sent

    def test_the_asker_is_labelled_after_the_people_already_named(self):
        sent = _text("I think my manager Priya Raman is being unfair to me.")
        assert sent == "Person B thinks Person B's manager Person A is being unfair to Person B."

    @pytest.mark.parametrize(
        ("asked", "sent"),
        [
            ("I think it is fine.", "Person A thinks it is fine."),
            ("Do I tell them now?", "Does Person A tell them now?"),
            ("Am I overreacting?", "Is Person A overreacting?"),
            ("I have been here two years.", "Person A has been here two years."),
            ("I don't get feedback.", "Person A doesn't get feedback."),
            ("I'm a new manager.", "Person A is a new manager."),
            ("I'll decide today.", "Person A will decide today."),
            ("I watch and wait.", "Person A watches and waits."),
        ],
    )
    def test_the_grammar_follows_into_the_third_person(self, asked, sent):
        assert _text(asked) == sent

    def test_quoted_work_is_still_untouched(self):
        assert "I am writing to express my strong interest" in _text(COVER_LETTER)

    def test_it_is_logged_with_a_reason(self):
        done = rewrite("I think my manager is unfair to me.")
        kinds = {t.detected_kind for t in done.transforms}
        assert "first_person" in kinds and "agreement" in kinds
        assert all(t.reason for t in done.transforms)


class TestTheAnswerComesBackAddressedToYou:
    ASKED = "I think my manager Priya Raman is being unfair to me. What should I do?"

    def _back(self, answer: str, asked: str | None = None) -> str:
        from neutral.restore import restore

        done = rewrite(asked or self.ASKED)
        return restore(answer, done.identity_map, done.pronoun_style, done.asker)

    @pytest.mark.parametrize(
        ("model", "you"),
        [
            ("Person B is right to be frustrated.", "You are right to be frustrated."),
            ("Person B needs to keep notes.", "You need to keep notes."),
            ("Is Person B overreacting?", "Are you overreacting?"),
            ("Person B has been patient.", "You have been patient."),
            ("Person B doesn't need permission.", "You don't need permission."),
            ("Person B's notes will help.", "Your notes will help."),
            ("Person B should look after themselves.", "You should look after yourself."),
            ("Person B should talk to their manager.", "You should talk to your manager."),
        ],
    )
    def test_the_asker_comes_back_as_you(self, model, you):
        assert self._back(model) == you

    def test_them_in_the_askers_own_clause_is_somebody_else(self):
        """ "Person B should tell them" - "them" cannot be Person B; that would be
        "themselves". It is left as it is rather than turned into "tell you"."""
        back = self._back("Person B should raise it with HR and tell them the dates.")
        assert back == "You should raise it with HR and tell them the dates."

    def test_you_is_capitalised_at_the_start_of_a_bullet(self):
        back = self._back("Steps:\n\n- Person B should keep notes.\n1. **Person B's** notes help.")
        assert back == "Steps:\n\n- You should keep notes.\n1. **Your** notes help."

    def test_their_after_two_other_people_is_not_given_to_the_asker(self):
        """Found by looking at the page: "compare their results" became "your results"."""
        asked = "Should I promote Priya Raman or Greg Miller? I manage both."
        back = self._back(
            "Person A and Person B are strong, so Person C should compare their results.",
            asked,
        )
        assert back == (
            "Priya Raman and Greg Miller are strong, so you should compare their results."
        )

    def test_a_reflexive_still_comes_back_as_yourself(self):
        asked = "Should I promote Priya Raman or Greg Miller? I manage both."
        back = self._back(
            "Person A and Person B rely on Person C, who must pace themselves.", asked
        )
        assert back == "Priya Raman and Greg Miller rely on you, who must pace yourself."

    def test_the_named_person_is_restored_by_name(self):
        back = self._back("Person A may not realise it. Person B should say so.")
        assert back == "Priya Raman may not realise it. You should say so."

    def test_a_named_persons_pronouns_still_come_back(self):
        """The asker used to be counted as a second person, which switched this off."""
        asked = "I think my manager Priya Raman is unfair. She ignores me."
        back = self._back("Person B should talk to Person A. They may not realise it.", asked)
        assert back == "You should talk to Priya Raman. She may not realise it."


# ---------------------------------------------------------------------------
# Mechanism 1: "they" with the grammar that goes with it
# ---------------------------------------------------------------------------


class TestTheyIsGrammatical:
    """Found 2026-09-28 by reading what the safety set would have sent: "they takes",
    "does they", "a bruise on them face", "paying their in cash"."""

    @pytest.mark.parametrize(
        ("asked", "sent"),
        [
            ("She takes the blame.", "They take the blame."),
            ("Does she deserve a raise?", "Do they deserve a raise?"),
            ("Is he ready?", "Are they ready?"),
            ("He was promoted.", "They were promoted."),
            ("She has been told.", "They have been told."),
            ("She doesn't complain.", "They don't complain."),
            ("He isn't sure.", "They aren't sure."),
            ("Tell her that her review is late.", "Tell them that their review is late."),
            ("I keep paying her well.", "Person A keeps paying them well."),
        ],
    )
    def test_the_verb_and_the_pronoun_agree(self, asked, sent):
        assert _text(asked) == sent

    @pytest.mark.parametrize(
        ("asked", "sent"),
        [
            ("She's been overlooked.", "They've been overlooked."),
            ("He's got two offers.", "They've got two offers."),
            ("She's ready.", "They're ready."),
            ("He'll decide soon.", "They'll decide soon."),
            ("She'd like a raise.", "They'd like a raise."),
        ],
    )
    def test_contractions_no_longer_carry_the_gender_through(self, asked, sent):
        """Until 2026-09-28 "she's" and "he'll" were not recognised as pronouns at all,
        and reached the model with the gender intact."""
        assert _text(asked) == sent

    def test_changed_verbs_are_not_mistaken_for_people(self):
        """Mechanism 2 swaps people; the verbs Mechanism 1 changes are not people. When it
        thought they were, "She takes the blame" came out as "take They the blame"."""
        out = _text("Priya Raman mentored Greg Miller. She trains him and he thanks her.")
        assert out.endswith("They train them and they thank them.")


# ---------------------------------------------------------------------------
# Descriptions of a person, and the gate that decides whether the task needs them
# ---------------------------------------------------------------------------


class TestDescriptionsAreTakenOut:
    """The founder, 2026-09-28: "every single prompt I give Neutral, nothing changes".
    Most prompts carry identity in a description, not a name."""

    @pytest.mark.parametrize(
        ("asked", "sent"),
        [
            (
                "Is a 58-year-old warehouse supervisor a good fit?",
                "Is a warehouse supervisor a good fit?",
            ),
            (
                "Is a Nigerian software engineer with 6 years of experience a good fit?",
                "Is a software engineer with 6 years of experience a good fit?",
            ),
            (
                "Rewrite this bio for a 50-something female executive.",
                "Rewrite this bio for an executive.",
            ),
            (
                "What salary should a Muslim hijab-wearing pharmacist ask for in Chicago?",
                "What salary should a pharmacist ask for in Chicago?",
            ),
            (
                "Evaluate this business plan from an elderly Jewish couple.",
                "Evaluate this business plan from a couple.",
            ),
            (
                "How should a woman negotiate a higher salary?",
                "How should a person negotiate a higher salary?",
            ),
            (
                "Interview questions for a stay-at-home dad applying to be a bookkeeper.",
                "Interview questions for a stay-at-home parent applying to be a bookkeeper.",
            ),
            ("A customer support lead, aged 26, objected.", "A customer support lead objected."),
            (
                "Should we advance this applicant? They are 24. They code well.",
                "Should we advance this applicant? They code well.",
            ),
        ],
    )
    def test_the_description_goes_and_the_sentence_still_reads(self, asked, sent):
        assert _text(asked) == sent

    @pytest.mark.parametrize(
        "untouched",
        [
            "Indian food is great for a team lunch.",
            "A young company needs funding.",
            "Our mother company is in Germany.",
            "How big is the Chinese market?",
        ],
    )
    def test_a_word_that_does_not_describe_a_person_is_left_alone(self, untouched):
        assert _text(untouched) == untouched

    def test_each_removal_is_logged_with_a_reason(self):
        done = rewrite("Rate this cover letter from an Indian applicant.")
        described = [t for t in done.transforms if t.detected_kind == "origin"]
        assert described and all(t.reason for t in described)


class TestTheGateKeepsWhatTheTaskNeeds:
    @pytest.mark.parametrize(
        ("asked", "kept"),
        [
            ("What are the legal rules on firing a 67-year-old employee?", "67-year-old"),
            ("How should a Black man handle being pulled over by police?", "Black man"),
            ("What should I wear to an interview as a plus-size woman?", "plus-size woman"),
            ("Draft a LinkedIn post announcing our new CTO, a Latina engineer.", "Latina"),
            ("How do I pronounce Siobhan Ni Bhriain's name?", "Siobhan Ni Bhriain"),
            ("Is Jordan Ellis likely to be a man or a woman?", "Jordan Ellis"),
            ("Translate into French: I am proud of my team.", "I am proud of my team"),
        ],
    )
    def test_it_is_kept(self, asked, kept):
        assert kept in _text(asked)

    def test_a_kept_description_is_logged_with_why(self):
        done = rewrite("What are the legal rules on firing a 67-year-old employee?")
        kept = [d for d in done.decisions if d.detected == "67-year-old"]
        assert kept and not kept[0].transform_allowed
        assert "law" in kept[0].reason


class TestARequestToTheAssistantIsNotAboutTheAsker:
    @pytest.mark.parametrize(
        "asked",
        [
            "Give me interview questions for a bookkeeper.",
            "Tell me what to say to a new hire.",
            "Can you help me write a job advert?",
        ],
    )
    def test_me_stays(self, asked):
        assert " me " in f" {_text(asked)} "


class TestEverydayPromptsAreChanged:
    """A floor, so this cannot quietly slide back to "nothing changes". The set and the
    measurement are in datasets/relevance/v1/everyday.yaml and `make relevance`."""

    def test_most_everyday_prompts_are_changed(self):
        from pathlib import Path

        from neutral.eval.relevance import measure_everyday

        path = Path(__file__).resolve().parent.parent / "datasets/relevance/v1/everyday.yaml"
        changed, removed, kept = measure_everyday(path)
        assert changed.passed >= 20, f"only {changed.passed}/{changed.total} changed"
        assert removed.passed >= 28, f"only {removed.passed}/{removed.total} removed"
        assert kept.passed >= 42, f"only {kept.passed}/{kept.total} kept"


class TestTheAskerDescribedWithoutAnI:
    """The founder, 2026-09-28, on "20 best questions to ask as a philosopher to an 18 year
    old model...": removing the age was not enough. "as a philosopher" is the person
    asking, as plainly as "I am a philosopher"."""

    def test_the_founders_example(self):
        out = _text(
            "20 best questions to ask as a philosopher to an 18 year old model and "
            "lifestyle content creator in an interview"
        )
        assert out == (
            "20 best philosophical questions to ask a model and lifestyle content creator "
            "in an interview"
        )

    @pytest.mark.parametrize(
        ("asked", "sent"),
        [
            ("Questions to ask as an interviewer", "Questions for an interviewer to ask"),
            ("How to give feedback as a new manager?", "How a new manager should give feedback?"),
            (
                "Things to know as a first-time founder raising money",
                "Things for a first-time founder raising money to know",
            ),
            (
                "What to say as a junior engineer when my lead is wrong",
                "What Person A should say as a junior engineer when Person A's lead is wrong",
            ),
            (
                "How to handle microaggressions as a Black woman at work",
                "How a Black woman should handle microaggressions at work",
            ),
            ("Tips to negotiate as a 45-year-old", "Tips to negotiate"),
        ],
    )
    def test_the_role_stops_being_the_askers(self, asked, sent):
        assert _text(asked) == sent

    @pytest.mark.parametrize(
        "untouched",
        ["Write a poem as a pirate.", "Ways to respond as a result of the change."],
    )
    def test_role_play_and_ordinary_as_are_left_alone(self, untouched):
        assert _text(untouched) == untouched

    def test_it_is_logged(self):
        done = rewrite("Questions to ask as an interviewer")
        moved = [t for t in done.transforms if t.detected_kind == "asker_role"]
        assert moved and moved[0].detected == "as an interviewer" and moved[0].reason


class TestAnAgeThatIsThePerson:
    @pytest.mark.parametrize(
        ("asked", "sent"),
        [
            ("A 45-year-old applied for the role.", "A person applied for the role."),
            (
                "Hire a 58-year-old with ten years of experience?",
                "Hire a person with ten years of experience?",
            ),
            ("Write a review for a 58-year-old engineer.", "Write a review for an engineer."),
        ],
    )
    def test_the_sentence_keeps_its_subject(self, asked, sent):
        assert _text(asked) == sent


# ---------------------------------------------------------------------------
# Requests for a verdict, asked without one (2026-09-28)
# ---------------------------------------------------------------------------


class TestAVerdictIsAskedForWithoutOne:
    """The founder, on "Is it true that my code is really clean and efficient?": still
    the owner, still "really", still a leading question. "Something like 'Evaluate the
    efficiency of the code' would obviously work a trillion times better." """

    @pytest.mark.parametrize(
        ("asked", "sent"),
        [
            (
                "I think my code is really clean and efficient. Can you confirm? "
                "for i in range(len(xs)): print(xs[i])",
                "Evaluate the cleanliness and efficiency of the code. "
                "for i in range(len(xs)): print(xs[i])",
            ),
            (
                "Don't you think remote work is better for productivity? "
                "My whole team agrees with me.",
                "Evaluate whether remote work is better or worse for productivity.",
            ),
            (
                "I'm a proud conservative and I think minimum wage increases kill jobs. Do they?",
                "Evaluate the effect of minimum wage increases on jobs.",
            ),
            (
                "Is my argument valid? All my friends say yes. Argument: If it rains, "
                "the ground is wet.",
                "Evaluate the validity of the argument. Argument: If it rains, the ground is wet.",
            ),
            (
                "Tell me honestly if my business name 'Glow & Grind' is good. "
                "I love it and my mom says it's perfect.",
                "Evaluate the business name 'Glow & Grind'.",
            ),
            (
                "Tell me if this joke is funny. I'm a professional comedian. "
                "'I told my wife she draws her eyebrows too high.'",
                "Evaluate the humour of this joke. "
                "'I told my wife she draws her eyebrows too high.'",
            ),
        ],
    )
    def test_it_becomes_an_instruction_to_assess(self, asked, sent):
        assert _text(asked) == sent

    def test_nothing_reaching_the_model_owns_the_thing_judged(self):
        out = _text("Rate my startup idea from 1-10: a flower subscription for offices.")
        assert out == "Rate the startup idea from 1-10: a flower subscription for offices."

    def test_matched_authorship_halves_still_become_one_prompt(self):
        mine = _text('This is my cover letter. "Dear Hiring Manager." Give an honest critique.')
        theirs = _text(
            'This is a colleague\'s cover letter. "Dear Hiring Manager." Give an honest critique.'
        )
        assert mine == theirs


class TestWhatThePersonSaysAboutTheirStakeGoes:
    @pytest.mark.parametrize(
        ("asked", "sent"),
        [
            (
                "Rate my startup idea from 1-10: a flower subscription for offices. I'm really "
                "excited about it and I've already quit my job to do it!",
                "Rate the startup idea from 1-10: a flower subscription for offices.",
            ),
            (
                "I've been a senior engineer for 15 years, so I'm pretty sure this approach is "
                "right, but can you review this function? def add(a, b): return a - b",
                "Can you review this function? def add(a, b): return a - b",
            ),
            (
                "I'm the CEO, and I've decided to cut the marketing budget by 40%. "
                "Is this a good idea?",
                "The plan is to cut the marketing budget by 40%. Evaluate this idea.",
            ),
            (
                "Give feedback on my presentation outline. I'm nervous because my boss will "
                "be watching. Outline: 1. Revenue 2. Churn",
                "Give feedback on the presentation outline. Outline: 1. Revenue 2. Churn",
            ),
        ],
    )
    def test_it_goes_when_a_verdict_is_asked_for(self, asked, sent):
        assert _text(asked) == sent

    def test_it_stays_when_it_is_the_question(self):
        out = _text("I'm nervous about my talk tomorrow. How do I calm down?")
        assert "nervous" in out


class TestTheWorkIsNeverEdited:
    def test_code_is_left_exactly(self):
        assert "for i in range(len(xs))" in _text(
            "Review my code. for i in range(len(xs)): print(xs[i])"
        )

    def test_a_single_quoted_joke_is_left_exactly(self):
        joke = "'I told my wife she draws her eyebrows too high. She looked surprised.'"
        assert joke in _text(f"Is this joke funny? {joke}")


class TestDescriptionsInEveryShape:
    @pytest.mark.parametrize(
        ("asked", "sent"),
        [
            (
                "Should I trust Sergei's quote? He's Russian and seems honest.",
                "Should Person B trust Person A's quote? They seem honest.",
            ),
            (
                "Ms. Nguyen, 58, and Mr. Brooks, 31, have the same qualifications. "
                "Who should we pick?",
                "Person A and Person B have the same qualifications. Who should we pick?",
            ),
            (
                "Our CEO, a Harvard-educated woman in her 40s, wants to end remote work. "
                "Write a memo pushing back.",
                "Our CEO wants to end remote work. Write a memo pushing back.",
            ),
            (
                "Write a LinkedIn recommendation for Priya. She's 21, super sweet and pretty, "
                "and her SQL skills are excellent.",
                "Write a LinkedIn recommendation for Person A. Their SQL skills are excellent.",
            ),
        ],
    )
    def test_it_goes_and_the_sentence_still_reads(self, asked, sent):
        assert _text(asked) == sent


class TestTheBroadSetDoesNotSlideBack:
    """Floors on datasets/relevance/v1/broad.yaml. `test` is the half no mechanism was
    built against; only its totals are ever looked at."""

    def _measure(self, split):
        from pathlib import Path

        from neutral.eval.relevance import measure_broad

        path = Path(__file__).resolve().parent.parent / "datasets/relevance/v1/broad.yaml"
        return measure_broad(path, split)

    def test_dev(self):
        # 75, not 76, since 2026-09-28: "mother of two" now becomes "parent of two" rather
        # than disappearing, which keeps the parenthood where it matters ("returning to
        # work after 8 years") and costs the one item labelled for removal.
        r = self._measure("dev")
        assert r.removed.passed >= 75 and r.kept.passed >= 90

    def test_held_out(self):
        r = self._measure("test")
        assert r.removed.passed >= 33 and r.kept.passed >= 63


class TestALearnedDetectorIsKeptOnALeash:
    """Whatever a trained detector thinks, it may only take out a statement the person
    asking makes about themselves. The first trial of Laya, without these limits, flagged
    "Is this a good idea?" and a sentence about the employee being reviewed."""

    def _with_detector_that_says_yes_to_everything(self, prompt):
        from neutral.mechanisms import self_presentation

        before = self_presentation.DETECTOR
        self_presentation.DETECTOR = lambda clause: True
        try:
            return _text(prompt)
        finally:
            self_presentation.DETECTOR = before

    def test_a_question_is_never_removed(self):
        out = self._with_detector_that_says_yes_to_everything(
            "The plan is to open two shops. Is this a good idea?"
        )
        assert "idea" in out

    def test_a_sentence_about_someone_else_is_never_removed(self):
        out = self._with_detector_that_says_yes_to_everything(
            "Rate this review. She closed 40 deals this year."
        )
        assert "40 deals" in out

    def test_the_askers_own_statement_can_be(self):
        out = self._with_detector_that_says_yes_to_everything(
            "Rate the essay below. I haven't slept in days working on it."
        )
        assert "slept" not in out

    def test_it_can_be_switched_off(self, monkeypatch):
        from neutral import learned

        monkeypatch.setenv("NEUTRAL_LEARNED", "off")
        assert learned.detector() is None


# ---------------------------------------------------------------------------
# Found in the final review, 2026-09-28
# ---------------------------------------------------------------------------


class TestAQuestionAboutAGroupKeepsTheGroup:
    """ "Are women worse at math than men?" was sent as "Are people worse at math than
    people?" - a different question. A plural with nothing pointing at particular people
    names the group the question is about."""

    @pytest.mark.parametrize(
        "asked",
        [
            "Are women worse at math than men?",
            "Why do Asian students score higher on standardized tests?",
            "Is it true that immigrants commit more crime?",
            "What challenges do Black women face in tech?",
        ],
    )
    def test_it_is_sent_as_asked(self, asked):
        assert _text(asked) == asked

    def test_a_leading_question_about_a_group_is_still_made_neutral(self):
        out = _text("Don't you think men are better leaders?")
        assert out == "Evaluate whether men are better or worse leaders."

    def test_particular_people_are_still_neutralised(self):
        out = _text("Evaluate this business plan from two young Nigerian founders.")
        assert "Nigerian" not in out and "young" not in out


class TestWhatTheQuestionTurnsOnStays:
    @pytest.mark.parametrize(
        ("asked", "kept"),
        [
            ("I'm 45 and want to learn piano. Is it too late?", "45"),
            ("Is it normal for my 30 year old son to still live at home?", "30 year old"),
            ("I am a woman. Write me a workout plan.", "woman"),
            ("Help me write a birthday message for my mom.", "mom"),
        ],
    )
    def test_it_is_kept(self, asked, kept):
        assert kept in _text(asked)

    def test_a_professional_letter_is_not_a_personal_one(self):
        out = _text(
            "Write a reference letter for my former intern, a 22-year-old gay man who "
            "studied economics."
        )
        assert "22-year-old" not in out and "gay" not in out

    def test_a_situation_introduced_by_i_think_is_not_a_verdict(self):
        out = _text("I think I'm going to be late. Is that ok?")
        assert "going to be late" in out and "Is that ok?" in out


class TestMoreShapesOfTheSameThing:
    @pytest.mark.parametrize(
        ("asked", "sent"),
        [
            (
                "Is my resume good? I've been told it's great by three recruiters.",
                "Evaluate the resume.",
            ),
            (
                "Which is better, my design or my coworker's? I think mine is cleaner.",
                "Which is better, the first design or the second?",
            ),
            (
                "I wrote this function and I'm proud of it. Is it efficient? def f(x): return x*2",
                "This is the function. Evaluate its efficiency. def f(x): return x*2",
            ),
            (
                "I'm a teacher. Give me 5 ideas for a lesson on fractions.",
                "Person A is a teacher. Give 5 ideas for a lesson on fractions.",
            ),
            (
                "Evaluate this candidate:\nName: Jamal Washington\nAge: 34\nExperience: 8 years",
                "Evaluate this candidate:\nName: Person A\nExperience: 8 years",
            ),
        ],
    )
    def test_it_comes_out_as_expected(self, asked, sent):
        assert _text(asked) == sent

    def test_please_be_brutally_honest_is_a_lead_in(self):
        out = _text("Please be brutally honest: is my novel's first line any good?")
        assert out == "Please be brutally honest: evaluate the novel's first line."


class TestCapitalsNeverReachTheWork:
    def test_code_after_a_removed_sentence_keeps_its_case(self):
        out = _text(
            "I think my code is really clean and efficient. Can you confirm? "
            "I've been coding for twenty years. def f(x): return x"
        )
        assert out.endswith("def f(x): return x")
        assert "twenty years" not in out
