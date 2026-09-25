"""Accounts: an email address, a password, and which model you prefer. Nothing else.

This file is the first thing in Neutral that writes to disk, so it needs to say plainly
how it sits with S5 - "no persistence of personal data by default".

S5 exists to protect the people who appear *inside* a prompt. A performance review names
an employee who never agreed to be sent to a language model, and Neutral must not keep a
record of them. That is why the identity map is discarded every request and why prompt
text is never stored.

An account holder is a different party. They are the person operating the tool, they
typed their own email in themselves, and something has to remember them between visits or
there is no account. So the carve-out is narrow and it is structural, not a promise:

  * The table has a column for an email, a password hash, and two preferences.
  * It has no column that could hold prompt text, and no column that could hold a name
    detected in a prompt. A test asserts the column list, so widening it is a build
    failure rather than a judgement call.
  * It has no column for an API key. That is not an oversight - see below.

Why no API key column. Storing a customer's model credentials means either holding them
in the clear, or encrypting them with a key that sits on the same disk, which is
decoration rather than protection. Neither is something to put in front of an enterprise
buyer. The key lives in the session in memory for as long as the browser tab is open, and
is gone when the process stops. The enterprise version puts it in a secrets manager; the
honest MVP does not pretend to be one.

Passwords go through scrypt from the standard library. The parameters are recorded in the
stored string, so they can be raised later without invalidating anybody's existing
password.
"""

from __future__ import annotations

import hmac
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import scrypt
from pathlib import Path

from neutral.adapters.providers import PROVIDERS, default_model_for

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = ROOT / "accounts.db"

# The complete list. tests/test_accounts.py asserts this is what the table has, so a
# column for prompt text or for an API key cannot be added without a test failing.
COLUMNS = ("id", "email", "password", "provider", "model", "created_at")

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id         INTEGER PRIMARY KEY,
    email      TEXT NOT NULL UNIQUE,
    password   TEXT NOT NULL,
    provider   TEXT NOT NULL DEFAULT 'anthropic',
    model      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""

MIN_PASSWORD = 10

# scrypt cost. n=2**14 with r=8 needs 16MB and about a tenth of a second, which is slow
# enough to matter to someone guessing and fast enough not to notice when signing in.
_N, _R, _P, _DKLEN = 2**14, 8, 1, 32

_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")


class AccountError(RuntimeError):
    """Something the person can fix, phrased so they can fix it."""


STORAGE_HELP = (
    "The account database could not be read or written. The usual cause is that the "
    "accounts.db file was moved or deleted while Neutral was running. Stop Neutral with "
    "Ctrl-C and run `make dev` again."
)


@dataclass(frozen=True)
class Account:
    id: int
    email: str
    provider: str
    model: str


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open the account database, creating it if this is the first run."""
    configured = os.environ.get("NEUTRAL_ACCOUNTS_DB", "") or str(DEFAULT_DB)
    target = Path(path) if path is not None else Path(configured)
    if str(target) != ":memory:":
        target.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(target, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    db.commit()
    return db


# ---------------------------------------------------------------------------
# passwords
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    """Return 'scrypt$n$r$p$salt$hash'. The password itself is never stored or logged."""
    salt = os.urandom(16)
    digest = scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    """Compare in constant time, using whatever parameters that row was written with."""
    try:
        scheme, n, r, p, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = scrypt(
            password.encode(),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(digest_hex) // 2,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


# ---------------------------------------------------------------------------
# accounts
# ---------------------------------------------------------------------------


def normalise_email(email: str) -> str:
    return (email or "").strip().lower()


def _validate(email: str, password: str) -> str:
    address = normalise_email(email)
    if not address:
        raise AccountError("Enter an email address.")
    if not _EMAIL.match(address):
        raise AccountError(
            f"{address!r} does not look like an email address. It needs an @ and a "
            f"domain, like you@company.com."
        )
    if len(password) < MIN_PASSWORD:
        raise AccountError(
            f"That password is {len(password)} characters. Use at least {MIN_PASSWORD}."
        )
    return address


def create(db: sqlite3.Connection, email: str, password: str) -> Account:
    """Make an account. Raises AccountError with something readable if it cannot."""
    address = _validate(email, password)
    provider = "anthropic"
    try:
        cursor = db.execute(
            "INSERT INTO accounts (email, password, provider, model, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (address, hash_password(password), provider, default_model_for(provider), _now()),
        )
        db.commit()
    except sqlite3.IntegrityError as exc:
        raise AccountError(
            f"There is already an account for {address}. Sign in instead, or use a "
            f"different address."
        ) from exc
    except sqlite3.Error as exc:
        # Anything else the database can raise - a deleted file, a read-only disk, a
        # locked database. None of it is the person's fault and none of it should reach
        # them as a stack trace.
        raise AccountError(STORAGE_HELP) from exc
    return Account(
        id=int(cursor.lastrowid or 0),
        email=address,
        provider=provider,
        model=default_model_for(provider),
    )


def authenticate(db: sqlite3.Connection, email: str, password: str) -> Account:
    """Return the account, or raise. The message never says which half was wrong."""
    address = normalise_email(email)
    try:
        row = db.execute("SELECT * FROM accounts WHERE email = ?", (address,)).fetchone()
    except sqlite3.Error as exc:
        raise AccountError(STORAGE_HELP) from exc

    # Hash anyway when there is no such account, so a missing address does not answer
    # faster than a wrong password and reveal who has signed up.
    stored = row["password"] if row else hash_password("not-a-real-password")
    ok = check_password(password, stored)

    if not row or not ok:
        raise AccountError("That email and password do not match an account.")
    return Account(
        id=int(row["id"]),
        email=row["email"],
        provider=row["provider"],
        model=row["model"],
    )


def set_model(db: sqlite3.Connection, account_id: int, provider: str, model: str) -> Account:
    """Remember which model this person sends to. Never the key for it."""
    if provider not in PROVIDERS:
        raise AccountError("Choose one of the listed models.")
    chosen = model.strip() or default_model_for(provider)
    try:
        db.execute(
            "UPDATE accounts SET provider = ?, model = ? WHERE id = ?",
            (provider, chosen, account_id),
        )
        db.commit()
        row = db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    except sqlite3.Error as exc:
        raise AccountError(STORAGE_HELP) from exc
    if row is None:
        raise AccountError("That account no longer exists. Sign in again.")
    return Account(
        id=int(row["id"]), email=row["email"], provider=row["provider"], model=row["model"]
    )


def count(db: sqlite3.Connection) -> int:
    try:
        return int(db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0])
    except sqlite3.Error as exc:
        raise AccountError(STORAGE_HELP) from exc


def file_for(db: sqlite3.Connection) -> str:
    """The path this connection was opened on, or "" for an in-memory database.

    Used to notice that the file has been deleted out from under a live connection.
    SQLite keeps writing happily to a deleted inode on some systems and refuses with
    "readonly database" on others, and neither is something to show a person.
    """
    try:
        row = db.execute("PRAGMA database_list").fetchone()
    except sqlite3.Error:
        return ""
    return str(row[2]) if row and row[2] else ""


def still_on_disk(db: sqlite3.Connection) -> bool:
    """False when the file behind this connection has gone away."""
    path = file_for(db)
    return not path or Path(path).exists()
