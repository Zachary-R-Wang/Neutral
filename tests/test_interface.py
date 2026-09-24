"""What the conversation page shows, and what it deliberately does not.

Two rules shape this page and both are easy to break by accident:

  * The rewritten prompt is machinery. Putting it in the thread makes the conversation
    unreadable, so it is never shown there.
  * The unmodified answer is not machinery. S2 says the interface must always expose it,
    so every answer carries a control that opens it in place.
"""

from __future__ import annotations

import re

from neutral.adapters.base import Completion
from neutral.conversation import Conversation, ask
from neutral.core import Span, TransformRecord
from neutral.web.page import page

PROMPT = "Assess Emily Carter. She shipped the payments work."


class _Model:
    model = "demo"

    def complete(self, prompt, *, system=None, history=None):
        neutral = "Person A" in prompt or any("Person A" in h[1] for h in (history or []))
        text = (
            "Person A should tighten their estimates."
            if neutral
            else "Emily is doing well overall."
        )
        return Completion(text=text, model=self.model, stop_reason="end_turn")


def rendered(prompt: str = PROMPT) -> tuple[str, Conversation]:
    conversation = Conversation()
    ask(conversation, prompt, _Model())
    return page(conversation), conversation


class TestTheThreadShowsTheAnswerTheUserCameFor:
    def test_the_restored_answer_is_in_the_thread(self):
        html, _ = rendered()
        assert "Emily Carter should tighten her estimates." in html

    def test_the_prompt_is_shown_as_the_user_wrote_it(self):
        html, _ = rendered()
        assert "Assess Emily Carter." in html

    def test_the_rewritten_prompt_is_never_shown(self):
        """It is machinery. The thread is a conversation, not a debug view."""
        html, _ = rendered()
        assert "Assess Person A." not in html


class TestTheOriginalIsAlwaysOneClickAway:
    def test_the_original_answer_is_present(self):
        """S2 - never hidden, even though it is not the answer being shown."""
        html, _ = rendered()
        assert "Emily is doing well overall." in html

    def test_it_sits_inside_a_collapsed_control(self):
        html, _ = rendered()
        block = re.search(r"<details class=\"original\">(.*?)</details>", html, re.S)
        assert block, "the original answer is not inside a collapsible control"
        assert "Emily is doing well overall." in block.group(1)

    def test_it_is_closed_by_default(self):
        html, _ = rendered()
        assert '<details class="original">' in html
        assert '<details class="original" open>' not in html

    def test_it_opens_in_place_rather_than_over_the_conversation(self):
        """No dialog, no overlay - it is a <details> inside the reply it belongs to."""
        html, _ = rendered()
        assert "<dialog" not in html
        assert "position:fixed" not in html
        reply = re.search(r"<div class=\"reply\">(.*?)</div>\s*</div>", html, re.S)
        assert reply and "details" in reply.group(1)

    def test_it_is_styled_as_a_different_kind_of_thing(self):
        html, _ = rendered()
        assert "--raw:" in html, "the original has no surface colour of its own"
        assert ".raw .text{white-space:pre-wrap;font-size:13.5px" in html, (
            "the original should be more compact than the answer above it"
        )
        assert re.search(r"\.reply \.text\{white-space:pre-wrap;font-size:15\.5px", html)


class TestWhatChangedIsRecorded:
    def test_the_substitutions_are_listed(self):
        html, _ = rendered()
        assert "Emily Carter" in html and "Person A" in html
        assert "Removed before sending" in html

    def test_a_turn_with_no_changes_lists_none(self):
        html, _ = rendered("What is a good structure for a performance review?")
        assert "Removed before sending" not in html


class TestTheOpeningState:
    def test_it_asks_one_question_and_shows_one_box(self):
        html = page()
        assert "What do you want to ask?" in html
        assert html.count("<textarea") == 1

    def test_there_is_no_thread_before_anything_is_asked(self):
        assert '<div class="thread">' not in page()

    def test_the_banner_is_present_in_both_states(self):
        html, _ = rendered()
        assert "evaluation use only" in page()
        assert "evaluation use only" in html


class TestFailuresStillShowTheRewriting:
    def test_an_unreachable_model_still_shows_what_would_have_been_removed(self):
        class Broken:
            model = "broken"

            def complete(self, prompt, *, system=None, history=None):
                return Completion(text="", model="broken", error="boom", error_kind="unreachable")

        conversation = Conversation()
        turn = ask(conversation, PROMPT, Broken())
        assert turn.failed
        assert turn.changes, "the rewriting is local and free; it should still be computed"
        html = page(conversation)
        assert "What Neutral would have removed" in html


class TestNothingUnescapedReachesThePage:
    def test_a_prompt_containing_markup_is_escaped(self):
        html, _ = rendered("Assess <script>alert(1)</script> and Emily Carter.")
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_a_model_answer_containing_markup_is_escaped(self):
        class Injecting:
            model = "x"

            def complete(self, prompt, *, system=None, history=None):
                return Completion(
                    text="<img src=x onerror=alert(1)>", model="x", stop_reason="end_turn"
                )

        conversation = Conversation()
        ask(conversation, PROMPT, Injecting())
        html = page(conversation)
        assert "<img src=x onerror" not in html


def test_a_transform_record_renders_without_breaking_the_page():
    conversation = Conversation()
    ask(conversation, PROMPT, _Model())
    conversation.turns[0].changes = (
        TransformRecord(
            mechanism="identity_substitution",
            detected="<b>Emily</b>",
            detected_kind="person_name",
            replacement="Person A",
            source=Span(0, 5),
            policy="hr-default",
            policy_version="v1",
            reason="test",
        ),
    )
    html = page(conversation)
    assert "<b>Emily</b>" not in html
    assert "&lt;b&gt;Emily&lt;/b&gt;" in html
