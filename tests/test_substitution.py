"""How names are found and grouped before they are replaced.

Grouping is where this mechanism can do real damage quietly. Replacing a name with a
placeholder is visible and checkable. Deciding that two names are the same person, or
that one person is two, changes what the model is told about the world - and nothing in
the rewritten prompt looks wrong afterwards.
"""

from __future__ import annotations

from neutral.detect import detect_names_offline, find_pronouns
from neutral.mechanisms.identity_substitution import apply, group_people
from neutral.pipeline import preview


def rewrite(prompt: str) -> str:
    return preview(prompt).processed_prompt


def people_in(prompt: str) -> int:
    findings = detect_names_offline(prompt)
    return len(set(group_people(findings).values()))


class TestTitlesBelongToTheirName:
    def test_a_title_and_name_are_one_person(self):
        """The bug a user found: "Mr. Nell" became "Person A. Person B"."""
        assert people_in("Please email my teacher Mr. Nell about the reference.") == 1
        assert "Person A" in rewrite("Please email my teacher Mr. Nell about the reference.")

    def test_the_title_is_removed_with_the_name(self):
        """ "Mr" states the person's gender, which is the signal being removed."""
        out = rewrite("Please email my teacher Mr. Nell about the reference.")
        assert "Mr" not in out
        assert "Nell" not in out

    def test_titles_without_a_full_stop_work_too(self):
        assert people_in("Ask Mrs Chen for feedback.") == 1

    def test_a_title_with_no_name_after_it_is_not_a_person(self):
        assert people_in("The rate is set by the board.") == 0


class TestGroupingDoesNotInventOrMergePeople:
    def test_two_people_sharing_a_title_stay_two_people(self):
        """ "Mr Smith" and "Mr Jones" share only the word "mr"."""
        prompt = "Mr Smith and Mr Jones disagreed about the plan."
        assert people_in(prompt) == 2
        out = rewrite(prompt)
        assert "Person A" in out and "Person B" in out

    def test_two_spellings_of_one_person_stay_one_person(self):
        prompt = "Emily Carter missed the deadline. Emily has been told."
        assert people_in(prompt) == 1
        out = rewrite(prompt)
        assert "Person B" not in out

    def test_two_people_sharing_a_surname_are_still_grouped_together(self):
        """A known limitation, asserted so it is a decision rather than a surprise.

        Word overlap cannot tell a shared surname from a second mention of one person.
        Phase 2's relevance gate is where this gets a better answer.
        """
        assert people_in("Emily Carter and Ethan Carter both applied.") == 1


class TestPronounsAreNotTreatedAsNames:
    def test_she_and_he_are_not_people(self):
        prompt = "Emily Carter shipped it. She was thorough. He disagreed."
        assert people_in(prompt) == 1

    def test_pronouns_are_still_neutralised(self):
        out = rewrite("Emily Carter shipped it. She was thorough.")
        assert "She" not in out
        assert "They" in out


class TestEveryCharacterIsAccountedFor:
    def test_the_rewrite_is_rebuilt_from_its_segments(self):
        """S1 by reconstruction - the same check the pipeline runs before dispatch."""
        prompt = "Ask Mrs Chen and Dr. Okonkwo whether Mr Smith is ready."
        names = detect_names_offline(prompt)
        findings = sorted(names + find_pronouns(prompt, names), key=lambda f: f.span.start)
        result = apply(prompt, findings, set(range(len(findings))))
        assert "".join(s.text for s in result.segments) == preview(prompt).processed_prompt
