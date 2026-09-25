"""How often one person may hit a form before Neutral makes them wait.

There is exactly one thing this protects against and it is worth naming, because a limit
aimed at the wrong thing is theatre. It is guessing: somebody working through passwords
against a known email address, or a script filling the sign-up form with junk. It is not
a defence against a large distributed attack, and nothing here pretends otherwise.

Two design notes.

**Only failures count.** Signing in correctly clears the record. A person who uses the
site normally never meets a limit; a person who guesses wrong ten times does. Counting
successes too would lock out the one user who is doing nothing wrong.

**Both the address and the origin are counted.** Limiting by origin alone lets somebody
spread guesses for one account across many machines. Limiting by address alone lets one
machine work through a list of addresses, a few guesses each, forever. Neither on its own
is enough, so both are checked and the longer wait wins.

Held in memory, so it resets when the server does. That is the honest limit of this: it
is a speed bump sized for the kind of nuisance a small site actually meets, not a
security boundary.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Limit:
    """This many attempts inside this many seconds, then wait."""

    attempts: int
    per_seconds: float

    def __post_init__(self) -> None:
        if self.attempts < 1 or self.per_seconds <= 0:
            raise ValueError("a limit needs at least one attempt and a positive window")


# Signing in wrong. Generous enough that a person typing badly never notices, tight
# enough that working through a password list is pointless.
SIGN_IN = Limit(attempts=10, per_seconds=15 * 60)

# Making accounts. Nobody legitimately needs six in an hour from one machine.
SIGN_UP = Limit(attempts=5, per_seconds=60 * 60)

# Asking for a reset link. Low, because each one sends an email to somebody who did not
# necessarily ask for it, and a form that can be used to pester a stranger is a problem
# whatever it does to this server.
RESET = Limit(attempts=4, per_seconds=60 * 60)


class Throttle:
    """A counter per key, with a window. Not a database and not meant to become one."""

    def __init__(self, limit: Limit) -> None:
        self.limit = limit
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, now: float) -> deque[float]:
        hits = self._hits[key]
        cutoff = now - self.limit.per_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if not hits:
            # Do not keep a key alive just because somebody touched it once an hour ago.
            self._hits.pop(key, None)
            return deque()
        return hits

    def retry_after(self, *keys: str) -> float:
        """Seconds until the next attempt is allowed. Zero means go ahead.

        Several keys can be checked at once - an address and an origin, say - and the
        longest wait among them is the one that applies.
        """
        now = time.monotonic()
        longest = 0.0
        for key in keys:
            if not key:
                continue
            hits = self._prune(key, now)
            if len(hits) >= self.limit.attempts:
                wait = hits[0] + self.limit.per_seconds - now
                longest = max(longest, wait)
        return max(0.0, longest)

    def record(self, *keys: str) -> None:
        """Note one attempt against each key."""
        now = time.monotonic()
        for key in keys:
            if key:
                self._hits[key].append(now)

    def clear(self, *keys: str) -> None:
        """Forget the attempts against these keys. Called when somebody gets it right."""
        for key in keys:
            self._hits.pop(key, None)

    def reset(self) -> None:
        self._hits.clear()


def wait_message(seconds: float) -> str:
    """Say how long to wait, in units a person uses, without naming a limit.

    Never says how many attempts are left or what the limit is. That is not secrecy for
    its own sake - a counter shown to somebody guessing tells them exactly how to pace
    themselves to stay under it.
    """
    if seconds <= 90:
        return (
            "Too many attempts from here. Wait about a minute and try again."
            if seconds > 30
            else "Too many attempts from here. Wait a few seconds and try again."
        )
    minutes = int(seconds // 60) + 1
    if minutes < 60:
        return f"Too many attempts from here. Try again in about {minutes} minutes."
    hours = int(seconds // 3600) + 1
    unit = "hour" if hours == 1 else "hours"
    return f"Too many attempts from here. Try again in about {hours} {unit}."
