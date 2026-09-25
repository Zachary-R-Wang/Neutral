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

import os
import threading
import traceback

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from neutral import accounts, errors, mailer
from neutral.accounts import AccountError
from neutral.adapters.providers import PROVIDERS, build, label_for, looks_like_model
from neutral.conversation import Conversation, ask
from neutral.throttle import RESET, SIGN_IN, SIGN_UP, Throttle, wait_message
from neutral.web.access import (
    connect_page,
    forgot_page,
    reset_page,
    reset_unavailable_page,
    signin_page,
    signup_page,
    trouble_page,
)
from neutral.web.legal import PRIVACY, TERMS
from neutral.web.page import legal_page, page
from neutral.web.sessions import COOKIE, Session, Sessions

app = FastAPI(title="Neutral", docs_url=None, redoc_url=None)

sessions = Sessions()

# Guessing costs something now. Only failures count, so somebody using the site normally
# never meets these - see the reasoning in neutral/throttle.py.
sign_in_limit = Throttle(SIGN_IN)
sign_up_limit = Throttle(SIGN_UP)
reset_limit = Throttle(RESET)


def client_ip(request: Request) -> str:
    """Who is asking, as well as that can be known from behind a proxy.

    Fly sets fly-client-ip itself and overwrites anything a caller sent, so it is the one
    to trust where it exists. x-forwarded-for is a fallback and can be written by whoever
    is calling, which is why it is not preferred: on its own it would let somebody defeat
    a per-origin limit by inventing a new origin each time.
    """
    direct = request.headers.get("fly-client-ip", "").strip()
    if direct:
        return f"ip:{direct}"
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if forwarded:
        return f"ip:{forwarded}"
    return f"ip:{request.client.host if request.client else 'unknown'}"


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


# Set NEUTRAL_PUBLIC=true when Neutral is reachable over the internet. It marks the
# session cookie "secure", which tells the browser never to send it over plain HTTP.
# Off by default because a secure cookie is not sent over http://127.0.0.1 either, and
# nobody should have to discover that while trying to sign in locally.
PUBLIC = os.environ.get("NEUTRAL_PUBLIC", "").strip().lower() == "true"


def _cookie(response, key: str):
    response.set_cookie(
        COOKIE,
        key,
        httponly=True,
        samesite="lax",
        secure=PUBLIC,
        max_age=8 * 60 * 60,
    )
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
    origin = client_ip(request)

    waiting = sign_up_limit.retry_after(origin)
    if waiting:
        return _html(signup_page(error=wait_message(waiting), email=email), key)

    try:
        account = accounts.create(db(), email, password)
    except AccountError as exc:
        return _html(signup_page(error=str(exc), email=email), key)
    # Counted on success, not on failure: the cost being limited here is accounts
    # existing, not people mistyping their own address.
    sign_up_limit.record(origin)
    session.adopt(account)
    return _go("/connect", key)


@app.get("/signin", response_class=HTMLResponse)
def signin_form(request: Request):
    """Always the sign-in page.

    This used to show the sign-up page instead when no account existed yet, meaning the
    "Sign in" link on the sign-up page led straight back to the sign-up page. The link
    looked broken because it was. Signing in is also the right thing for an arriving
    visitor to see: a product that asks you to register before it will admit it has
    existing users reads like it has none.
    """
    key, session = _session(request)
    if session.signed_in:
        return _go("/", key)
    return _html(signin_page(), key)


@app.post("/signin", response_class=HTMLResponse)
def signin(request: Request, email: str = Form(default=""), password: str = Form(default="")):
    key, session = _session(request)
    origin = client_ip(request)
    address = f"email:{accounts.normalise_email(email)}"

    # Both the machine and the address are counted. Either alone leaves a way round:
    # many machines against one account, or one machine against many accounts.
    waiting = sign_in_limit.retry_after(origin, address)
    if waiting:
        return _html(signin_page(error=wait_message(waiting), email=email), key)

    try:
        account = accounts.authenticate(db(), email, password)
    except AccountError as exc:
        sign_in_limit.record(origin, address)
        return _html(signin_page(error=str(exc), email=email), key)

    sign_in_limit.clear(origin, address)
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
# forgotten passwords
# ---------------------------------------------------------------------------


@app.get("/forgot", response_class=HTMLResponse)
def forgot_form(request: Request):
    key, _ = _session(request)
    if not mailer.configured():
        return _html(reset_unavailable_page(), key)
    return _html(forgot_page(), key)


@app.post("/forgot", response_class=HTMLResponse)
def forgot(request: Request, email: str = Form(default="")):
    """Email a reset link, and say the same thing whether or not there was an account."""
    key, _ = _session(request)
    if not mailer.configured():
        return _html(reset_unavailable_page(), key)

    origin = client_ip(request)
    address = f"reset:{accounts.normalise_email(email)}"
    waiting = reset_limit.retry_after(origin, address)
    if waiting:
        return _html(forgot_page(error=wait_message(waiting), email=email), key)
    reset_limit.record(origin, address)

    try:
        started = accounts.begin_reset(db(), email)
    except AccountError as exc:
        return _html(forgot_page(error=str(exc), email=email), key)

    if started is not None:
        account, token = started
        link = str(request.url_for("reset_form").include_query_params(token=token))
        subject, message = mailer.reset_email(link)
        mailer.send(account.email, subject, message)

    # The same page either way. Whether the send failed is in the server log, not here:
    # a different answer for an address that exists turns this form into a way of asking
    # who has an account.
    return _html(forgot_page(sent=True), key)


@app.get("/reset", response_class=HTMLResponse, name="reset_form")
def reset_form(request: Request, token: str = ""):
    key, _ = _session(request)
    try:
        accounts.check_reset(db(), token)
    except AccountError as exc:
        return _html(forgot_page(error=str(exc)), key)
    return _html(reset_page(token), key)


@app.post("/reset", response_class=HTMLResponse)
def reset(request: Request, token: str = Form(default=""), password: str = Form(default="")):
    """Set the new password and sign in, so nobody has to type it twice."""
    key, session = _session(request)
    try:
        account = accounts.complete_reset(db(), token, password)
    except AccountError as exc:
        try:
            accounts.check_reset(db(), token)
        except AccountError:
            # The link itself is spent or expired; sending them back to the password
            # form would just fail again.
            return _html(forgot_page(error=str(exc)), key)
        return _html(reset_page(token, error=str(exc)), key)

    sign_in_limit.clear(client_ip(request), f"email:{account.email}")
    session.adopt(account)
    return _go("/connect", key)


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
    picked = str(form.get(f"model_{provider}") or "")
    # The free box counts only when its box was ticked. It used to win whenever it had
    # anything in it, and a browser's autofill put the account email there - which then
    # overrode the option the person had actually chosen. Autofill never ticks a box.
    custom = str(form.get("custom_model") or "").strip()
    use_custom = form.get("use_custom") == "on" and bool(custom)
    model = custom if use_custom else picked
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

    if use_custom and not looks_like_model(custom):
        # Said out loud, never quietly swapped for the pill: silently replacing one
        # choice with another is how this went wrong in the first place. The rejected
        # text is not echoed back, since it may be somebody's email address.
        model = picked
        return again(
            "What is in the custom model box does not look like a model name - they look "
            "like gpt-6-astra or claude-sonnet-5. If your browser filled that box in by "
            "itself, untick \u201cUse a model that is not listed\u201d."
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
