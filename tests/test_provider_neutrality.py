"""Nothing a Neutral customer sees may name a model provider.

CLAUDE.md section 4: "The model adapter is an interface. Neutral must work against more
than one provider. Never let provider-specific details leak past the adapter boundary."

This is not only tidiness. A Neutral customer connects their own model. If the interface
repeats a provider's own error text, it tells that customer to go and check an account
they do not have, at a company they are not using. The first version of the interface did
exactly that: it told everyone to top up at one specific vendor's billing page.
"""

from __future__ import annotations

import re

import pytest

from neutral import errors
from neutral.adapters.base import Completion
from neutral.detect import DetectedSpan, Detection
from neutral.pipeline import preview, process
from neutral.web.page import page

# Any vendor name. The point is that none of them belong in the interface, including the
# one this repository happens to build against first.
VENDORS = (
    "anthropic",
    "claude",
    "openai",
    "gpt",
    "chatgpt",
    "gemini",
    "google",
    "grok",
    "xai",
    "mistral",
    "llama",
    "meta",
    "cohere",
    "bedrock",
    "vertex",
)

PROMPT = "Write a performance review for Emily Carter. She shipped the payments work."


_TAGS = re.compile(r"<[^>]*>")
_STYLE = re.compile(r"<style.*?</style>", re.S)


def visible_text(html: str) -> str:
    """What a person actually reads.

    Checking raw markup gives false positives - <meta charset> is not a reference to the
    company that makes Llama. Tags and CSS are stripped; the placeholder attribute is
    folded back in because a user does read that.
    """
    placeholders = " ".join(re.findall(r'placeholder="([^"]*)"', html))
    stripped = _TAGS.sub(" ", _STYLE.sub(" ", html))
    return f"{stripped} {placeholders}"


def assert_no_vendor(html: str, where: str) -> None:
    text = visible_text(html).lower()
    found = [v for v in VENDORS if re.search(rf"\b{re.escape(v)}\b", text)]
    assert not found, (
        f"{where} names a model provider: {', '.join(found)}. A Neutral customer connects "
        f"their own model; the interface must never mention someone else's."
    )


class _Failing:
    """A provider whose own error text is full of its own branding, as they all are."""

    model = "some-vendor-model-1"

    def __init__(self, kind: str) -> None:
        self.kind = kind

    def complete(self, prompt, *, system=None):
        return Completion(
            text="",
            model=self.model,
            error_kind=self.kind,
            error=(
                "Error code: 400 - Your Anthropic account credit balance is too low. "
                "Go to console.anthropic.com/settings/billing to purchase credits."
            ),
        )

    def parse(self, prompt, output_format, *, system=None):
        return Detection(spans=[]), Completion(text="", model=self.model)


class _Working:
    model = "some-vendor-model-1"

    def complete(self, prompt, *, system=None):
        return Completion(
            text="Person A should tighten their estimates.",
            model=self.model,
            stop_reason="end_turn",
        )

    def parse(self, prompt, output_format, *, system=None):
        spans = [DetectedSpan(text="Emily Carter", kind="person_name")]
        return Detection(spans=spans), Completion(text="", model=self.model)


class TestTheInterfaceNamesNobody:
    def test_the_empty_page(self):
        assert_no_vendor(page(), "the empty page")

    def test_a_successful_result(self):
        result = process(PROMPT, adapter=_Working())
        assert_no_vendor(page(prompt=PROMPT, result=result), "a successful result page")

    def test_the_preview_shown_when_no_model_is_connected(self):
        result = preview(PROMPT)
        rendered = page(
            prompt=PROMPT,
            result=result,
            preview_note=errors.user_message(errors.NO_KEY),
        )
        assert_no_vendor(rendered, "the no-model-connected page")

    @pytest.mark.parametrize(
        "kind",
        [
            errors.NO_CREDIT,
            errors.RATE_LIMITED,
            errors.AUTH,
            errors.UNREACHABLE,
            errors.SERVER_ERROR,
            errors.BAD_REQUEST,
            errors.NO_KEY,
        ],
    )
    def test_every_error_kind_renders_without_a_vendor_name(self, kind):
        assert_no_vendor(errors.user_message(kind), f"the {kind} message")
        assert_no_vendor(page(prompt=PROMPT, error=errors.user_message(kind)), kind)

    def test_a_provider_error_never_reaches_the_page_verbatim(self):
        """The failure this file exists to prevent."""
        result = process(PROMPT, adapter=_Failing(errors.NO_CREDIT))
        assert result.error_kind == errors.NO_CREDIT

        # The provider's own wording is kept for diagnostics...
        assert "anthropic" in (result.passthrough_reason or "").lower()

        # ...but what the user is shown is rendered from the kind, not from that text.
        rendered = page(
            prompt=PROMPT,
            result=preview(PROMPT),
            preview_note=errors.user_message(result.error_kind),
        )
        assert_no_vendor(rendered, "the page after a provider error")
        assert "no remaining credit" in rendered


class TestTheNeutralTaxonomyIsComplete:
    def test_every_kind_has_a_message(self):
        for name in dir(errors):
            if name.isupper() and isinstance(getattr(errors, name), str):
                kind = getattr(errors, name)
                assert errors.user_message(kind) != errors.user_message("nonsense"), (
                    f"{name} has no message of its own in neutral.errors"
                )
