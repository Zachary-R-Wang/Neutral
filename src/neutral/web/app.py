"""The web app. An account, a model you bring yourself, and a conversation.

Two stores, and the line between them is the point:

  accounts.db        email, password hash, preferred model.  Survives a restart.
  web/sessions.py    the conversation, and the API key.      Dies with the process.

S5 says nothing identifying is written to disk. Prompt text and the identity map stay on
the memory side, so there is nowhere to write them even by accident. The API key is on
that side too - see the reasoning in neutral/accounts.py.

Every page a person can reach without being signed in is a form. Nothing reaches a model
until there is both an account and a key.
"""

from __future__ import annotations

import threading
import traceback

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from neutral import accounts, errors
from neutral.accounts import AccountError
from neutral.adapters.providers import PROVIDERS, build, label_for
from neutral.conversation import Conversation, ask
from neutral.web.access import connect_page, signin_page, signup_page, trouble_page
from neutral.web.legal import PRIVACY, TERMS
from neutral.web.page import legal_page, page
from neutral.web.sessions import COOKIE, Session, Sessions

app = FastAPI(title="Neutral", docs_url=None, redoc_url=None)

sessions = Sessions()

UNEXPECTED = (
    "Neutral hit a problem it did not expect and stopped rather than guessing. Nothing "
    "was sent to a model. The details were printed in the terminal window running "
    "Neutral - if this keeps happening, that text is what to report."
)


@app.middleware("http")
async def never_show_a_stack_trace(request: Request, call_next):
    """The last net. No route may answer with a bare Internal Server Error.

    The conversation route already fails open to a readable message (S4). This catches
    everything else - a database that vanished, a bug nobody predicted - so a person
    always gets a sentence in English and the cause still lands in the terminal.
    """
    try:
        return await call_next(request)
    except Exception:  # noqa: BLE001 - that is the entire job
        traceback.print_exc()
        return HTMLResponse(trouble_page(UNEXPECTED), status_code=500)


# One connection, shared. SQLite serialises writes itself but the Python driver is happier
# with a lock in front of it, and FastAPI runs these handlers on a threadpool.
_db_lock = threading.Lock()
_db = None


def db():
    """The account database, reopened if the file was deleted while we held it open.

    Deleting accounts.db to start over is a reasonable thing to do, and doing it while
    Neutral is running used to leave every later write failing with "readonly database"
    until the server was restarted. Now the connection is simply reopened.
    """
    global _db
    with _db_lock:
        if _db is not None and not accounts.still_on_disk(_db):
            try:
                _db.close()
            except Exception:  # noqa: BLE001 - closing a dead connection is not news
                pass
            _db = None
        if _db is None:
            _db = accounts.connect()
        return _db


def _cookie(response, key: str):
    response.set_cookie(COOKIE, key, httponly=True, samesite="lax", max_age=8 * 60 * 60)
    return response


def _session(request: Request) -> tuple[str, Session]:
    return sessions.get(request.cookies.get(COOKIE))


def _html(body: str, key: str) -> HTMLResponse:
    return _cookie(HTMLResponse(body), key)


def _go(where: str, key: str | None = None) -> RedirectResponse:
    response = RedirectResponse(where, status_code=303)
    return _cookie(response, key) if key else response


def _conversation_page(session: Session, *, error: str = "") -> str:
    return page(
        session.conversation,
        error=error,
        email=session.email,
        provider_label=label_for(session.provider),
        model=session.model,
    )


# ---------------------------------------------------------------------------
# the conversation
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    key, session = _session(request)
    if not session.signed_in:
        return _go("/signin", key)
    if not session.connected:
        return _go("/connect", key)
    return _html(_conversation_page(session), key)


@app.post("/", response_class=HTMLResponse)
def send(request: Request, prompt: str = Form(default="")):
    """Add one turn. Defined with `def`, so FastAPI runs it off the event loop."""
    key, session = _session(request)
    if not session.signed_in:
        return _go("/signin", key)
    if not session.connected:
        return _go("/connect", key)

    text = (prompt or "").strip()
    if text:
        adapter = build(session.provider, session.api_key, session.model)
        try:
            ask(session.conversation, text, adapter)
        except Exception:  # noqa: BLE001 - the page must never show a stack trace
            # S4: fail open to something readable. The trace goes to the console the
            # server is running in, because a swallowed exception with nowhere to look
            # is the worst of both - the page stays clean and the cause is still findable.
            traceback.print_exc()
            return _html(
                _conversation_page(session, error=errors.user_message(errors.UNREACHABLE)),
                key,
            )

    # Redirect after posting, so refreshing the page does not send the prompt again.
    return _go("/", key)


@app.post("/new")
def new(request: Request):
    """Start again. The old conversation is dropped, not archived."""
    key, session = _session(request)
    session.conversation = Conversation()
    return _go("/", key)


# ---------------------------------------------------------------------------
# accounts
# ---------------------------------------------------------------------------


@app.get("/signup", response_class=HTMLResponse)
def signup_form(request: Request):
    key, session = _session(request)
    if session.signed_in:
        return _go("/", key)
    return _html(signup_page(), key)


@app.post("/signup", response_class=HTMLResponse)
def signup(request: Request, email: str = Form(default=""), password: str = Form(default="")):
    key, session = _session(request)
    try:
        account = accounts.create(db(), email, password)
    except AccountError as exc:
        return _html(signup_page(error=str(exc), email=email), key)
    session.adopt(account)
    return _go("/connect", key)


@app.get("/signin", response_class=HTMLResponse)
def signin_form(request: Request):
    key, session = _session(request)
    if session.signed_in:
        return _go("/", key)
    try:
        first_run = accounts.count(db()) == 0
    except AccountError as exc:
        return _html(trouble_page(str(exc)), key)
    return _html(signup_page() if first_run else signin_page(), key)


@app.post("/signin", response_class=HTMLResponse)
def signin(request: Request, email: str = Form(default=""), password: str = Form(default="")):
    key, session = _session(request)
    try:
        account = accounts.authenticate(db(), email, password)
    except AccountError as exc:
        return _html(signin_page(error=str(exc), email=email), key)
    session.adopt(account)
    return _go("/connect", key)


@app.post("/signout")
def signout(request: Request):
    """Drop the session entirely, so the key and the conversation go with it."""
    key = request.cookies.get(COOKIE)
    sessions.drop(key)
    response = RedirectResponse("/signin", status_code=303)
    response.delete_cookie(COOKIE)
    return response


# ---------------------------------------------------------------------------
# connecting a model
# ---------------------------------------------------------------------------


@app.get("/connect", response_class=HTMLResponse)
def connect_form(request: Request, change: int = 0):
    key, session = _session(request)
    if not session.signed_in:
        return _go("/signin", key)
    if session.connected and not change:
        return _go("/", key)
    return _html(
        connect_page(
            provider=session.provider,
            model=session.model,
            email=session.email,
            replacing=bool(change),
        ),
        key,
    )


@app.post("/connect", response_class=HTMLResponse)
async def connect(request: Request):
    """Take a provider, a model and a key. The key goes into memory and nowhere else."""
    key, session = _session(request)
    if not session.signed_in:
        return _go("/signin", key)

    form = await request.form()
    provider = str(form.get("provider") or "anthropic")
    if provider not in PROVIDERS:
        provider = "anthropic"
    # One list per provider, so the chosen one names its own field.
    model = str(form.get(f"model_{provider}") or "")
    api_key = str(form.get("api_key") or "").strip()

    def again(message: str):
        return _html(
            connect_page(
                provider=provider,
                model=model,
                error=message,
                email=session.email,
                replacing=session.connected,
            ),
            key,
        )

    if not api_key:
        return again(
            f"Paste an API key for {label_for(provider)}. Neutral has no model of its "
            f"own, so it cannot send anything without one."
        )

    session.connect(provider, model, api_key)
    try:
        accounts.set_model(db(), session.account_id or 0, provider, session.model)
    except AccountError as exc:
        session.forget_key()
        return again(str(exc))
    return _go("/", key)


# ---------------------------------------------------------------------------
# the rest
# ---------------------------------------------------------------------------


@app.get("/terms", response_class=HTMLResponse)
def terms() -> HTMLResponse:
    return HTMLResponse(legal_page("Terms of use", TERMS))


@app.get("/privacy", response_class=HTMLResponse)
def privacy() -> HTMLResponse:
    return HTMLResponse(legal_page("Privacy", PRIVACY))


@app.get("/health")
def health() -> dict:
    return {"ok": True}
