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
from neutral.adapters.providers import PROVIDERS, default_model_for
from neutral.conversation import Conversation

COOKIE = "neutral_session"

# A session with no activity for this long is dropped, key and all.
IDLE_SECONDS = 8 * 60 * 60


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
        self.model = account.model or default_model_for(self.provider)

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

    def __init__(self, idle_seconds: float = IDLE_SECONDS) -> None:
        self._sessions: dict[str, Session] = {}
        self._idle = idle_seconds

    def __len__(self) -> int:
        return len(self._sessions)

    def _expire(self, now: float) -> None:
        stale = [k for k, s in self._sessions.items() if now - s.touched > self._idle]
        for key in stale:
            self._sessions.pop(key, None)

    def get(self, key: str | None) -> tuple[str, Session]:
        """Return the session for this cookie, making one if the cookie is new or stale."""
        now = time.monotonic()
        self._expire(now)
        if key and key in self._sessions:
            session = self._sessions[key]
            session.touched = now
            return key, session
        fresh = key or secrets.token_urlsafe(24)
        session = Session()
        self._sessions[fresh] = session
        return fresh, session

    def drop(self, key: str | None) -> None:
        if key:
            self._sessions.pop(key, None)
