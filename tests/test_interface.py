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
from neutral.web.legal import CONTACT, JURISDICTION, OPERATOR, PRIVACY, TERMS
from neutral.web.page import markdown, page

PROMPT = "Assess Emily Carter. She shipped the payments work."


class _Model:
    model = "demo"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt, *, system=None, history=None):
        self.calls += 1
        return Completion(
            text="Person A should tighten their estimates.",
            model=self.model,
            stop_reason="end_turn",
        )


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

    def test_the_rewritten_prompt_is_not_in_the_thread(self):
        """It is machinery. The thread is a conversation, not a debug view - so it is
        only inside the collapsed control, never in the conversation itself."""
        html, _ = rendered()
        thread = re.sub(r"<details.*?</details>", "", html, flags=re.S)
        assert "Assess Person A." not in thread

    def test_the_exact_prompt_sent_is_one_click_away(self):
        """Phase 5: a person can see what Neutral did to their prompt. Without it the
        founder could not tell that Mechanisms 2 and 3 were running."""
        html, _ = rendered()
        control = re.search(r'<details class="original">.*?</details>', html, re.S)
        assert control and "What the model was sent" in control.group(0)
        assert "Assess Person A." in control.group(0)


class TestTheOriginalIsAlwaysOneClickAway:
    def test_one_model_call_per_turn(self):
        """A conversation asks once. Asking twice to fill an expander is not free."""
        adapter = _Model()
        conversation = Conversation()
        ask(conversation, PROMPT, adapter)
        assert adapter.calls == 1

    def test_the_unrestored_reply_is_present(self):
        """The same reply, before names went back - what Neutral actually did."""
        html, _ = rendered()
        assert "Person A should tighten their estimates." in html

    def test_it_sits_inside_a_collapsed_control(self):
        html, _ = rendered()
        block = re.search(r"<details class=\"original\">(.*?)</details>", html, re.S)
        assert block, "the unrestored reply is not inside a collapsible control"
        assert "Person A" in block.group(1)

    def test_it_is_closed_by_default(self):
        html, _ = rendered()
        assert '<details class="original">' in html
        assert '<details class="original" open>' not in html

    def test_it_opens_in_place_rather_than_over_the_conversation(self):
        """No dialog, no overlay - it is a <details> inside the reply it belongs to."""
        html, _ = rendered()
        assert "<dialog" not in html

        # Scoped to the rules that matter: decoration elsewhere may legitimately be
        # fixed, but nothing that carries the original answer may lift off the page.
        for selector in ("details.original", r"details\.original>summary", r"\.raw"):
            rule = re.search(rf"{selector}\s*\{{([^}}]*)\}}", html)
            if rule:
                assert "fixed" not in rule.group(1)
                assert "absolute" not in rule.group(1)
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
        assert "Changed before sending" in html

    def test_a_turn_with_no_changes_lists_none(self):
        html, _ = rendered("What is a good structure for a performance review?")
        assert "Changed before sending" not in html

    def test_each_mechanism_that_fired_is_named(self):
        html, _ = rendered("Should I promote Priya Raman or Greg Miller? I manage both.")
        for heading in ("Names", "Who is asking"):
            assert f"<span>{heading}</span>" in html


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
        assert "What Neutral would have changed" in html


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


class TestMarkdownHandlesWrappedText:
    """A list item written across two lines is one item, not an item and a stray line.

    Found by reading the rendered privacy page. Model answers arrive as long single
    lines so they never hit this, but anything hand-written in the repository does.
    """

    def test_a_wrapped_bullet_is_one_bullet(self):
        html = markdown("- a bullet that carries on\n  onto a second line")
        assert html == "<ul><li>a bullet that carries on onto a second line</li></ul>"

    def test_a_wrapped_numbered_item_is_one_item(self):
        html = markdown("1. a numbered item\n   continued here")
        assert html == "<ol><li>a numbered item continued here</li></ol>"

    def test_emphasis_spanning_the_wrap_still_renders(self):
        html = markdown("- this is **bold\n  across a wrap** here")
        assert "<strong>bold across a wrap</strong>" in html

    def test_a_blank_line_still_ends_the_list(self):
        html = markdown("- one\n\nA new paragraph.")
        assert html == "<ul><li>one</li></ul><p>A new paragraph.</p>"

    def test_a_heading_still_ends_the_list(self):
        html = markdown("- one\n## Next")
        assert html == "<ul><li>one</li></ul><h4>Next</h4>"

    def test_the_privacy_pages_lists_come_out_whole(self):
        """The bug as it appeared: every wrapped bullet split into its own one-item list.

        Checked by shape rather than by looking for a suspicious pattern - prose between
        two lists is ordinary on this page, so only the item counts say whether a bullet
        survived its own line wrap.
        """
        rendered = markdown(PRIVACY)
        counts = [items.count("<li>") for items in re.findall(r"<ul>(.*?)</ul>", rendered)]
        assert counts == [3, 3, 4], (
            f"the privacy page's lists came out as {counts}, expected [3, 3, 4]: "
            f"three cases where a prompt goes out unchanged, three things in an account, "
            f"four things that are not kept"
        )

    def test_two_separate_bullets_stay_separate(self):
        html = markdown("- one\n- two")
        assert html == "<ul><li>one</li><li>two</li></ul>"


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
        """A terms page that quietly ships saying FILL_IN is worse than none at all.

        Written against a made-up page rather than the real one. It used to use the real
        TERMS, which only worked while that page was unfinished - filling it in broke a
        test that was supposed to be about the highlighting.
        """
        from neutral.web.page import legal_page

        html = legal_page("Terms of use", "## Who\n\nOperated by [[your name]] under [[some law]].")
        assert "This page is not finished" in html
        assert html.count('class="fillin"') == 2

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
        """The most important thing on either page: prompts leave this machine.

        This test used to require the page to say "nothing is stored here", which was
        true when it was written and false the moment accounts arrived - so the test was
        holding a false claim in place rather than catching it. It now checks the two
        things that are actually load-bearing: that prompts go to someone else, and that
        they are not kept here.
        """
        lowered = PRIVACY.lower()
        assert "third-party model provider" in lowered
        assert "prompts and answers" in lowered
        assert "not saved to any file or database" in lowered

    def _pages_with(self, monkeypatch, env: dict[str, str]):
        import importlib

        from neutral.web import legal

        for key in ("NEUTRAL_OPERATOR", "NEUTRAL_CONTACT", "NEUTRAL_JURISDICTION"):
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        reloaded = importlib.reload(legal)
        pages = reloaded.TERMS, reloaded.PRIVACY
        monkeypatch.undo()
        importlib.reload(legal)
        return pages

    def test_the_live_site_sets_who_operates_it(self):
        """The operator's details moved out of the code on 2026-09-28, so that anyone can
        run their own copy without it naming someone else. neutralai.app sets them in
        fly.toml; if they go missing there, the live pages would show placeholders."""
        import tomllib
        from pathlib import Path

        fly = tomllib.loads((Path(__file__).resolve().parent.parent / "fly.toml").read_text())
        env = fly["env"]
        for key in ("NEUTRAL_OPERATOR", "NEUTRAL_CONTACT", "NEUTRAL_JURISDICTION"):
            assert env.get(key, "").strip(), f"fly.toml does not set {key}"

    def test_configured_pages_have_no_placeholders_left(self, monkeypatch):
        """With the operator's details set, as they are on a real deployment, nothing
        unfilled goes out."""
        terms, privacy = self._pages_with(
            monkeypatch,
            {
                "NEUTRAL_OPERATOR": "A. Operator",
                "NEUTRAL_CONTACT": "operator@example.com",
                "NEUTRAL_JURISDICTION": "England and Wales",
            },
        )
        for name, body in (("terms", terms), ("privacy", privacy)):
            assert "[[" not in body, f"the {name} page still has a placeholder in it"
        assert "A. Operator" in terms and "operator@example.com" in privacy

    def test_an_unconfigured_copy_shows_it_plainly(self, monkeypatch):
        """Someone running their own copy without setting their details sees the gap
        highlighted, rather than a stranger's name as the operator."""
        terms, _ = self._pages_with(monkeypatch, {})
        assert "[[the operator's name]]" in terms

    def test_the_pages_name_who_operates_it_and_how_to_reach_them(self):
        assert OPERATOR in TERMS
        assert CONTACT in TERMS and CONTACT in PRIVACY
        assert JURISDICTION in TERMS

    def test_the_privacy_page_does_not_claim_nothing_is_stored(self):
        """It said exactly that until accounts were added, which made it false.

        A privacy policy that misdescribes the product is worse than not having one, and
        this is the failure mode: the page was written when Neutral had no database, and
        nothing made it wrong again when one arrived.
        """
        for false_claim in (
            "Nothing is stored here",
            "No account, no login",
            "Nothing is written to disk",
            "no record to access",
        ):
            assert false_claim not in PRIVACY, f"the privacy page still says: {false_claim}"

    def test_the_privacy_page_describes_the_account_that_is_stored(self):
        for fact in ("email address", "password", "written to disk"):
            assert fact in PRIVACY, f"the privacy page does not mention {fact}"

    def test_the_privacy_page_says_the_api_key_is_never_written_down(self):
        assert "API key is never written down" in PRIVACY

    def test_it_says_the_prompt_is_sent_once_not_twice(self):
        """The conversation makes one model call. The page used to promise two."""
        assert "sent twice" not in PRIVACY
        assert "It is sent once" in PRIVACY

    def test_it_admits_the_cases_where_the_real_names_do_go_out(self):
        """Rewritten is the usual path, not the only one. Saying otherwise overclaims."""
        assert "exactly as you wrote it" in PRIVACY

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
        turn = ask(conversation, "What makes a good structure for a review?", self._Counting())
        assert turn.untouched
        assert "nothing in this needed changing" in turn.note.lower()

    def test_no_toggle_is_offered_when_there_is_nothing_to_show(self):
        conversation = Conversation()
        ask(conversation, "What makes a good structure for a review?", self._Counting())
        assert "What Neutral changed" not in page(conversation)

    def test_a_prompt_with_a_name_also_makes_one_call(self):
        """Every turn costs one call. The expander shows the same reply, unrestored."""
        adapter = self._Counting()
        conversation = Conversation()
        turn = ask(conversation, "Assess Emily Carter for promotion.", adapter)
        assert adapter.calls == 1
        assert turn.changes
        assert "What Neutral changed" in page(conversation)


class TestTheFooterSaysWhatIsActuallyRunning:
    """It said "Phase 1 - names and bound pronouns only" for a day after Mechanisms 2 and 3
    went live, and the founder reasonably concluded they had not been built."""

    def test_every_running_mechanism_is_described(self):
        from neutral.rewrite import DEFAULT_MECHANISMS
        from neutral.web.page import MECHANISM_WORDS, footer_note

        for mechanism in DEFAULT_MECHANISMS:
            assert mechanism in MECHANISM_WORDS, f"{mechanism} runs but has no description"
            for phrase in MECHANISM_WORDS[mechanism]:
                assert phrase in footer_note()

    def test_it_reads_as_one_list(self):
        """It once said "who wrote it and who is named first and who is the subject"."""
        from neutral.web.page import footer_note

        note = footer_note()
        tail = note.split(", ")[-1]
        assert tail.count(" and ") == 1, note

    def test_the_stale_label_is_gone_from_every_page(self):
        from neutral.web.access import connect_page, signin_page, signup_page

        for html in (page(), signin_page(), signup_page(), connect_page(email="a@b.com")):
            assert "Phase 1" not in html


class TestTheMark:
    """The logo beside the name, and in the browser tab."""

    def test_every_page_has_the_mark_beside_the_name(self):
        from neutral.web.access import connect_page, signin_page, signup_page, trouble_page
        from neutral.web.page import legal_page

        pages = (
            page(),
            signin_page(),
            signup_page(),
            connect_page(email="a@b.com"),
            trouble_page("x"),
            legal_page("Terms", "text"),
        )
        for html in pages:
            header = html[html.index('<div class="top">') :][:2000]
            name = header.index("Neutral")
            assert 'class="mark"' in header[name : name + 400], "mark is not beside the name"

    def test_every_page_asks_for_the_tab_icon_and_keeps_its_title(self):
        from neutral.web.access import signin_page
        from neutral.web.page import legal_page

        for html, title in (
            (page(), "Neutral"),
            (signin_page(), "Sign In &mdash; Neutral"),
            (legal_page("Privacy", "x"), "Privacy &mdash; Neutral"),
        ):
            assert 'rel="icon" href="/favicon.svg"' in html
            assert 'rel="icon" href="/favicon.ico"' in html
            assert f"<title>{title}</title>" in html

    def test_the_icon_files_are_served_as_the_right_kind_of_file(self):
        from fastapi.testclient import TestClient

        from neutral.web.app import app

        client = TestClient(app)
        for path, kind in (
            ("/favicon.ico", "image/x-icon"),
            ("/favicon.svg", "image/svg+xml"),
            ("/apple-touch-icon.png", "image/png"),
        ):
            got = client.get(path)
            assert got.status_code == 200, path
            assert got.headers["content-type"].startswith(kind), path
            assert len(got.content) > 100, path

    def test_the_icon_on_disk_was_drawn_from_the_current_geometry(self):
        """If brand.py changes and tools/make_icons.py is not re-run, the tab icon would
        quietly show the old mark. This catches it for the SVG, which is text."""
        from pathlib import Path

        from neutral.web.brand import favicon_svg

        on_disk = (
            Path(__file__).resolve().parent.parent / "src/neutral/web/static/favicon.svg"
        ).read_text()
        assert on_disk == favicon_svg(), "run: uv run --with pillow python tools/make_icons.py"

    def test_the_mark_is_the_founders_colour(self):
        from neutral.web.brand import INK, mark_svg

        assert INK == "#586a60"
        assert INK in mark_svg()


class TestConversationsSurviveWhatTheMechanismsRemove:
    """Found in the final review: a message that was all self-presentation was sent to the
    model as an empty string, and the removal took the separator between turns with it,
    so the next turn fell back to being sent unchanged."""

    class _Recording:
        model = "recording"

        def __init__(self, fail_first=False):
            self.sent, self.histories, self.fail_first = [], [], fail_first

        def complete(self, prompt, *, system=None, history=None):
            self.sent.append(prompt)
            self.histories.append(list(history or []))
            if self.fail_first and len(self.sent) == 1:
                return Completion(text="", model=self.model, error="boom", error_kind="unreachable")
            return Completion(text="Noted.", model=self.model, stop_reason="end_turn")

    def test_nothing_is_sent_when_nothing_is_left(self):
        adapter = self._Recording()
        conversation = Conversation()
        ask(conversation, "Rate my essay out of 10", adapter)
        turn = ask(
            conversation,
            "I spent three weeks on it and I think it's the best thing I've written",
            adapter,
        )
        assert len(adapter.sent) == 1, "an empty message went to the model"
        assert "nothing left to send" in turn.note

    def test_the_next_turn_is_still_neutralised(self):
        adapter = self._Recording()
        conversation = Conversation()
        ask(conversation, "Rate my essay out of 10", adapter)
        ask(conversation, "I spent three weeks on it and I think it's the best thing", adapter)
        turn = ask(conversation, "Is it good enough for a magazine?", adapter)
        assert not turn.untouched
        assert adapter.sent[-1] == "Evaluate its suitability for a magazine."

    def test_a_failed_turn_does_not_poison_the_history(self):
        """Its reply is empty, and an empty message in the history makes providers refuse
        every later turn."""
        adapter = self._Recording(fail_first=True)
        conversation = Conversation()
        ask(conversation, "Assess Emily Carter.", adapter)
        ask(conversation, "Assess Ravi Menon.", adapter)
        assert all(content for _, content in adapter.histories[-1])


class TestThePanelSaysWhatKindOfChangeEachWas:
    class _Model:
        model = "demo"

        def complete(self, prompt, *, system=None, history=None):
            return Completion(text="Noted.", model=self.model, stop_reason="end_turn")

    def test_the_question_and_the_stake_have_their_own_lines(self):
        conversation = Conversation()
        ask(
            conversation,
            "I think my code is really clean and efficient. Can you confirm? "
            "I've been coding for twenty years. def f(x): return x",
            self._Model(),
        )
        html = page(conversation)
        assert "<span>The question</span>" in html
        assert "<span>Your stake</span>" in html

    def test_what_was_deliberately_kept_is_shown_with_why(self):
        conversation = Conversation()
        ask(
            conversation,
            "My colleague Priya Raman asked what the legal rules are for firing a "
            "67-year-old employee.",
            self._Model(),
        )
        html = page(conversation)
        assert "<span>Kept</span>" in html and "67-year-old" in html
