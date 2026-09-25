"""What the conversation page shows, and what it deliberately does not.

Two rules shape this page and both are easy to break by accident:

  * The rewritten prompt is machinery. Putting it in the thread makes the conversation
    unreadable, so it is never shown there.
  * The unmodified answer is not machinery. S2 says the interface must always expose it,
    so every answer carries a control that opens it in place.
"""

from __future__ import annotations

import re
from html import escape

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
        """Asserts the property, not the pixel values, so restyling does not break it."""
        html, _ = rendered()

        def font_size(selector: str) -> float:
            block = re.search(rf"{re.escape(selector)}\s*\{{([^}}]*)\}}", html)
            assert block, f"no rule found for {selector}"
            size = re.search(r"font-size:\s*([\d.]+)px", block.group(1))
            assert size, f"{selector} sets no font size"
            return float(size.group(1))

        assert font_size(".prose.small") < font_size(".reply .prose"), (
            "the original should be more compact than the answer above it"
        )

        surface = re.search(r"\.raw\s*\{([^}]*)\}", html)
        assert surface and "background:" in surface.group(1), (
            "the original needs a surface of its own, so it reads as a different kind of "
            "thing rather than as more of the answer"
        )


class TestWhatChangedIsRecorded:
    def test_the_substitutions_are_listed(self):
        html, _ = rendered()
        assert "Emily Carter" in html and "Person A" in html
        assert "Removed before sending" in html

    def test_a_turn_with_no_changes_lists_none(self):
        html, _ = rendered("What is a good structure for a performance review?")
        assert "Removed before sending" not in html


class TestTheOpeningState:
    def test_it_greets_and_shows_one_box(self):
        html = page()
        assert 'id="greeting"' in html
        assert html.count("<textarea") == 1

    def test_the_greeting_is_a_real_one_without_javascript(self):
        """Someone with scripting off keeps whatever the server rendered."""
        from neutral.web.page import ANYTIME_GREETINGS

        greeting = re.search(r'id="greeting">([^<]+)<', page())
        assert greeting, "no greeting was rendered"
        assert greeting.group(1) in [escape(g) for g in ANYTIME_GREETINGS]

    def test_the_server_never_renders_a_time_specific_greeting(self):
        """It cannot know the visitor's local hour, so it must not guess at one."""
        renders = [page() for _ in range(40)]
        for word in ("morning", "afternoon", "evening", "night", "Still up", "late"):
            for html in renders:
                shown = re.search(r'id="greeting">([^<]+)<', html).group(1)
                assert word.lower() not in shown.lower(), (
                    f"the server rendered {shown!r}, which assumes a time of day"
                )

    def test_the_greeting_varies(self):
        seen = {re.search(r'id="greeting">([^<]+)<', page()).group(1) for _ in range(60)}
        assert len(seen) > 1, "the same greeting every time is not a rotation"

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


class TestTheLegalPages:
    """Not lawyer-written, and the pages say so. These check they cannot ship half-done."""

    def test_both_pages_render(self):
        from neutral.web.legal import PRIVACY, TERMS
        from neutral.web.page import legal_page

        for title, body in (("Terms of use", TERMS), ("Privacy", PRIVACY)):
            html = legal_page(title, body)
            assert title in html
            assert "evaluation use only" in html

    def test_unfilled_placeholders_are_flagged_loudly(self):
        """A terms page that quietly ships saying FILL_IN is worse than none at all."""
        from neutral.web.legal import TERMS
        from neutral.web.page import legal_page

        html = legal_page("Terms of use", TERMS)
        assert "This page is not finished" in html
        assert 'class="fillin"' in html

    def test_a_filled_page_shows_no_warning(self):
        from neutral.web.page import legal_page

        html = legal_page("Terms of use", "## Done\n\nOperated by Acme Ltd.")
        assert "This page is not finished" not in html
        assert 'class="fillin"' not in html

    def test_the_highlight_stops_at_the_placeholder(self):
        """It used to run to the next full stop and swallow the sentence after it."""
        import re

        from neutral.web.page import legal_page

        html = legal_page("T", "Operated by [[your name]] and nothing else follows.")
        span = re.search(r'<span class="fillin">(.*?)</span>', html)
        assert span and "nothing else follows" not in span.group(1)

    def test_the_third_party_disclosure_is_present(self):
        """The most important thing on either page: prompts leave this machine."""
        from neutral.web.legal import PRIVACY

        lowered = PRIVACY.lower()
        assert "third-party model provider" in lowered
        assert "not stored here" in lowered or "nothing is stored here" in lowered

    def test_the_main_page_links_to_both(self):
        html = page()
        assert 'href="/terms"' in html
        assert 'href="/privacy"' in html


class TestNothingChangedMeansOneAnswer:
    """Reported from the page: two visibly different answers with no changes listed.

    Both calls had sent the identical prompt, so the difference was nothing but the
    model's own randomness - presented side by side as though Neutral had done something.
    """

    class _Counting:
        model = "demo"

        def __init__(self) -> None:
            self.calls = 0

        def complete(self, prompt, *, system=None, history=None):
            self.calls += 1
            return Completion(
                text=f"answer number {self.calls}", model="demo", stop_reason="end_turn"
            )

    def test_a_prompt_with_no_names_makes_one_call(self):
        adapter = self._Counting()
        conversation = Conversation()
        ask(conversation, "What makes a good performance review structure?", adapter)
        assert adapter.calls == 1, (
            "the same prompt was sent twice, so the two answers differ only by chance"
        )

    def test_it_says_why_there_is_only_one_answer(self):
        conversation = Conversation()
        turn = ask(conversation, "How should I structure a review?", self._Counting())
        assert turn.untouched
        assert "nothing in this needed changing" in turn.note.lower()

    def test_no_original_toggle_is_offered_when_they_would_be_identical(self):
        conversation = Conversation()
        ask(conversation, "How should I structure a review?", self._Counting())
        assert "Original response" not in page(conversation)

    def test_a_prompt_with_a_name_still_makes_two_calls(self):
        adapter = self._Counting()
        conversation = Conversation()
        turn = ask(conversation, "Assess Emily Carter for promotion.", adapter)
        assert adapter.calls == 2
        assert turn.changes
        assert "Original response" in page(conversation)
