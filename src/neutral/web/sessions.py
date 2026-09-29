"""What is remembered while a browser tab is open, and nowhere else.

There are two stores in Neutral and the split between them is the whole security story.

  accounts.db   an email, a password hash, a preferred model.  Survives a restart.
  this file     the conversation, and the API key.              Dies with the process.

The API key is deliberately on the side that does not survive. A person pastes it once
per session and Neutral holds it in a dictionary; there is no file, no column and no
cache to leak it from, and stopping the server erases it. That is also why the session
expires on its own: a demo laptop left open in a hotel lobby should not still be holding
somebody's model credentials the next morning.

Prompt text lives here too, for the same reason - S5 says nothing identifying is written
to disk, and the simplest way to keep that promise is to have nowhere to write it.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field

from neutral.accounts import Account
from neutral.adapters.providers import PROVIDERS, default_model_for, looks_like_model
from neutral.conversation import Conversation

COOKIE = "neutral_session"

# A session with no activity for this long is dropped, key and all.
IDLE_SECONDS = 8 * 60 * 60

# How many sessions are held at once. Every visit without a cookie makes one, so without a
# ceiling a script requesting the sign-in page in a loop could fill the server's memory.
# Past the ceiling the least recently used signed-out sessions go first.
MAX_SESSIONS = 20_000


@dataclass
class Session:
    """One browser tab's worth of state. Never serialised, never written down."""

    conversation: Conversation = field(default_factory=Conversation)
    account_id: int | None = None
    email: str = ""
    provider: str = "anthropic"
    model: str = ""
    # In memory only. Not a column anywhere, by design - see neutral/accounts.py.
    api_key: str = ""
    touched: float = field(default_factory=time.monotonic)

    @property
    def signed_in(self) -> bool:
        return self.account_id is not None

    @property
    def connected(self) -> bool:
        """True when there is a key to send with, so a prompt can actually go out."""
        return bool(self.api_key) and self.provider in PROVIDERS

    @property
    def ready(self) -> bool:
        return self.signed_in and self.connected

    def adopt(self, account: Account) -> None:
        """Sign this session in. Carries the model preference, never a credential."""
        self.account_id = account.id
        self.email = account.email
        self.provider = account.provider or "anthropic"
        # A preference saved before the connect page learnt to refuse junk - an email
        # address, a username - falls back to the default instead of being re-sent.
        self.model = (
            account.model if looks_like_model(account.model) else default_model_for(self.provider)
        )

    def connect(self, provider: str, model: str, api_key: str) -> None:
        self.provider = provider
        self.model = model.strip() or default_model_for(provider)
        self.api_key = api_key.strip()

    def forget_key(self) -> None:
        self.api_key = ""

    def sign_out(self) -> None:
        """Leave nothing behind. The conversation goes with the key."""
        self.account_id = None
        self.email = ""
        self.api_key = ""
        self.conversation = Conversation()


class Sessions:
    """A dictionary with an expiry. Not a database, and not meant to become one."""

    def __init__(self, idle_seconds: float = IDLE_SECONDS, limit: int = MAX_SESSIONS) -> None:
        self._sessions: dict[str, Session] = {}
        self._idle = idle_seconds
        self._limit = limit

    def __len__(self) -> int:
        return len(self._sessions)

    def _expire(self, now: float) -> None:
        stale = [k for k, s in self._sessions.items() if now - s.touched > self._idle]
        for key in stale:
            self._sessions.pop(key, None)

    def _make_room(self) -> None:
        if len(self._sessions) < self._limit:
            return
        by_age = sorted(self._sessions.items(), key=lambda kv: kv[1].touched)
        anonymous = [k for k, s in by_age if not s.signed_in]
        for key in (anonymous or [k for k, _ in by_age])[: max(1, self._limit // 10)]:
            self._sessions.pop(key, None)

    def get(self, key: str | None) -> tuple[str, Session]:
        """Return the session for this cookie, making one if the cookie is new or stale.

        A cookie the server did not issue - stale after a restart, or planted - is never
        adopted as the new session's name. Adopting it let whoever chose the value share
        the session once its owner signed in ("session fixation")."""
        now = time.monotonic()
        self._expire(now)
        if key and key in self._sessions:
            session = self._sessions[key]
            session.touched = now
            return key, session
        self._make_room()
        fresh = secrets.token_urlsafe(24)
        session = Session()
        self._sessions[fresh] = session
        return fresh, session

    def rotate(self, key: str) -> str:
        """Give this session a new name, as it signs in. Anyone who knew the old one -
        from before the person signed in - knows nothing useful now."""
        session = self._sessions.pop(key, None)
        fresh = secrets.token_urlsafe(24)
        if session is not None:
            self._sessions[fresh] = session
        return fresh

    def drop(self, key: str | None) -> None:
        if key:
            self._sessions.pop(key, None)
