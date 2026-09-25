"""Provider-neutral error kinds.

CLAUDE.md section 4: "The model adapter is an interface. Neutral must work against more
than one provider. Never let provider-specific details leak past the adapter boundary."

A provider's own error text is provider-specific by nature - it names the company, its
console, its billing page. Letting that text through to the interface tells a Neutral
customer, who has connected their own model, to go and check someone else's account.

So an adapter returns two things: the raw message, which is useful in a log, and a KIND
from this list, which is not tied to anyone. Everything the user sees is rendered from
the kind. Adding a provider means mapping its errors onto these; it never means touching
the interface.
"""

from __future__ import annotations

NO_CREDIT = "no_credit"
RATE_LIMITED = "rate_limited"
AUTH = "auth"
UNREACHABLE = "unreachable"
SERVER_ERROR = "server_error"
BAD_REQUEST = "bad_request"
NO_KEY = "no_key"
MODEL_NOT_FOUND = "model_not_found"

_MESSAGES = {
    NO_CREDIT: (
        "Your model provider reports no remaining credit on the account, so the prompt "
        "was not sent. Top up with your provider and try again."
    ),
    RATE_LIMITED: (
        "Your model provider is rate limiting this account. Wait a moment and try again."
    ),
    AUTH: (
        "Your model provider rejected the credentials. Check the API key configured for "
        "the connected model."
    ),
    UNREACHABLE: (
        "The connected model could not be reached. Check the network connection and try again."
    ),
    SERVER_ERROR: (
        "Your model provider had a problem at their end. This is usually temporary - try "
        "again shortly."
    ),
    BAD_REQUEST: "The connected model rejected the request.",
    MODEL_NOT_FOUND: (
        "Your model provider does not recognise that model name, or this account cannot "
        "use it. Check the spelling in the model field, or choose one from the list."
    ),
    NO_KEY: (
        "No model is connected yet. Add an API key for the model you want Neutral to send "
        "prompts to, then restart."
    ),
}


def user_message(kind: str) -> str:
    """What to show a person. Never names a provider."""
    return _MESSAGES.get(kind, "The connected model could not answer this request.")


# How providers say "no such model". Status alone is not enough for this either: some use
# 404, some use 400 with the reason in words.
_MODEL_MISSING = (
    # "not exist" rather than "does not exist": DeepSeek says "Model Not Exist".
    "not exist",
    "not found",
    "model_not_found",
    "unknown model",
    "invalid model",
    "no such model",
    "is not available to your account",
    "do not have access to the model",
    "not supported for generatecontent",
)


def is_model_missing(status: int, body: str) -> bool:
    """True when a failure means the model name, not the request, was the problem."""
    lowered = (body or "").lower()
    if any(phrase in lowered for phrase in _MODEL_MISSING):
        return "model" in lowered or status == 404
    return False
