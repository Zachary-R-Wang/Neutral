"""Putting the answer back into natural language.

CLAUDE.md section 4: "Restoration is harder than substitution. Budget accordingly. It is
where demos break."

It broke in exactly the predicted way on the first live run. The model, talking about
"they", wrote "what level are they being considered for". Swapping the pronoun on its own
produced "what level are she being considered for" - a sentence no person would write,
sitting in the middle of an otherwise good answer.
"""

from __future__ import annotations

import pytest

from neutral.restore import restore

ONE_PERSON = {"Person A": "Emily Carter"}
FEMININE = {"*": "feminine"}
MASCULINE = {"*": "masculine"}


def back(text: str, style=FEMININE, names=None) -> str:
    return restore(text, ONE_PERSON if names is None else names, style)


class TestNamesComeBack:
    def test_a_placeholder_becomes_the_real_name(self):
        assert back("Person A shipped it.") == "Emily Carter shipped it."

    def test_a_possessive_placeholder_comes_back(self):
        assert "Emily Carter's" in back("Person A's work was strong.")


class TestTheVerbAgreesWithThePronounItGoesBackTo:
    """The bug found on the first live run."""

    @pytest.mark.parametrize(
        ("neutral", "expected"),
        [
            (
                "What level are they being considered for?",
                "What level is she being considered for?",
            ),
            ("They are ready.", "She is ready."),
            ("They were thorough.", "She was thorough."),
            ("They have shipped twice.", "She has shipped twice."),
            ("They do not hesitate.", "She does not hesitate."),
            ("Do they need support?", "Does she need support?"),
            ("Were they consulted?", "Was she consulted?"),
            ("Have they improved?", "Has she improved?"),
            ("They're strong.", "She's strong."),
            ("They've missed deadlines.", "She's missed deadlines."),
            ("They aren't communicating.", "She isn't communicating."),
            ("They haven't asked.", "She hasn't asked."),
        ],
    )
    def test_common_agreements(self, neutral, expected):
        assert back(neutral) == expected

    def test_it_works_for_masculine_too(self):
        assert back("They are ready.", MASCULINE) == "He is ready."
        assert back("Are they ready?", MASCULINE) == "Is he ready?"

    def test_no_sentence_is_left_saying_are_she(self):
        text = (
            "They are strong. What level are they at? They have grown and they do well, "
            "though they aren't always visible."
        )
        out = back(text)
        for wrong in ("are she", "were she", "have she", "do she", "aren't she"):
            assert wrong not in out, f"restoration produced {wrong!r}: {out}"


class TestWhenItCannotTellWhoIsMeant:
    def test_pronouns_are_left_neutral_with_two_people(self):
        """An answer that confidently discusses the wrong person is the worst outcome."""
        out = restore(
            "Person A and Person B disagreed; they both had a point.",
            {"Person A": "Emily", "Person B": "Ethan"},
            FEMININE,
        )
        assert "they both had a point" in out
        assert "Emily" in out and "Ethan" in out

    def test_agreement_is_not_touched_either_with_two_people(self):
        out = restore("They are both ready.", {"Person A": "Emily", "Person B": "Ethan"}, FEMININE)
        assert out == "They are both ready."

    def test_no_style_means_no_pronoun_change(self):
        assert back("They are ready.", None) == "They are ready."


class TestCapitalisationSurvives:
    def test_a_sentence_opening_pronoun_stays_capitalised(self):
        assert back("They led the project.").startswith("She led")

    def test_a_mid_sentence_pronoun_stays_lower_case(self):
        assert "that they" not in back("I think that they led it.")
        assert "that she led it" in back("I think that they led it.")


class TestOnlyThePersonsPronounsAreConverted:
    """Found in a live answer, not in a test.

    The model wrote "if blockers or scope creep emerge, surfacing them in week one".
    "Them" meant the blockers. Converting every neutral pronoun turned it into "surfacing
    her in one week", which is not what the model said.

    The rule is recency - a pronoun refers to the most recently mentioned thing it could
    refer to - so a pronoun is only converted when the person was mentioned more recently
    than any plural noun.
    """

    def test_a_pronoun_about_things_is_left_alone(self):
        out = back(
            "Work on flagging risks earlier - if blockers or scope creep emerge, "
            "surfacing them in week one gives the team options."
        )
        assert "surfacing them" in out
        assert "surfacing her" not in out

    def test_a_pronoun_about_the_person_is_still_converted(self):
        assert "her estimates" in back("Person A should tighten their estimates.")

    def test_the_person_carries_across_sentences(self):
        out = back("Person A missed a deadline. They should improve their planning.")
        assert "She should improve her planning" in out

    def test_a_nearer_plural_wins(self):
        out = back("Person A owns the service. The other teams rely on it; they escalate.")
        assert "they escalate" in out

    def test_with_nothing_else_mentioned_the_person_is_assumed(self):
        """The answer is about them; a plural has to actually appear to take precedence."""
        assert back("They are strong on delivery.") == "She is strong on delivery."

    def test_agreement_still_follows_the_conversion(self):
        out = back("Person A is ready. They have shipped twice and they do not hesitate.")
        assert "She has shipped" in out
        assert "she does not hesitate" in out


def test_the_language_model_is_installed_so_detection_does_not_degrade_silently():
    """It was pruned once by a dependency sync and nothing failed - it just got worse."""
    from neutral.detect import _model

    assert _model() is not None, (
        "the local language model is missing, so name detection and pronoun resolution "
        "have silently fallen back to rules. Run `make dev` to reinstall it."
    )
