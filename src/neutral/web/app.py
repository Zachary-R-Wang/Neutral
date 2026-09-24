"""The web app. One page, a conversation, no database.

There is no database on purpose. S5 says identity mappings live in memory for one request
and nothing identifying is written to disk unless AUDIT_RETAIN is set. Conversations are
held in a dictionary that dies with the process; the simplest way to satisfy S5 is to have
nowhere to write to.

The name-to-placeholder map is not even kept for the conversation. Every turn re-derives
it over the whole thread and discards it before the response is sent - see
neutral/conversation.py.
"""

from __future__ import annotations

import secrets

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from neutral import errors
from neutral.adapters.anthropic_api import AnthropicAdapter
from neutral.config import ConfigError, load_settings
from neutral.conversation import Conversation, ask
from neutral.web.page import page

app = FastAPI(title="Neutral", docs_url=None, redoc_url=None)

COOKIE = "neutral_session"

# In memory, for this process only. Never written anywhere.
_conversations: dict[str, Conversation] = {}


def _conversation(request: Request) -> tuple[str, Conversation]:
    key = request.cookies.get(COOKIE) or secrets.token_urlsafe(16)
    conversation = _conversations.setdefault(key, Conversation())
    return key, conversation


def _adapter():
    settings = load_settings()
    if not settings.api_key_present:
        raise ConfigError(errors.NO_KEY)
    return AnthropicAdapter(
        api_key=settings.api_key,
        model=settings.subject_model,
        max_tokens=4000,
        effort="medium",
    )


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    key, conversation = _conversation(request)
    response = HTMLResponse(page(conversation))
    response.set_cookie(COOKIE, key, httponly=True, samesite="lax")
    return response


@app.post("/", response_class=HTMLResponse)
def send(request: Request, prompt: str = Form(default="")) -> HTMLResponse:
    """Add one turn. Defined with `def`, so FastAPI runs it off the event loop."""
    key, conversation = _conversation(request)
    text = (prompt or "").strip()

    if text:
        try:
            adapter = _adapter()
        except ConfigError as exc:
            kind = str(exc) if str(exc) in (errors.NO_KEY,) else errors.UNREACHABLE
            response = HTMLResponse(page(conversation, error=errors.user_message(kind)))
            response.set_cookie(COOKIE, key, httponly=True, samesite="lax")
            return response

        try:
            ask(conversation, text, adapter)
        except Exception:  # noqa: BLE001 - the page must never show a stack trace
            response = HTMLResponse(
                page(conversation, error=errors.user_message(errors.UNREACHABLE))
            )
            response.set_cookie(COOKIE, key, httponly=True, samesite="lax")
            return response

    # Redirect after posting, so refreshing the page does not send the prompt again.
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(COOKIE, key, httponly=True, samesite="lax")
    return response


@app.post("/new")
def new(request: Request) -> RedirectResponse:
    """Start again. The old conversation is dropped, not archived."""
    key = request.cookies.get(COOKIE)
    if key:
        _conversations.pop(key, None)
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(COOKIE)
    return response


@app.get("/health")
def health() -> dict:
    return {"ok": True}
