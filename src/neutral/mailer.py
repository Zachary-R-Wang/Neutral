"""Sending the one email Neutral sends: a password reset link.

Neutral has no mailing list, no notifications and no receipts. This exists so that a
person who forgets their password can get back in, and for nothing else.

**It is honest about not being configured.** With no email service set up, `send` returns
False and the interface says plainly that reset is unavailable and who to contact. The
alternative - showing "check your inbox" when no inbox will ever receive anything - is
the kind of lie that makes somebody sit refreshing their mail for ten minutes.

Resend over plain HTTP, for the same reason the model providers are: it is thirty lines,
and an SDK for this would be a dependency tree to use one endpoint of.
"""

from __future__ import annotations

import os
import traceback

import httpx

TIMEOUT = httpx.Timeout(20.0, connect=10.0)
ENDPOINT = "https://api.resend.com/emails"


def _key() -> str:
    return os.environ.get("RESEND_API_KEY", "").strip()


def _from() -> str:
    """Who the email appears to come from. Must be on a domain you have verified."""
    return os.environ.get("NEUTRAL_MAIL_FROM", "").strip()


def configured() -> bool:
    """True when a reset email could actually be sent."""
    return bool(_key() and _from())


def send(to: str, subject: str, body: str) -> bool:
    """Send one plain-text email. Returns whether it went.

    Never raises. A failure here must not take down the page the person is looking at,
    and it must not be reported to them as a stack trace.
    """
    if not configured():
        return False
    try:
        reply = httpx.post(
            ENDPOINT,
            headers={
                "Authorization": f"Bearer {_key()}",
                "Content-Type": "application/json",
            },
            json={"from": _from(), "to": [to], "subject": subject, "text": body},
            timeout=TIMEOUT,
        )
    except httpx.HTTPError:
        traceback.print_exc()
        return False
    if reply.status_code >= 400:
        # To the terminal, never to the page. The body can name the mail provider.
        print(f"[mailer] refused with {reply.status_code}: {reply.text[:300]}")
        return False
    return True


def reset_email(link: str) -> tuple[str, str]:
    """The subject and body of the only email Neutral sends.

    Short, plain text, no images and no tracking. It says what to do if the reader did
    not ask for it, because a reset email always reaches some people who did not.
    """
    subject = "Reset your Neutral password"
    body = f"""Someone asked to reset the password for this address on Neutral.

To set a new password, open this link:

{link}

The link works once and expires in an hour.

If you did not ask for this, you can ignore this email. Your password has not
been changed, and nobody can change it without this link.

Neutral - evaluation use only. Do not use its output as the basis of an
employment decision.
"""
    return subject, body
