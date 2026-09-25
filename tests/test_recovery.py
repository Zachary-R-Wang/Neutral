"""Getting back in after forgetting a password, and what stops somebody guessing.

The properties worth holding onto here are not "it works". They are:

  * the form cannot be used to ask who has an account
  * a stolen copy of the database does not let anyone reset a password with it
  * a link works once, expires, and does not outlive a second request for one
  * a person using the site normally never meets a rate limit
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from neutral import accounts
from neutral.accounts import RESET_COLUMNS, AccountError
from neutral.invariants import verify_account_store_columns
from neutral.throttle import Limit, Throttle, wait_message
from neutral.web import app as app_module
from neutral.web.sessions import Sessions

EMAIL = "hiring@example.com"
PASSWORD = "a-long-enough-password"
NEW_PASSWORD = "an-entirely-different-one"


@pytest.fixture
def db(tmp_path):
    return accounts.connect(tmp_path / "accounts.db")


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A live app with a working mailbox that goes to a list instead of the internet."""
    path = tmp_path / "accounts.db"
    monkeypatch.setenv("NEUTRAL_ACCOUNTS_DB", str(path))
    monkeypatch.setattr(app_module, "_db", None)
    monkeypatch.setattr(app_module, "sessions", Sessions())
    for limit in (app_module.sign_in_limit, app_module.sign_up_limit, app_module.reset_limit):
        limit.reset()

    outbox: list[tuple[str, str, str]] = []
    monkeypatch.setattr(app_module.mailer, "configured", lambda: True)
    monkeypatch.setattr(
        app_module.mailer,
        "send",
        lambda to, subject, body: (outbox.append((to, subject, body)), True)[1],
    )

    with TestClient(app_module.app) as running:
        running.db_path = path
        running.outbox = outbox
        yield running


def _sign_up(client, email: str = EMAIL) -> None:
    got = client.post(
        "/signup", data={"email": email, "password": PASSWORD}, follow_redirects=False
    )
    assert got.status_code == 303, got.text


def _link(client) -> str:
    """The reset link out of the last email sent."""
    assert client.outbox, "no email was sent"
    found = re.search(r"https?://\S+", client.outbox[-1][2])
    assert found, "the email contains no link"
    return found.group(0)


# ---------------------------------------------------------------------------
# the token itself
# ---------------------------------------------------------------------------


class TestTheTokenIsNotStored:
    def test_the_reset_table_holds_no_column_it_should_not(self):
        verify_account_store_columns(RESET_COLUMNS)

    def test_what_is_stored_is_not_what_was_emailed(self, db, tmp_path):
        """A stolen copy of this database must not let anyone reset a password with it."""
        accounts.create(db, EMAIL, PASSWORD)
        _, token = accounts.begin_reset(db, EMAIL)

        stored = db.execute("SELECT token_hash FROM password_resets").fetchone()["token_hash"]
        assert stored != token
        assert token not in stored
        # Nor can the link be found by looking it up as itself.
        assert (
            db.execute("SELECT 1 FROM password_resets WHERE token_hash = ?", (token,)).fetchone()
            is None
        )

        # And it is in none of the files on disk, including the write-ahead log.
        on_disk = b"".join(
            found.read_bytes() for found in sorted(tmp_path.glob("accounts.db*")) if found.is_file()
        )
        assert token.encode() not in on_disk
        assert stored.encode() in on_disk, "not vacuous: the hash really is written down"

    def test_a_token_is_long_enough_not_to_be_guessed(self, db):
        accounts.create(db, EMAIL, PASSWORD)
        _, token = accounts.begin_reset(db, EMAIL)
        assert len(token) >= 32

    def test_two_tokens_are_never_the_same(self, db):
        accounts.create(db, EMAIL, PASSWORD)
        first = accounts.begin_reset(db, EMAIL)[1]
        second = accounts.begin_reset(db, EMAIL)[1]
        assert first != second


class TestALinkIsSpentWhenUsed:
    def test_the_right_token_sets_the_password(self, db):
        made = accounts.create(db, EMAIL, PASSWORD)
        _, token = accounts.begin_reset(db, EMAIL)
        assert accounts.complete_reset(db, token, NEW_PASSWORD).id == made.id
        assert accounts.authenticate(db, EMAIL, NEW_PASSWORD).id == made.id

    def test_the_old_password_stops_working(self, db):
        accounts.create(db, EMAIL, PASSWORD)
        _, token = accounts.begin_reset(db, EMAIL)
        accounts.complete_reset(db, token, NEW_PASSWORD)
        with pytest.raises(AccountError):
            accounts.authenticate(db, EMAIL, PASSWORD)

    def test_the_same_link_cannot_be_used_twice(self, db):
        accounts.create(db, EMAIL, PASSWORD)
        _, token = accounts.begin_reset(db, EMAIL)
        accounts.complete_reset(db, token, NEW_PASSWORD)
        with pytest.raises(AccountError, match="already been used"):
            accounts.complete_reset(db, token, "a-third-password")

    def test_asking_again_kills_the_earlier_link(self, db):
        """Otherwise a link in an old email stays live after you ask for a new one."""
        accounts.create(db, EMAIL, PASSWORD)
        _, first = accounts.begin_reset(db, EMAIL)
        _, second = accounts.begin_reset(db, EMAIL)

        with pytest.raises(AccountError):
            accounts.check_reset(db, first)
        assert accounts.check_reset(db, second).email == EMAIL

    def test_an_expired_link_is_refused(self, db):
        accounts.create(db, EMAIL, PASSWORD)
        _, token = accounts.begin_reset(db, EMAIL)
        stale = (datetime.now(UTC) - timedelta(minutes=1)).isoformat(timespec="seconds")
        db.execute("UPDATE password_resets SET expires_at = ?", (stale,))
        db.commit()

        with pytest.raises(AccountError, match="expired"):
            accounts.complete_reset(db, token, NEW_PASSWORD)

    @pytest.mark.parametrize("bad", ["", "not-a-token", "x" * 43])
    def test_an_invented_token_is_refused(self, db, bad):
        accounts.create(db, EMAIL, PASSWORD)
        with pytest.raises(AccountError):
            accounts.complete_reset(db, bad, NEW_PASSWORD)

    def test_a_short_new_password_is_refused_and_the_link_survives(self, db):
        """Getting the password wrong must not burn the one link they have."""
        accounts.create(db, EMAIL, PASSWORD)
        _, token = accounts.begin_reset(db, EMAIL)
        with pytest.raises(AccountError, match="at least 10"):
            accounts.complete_reset(db, token, "short")
        assert accounts.check_reset(db, token).email == EMAIL


# ---------------------------------------------------------------------------
# the pages
# ---------------------------------------------------------------------------


class TestTheFormCannotBeUsedToAskWhoHasAnAccount:
    def test_a_known_and_an_unknown_address_answer_identically(self, client):
        _sign_up(client)
        known = client.post("/forgot", data={"email": EMAIL})
        unknown = client.post("/forgot", data={"email": "stranger@example.com"})
        assert known.status_code == unknown.status_code
        assert known.text == unknown.text

    def test_only_the_address_that_exists_gets_an_email(self, client):
        _sign_up(client)
        client.post("/forgot", data={"email": "stranger@example.com"})
        assert client.outbox == []
        client.post("/forgot", data={"email": EMAIL})
        assert [to for to, _, _ in client.outbox] == [EMAIL]


class TestTheWholeJourney:
    def test_forgetting_a_password_and_getting_back_in(self, client):
        _sign_up(client)
        client.post("/forgot", data={"email": EMAIL})

        opened = client.get(_link(client))
        assert "Set a new password" in opened.text

        token = re.search(r'name="token" value="([^"]+)"', opened.text).group(1)
        done = client.post(
            "/reset", data={"token": token, "password": NEW_PASSWORD}, follow_redirects=False
        )
        # Signed in already, so nobody types the new password twice.
        assert done.status_code == 303
        assert done.headers["location"] == "/connect"

    def test_the_email_says_what_to_do_if_you_did_not_ask(self, client):
        _sign_up(client)
        client.post("/forgot", data={"email": EMAIL})
        body = client.outbox[-1][2]
        assert "did not ask" in body
        assert "expires in an hour" in body

    def test_a_used_link_sends_you_back_to_ask_for_another(self, client):
        _sign_up(client)
        client.post("/forgot", data={"email": EMAIL})
        link = _link(client)
        token = re.search(r"token=([^&]+)", link).group(1)
        client.post("/reset", data={"token": token, "password": NEW_PASSWORD})

        again = client.get(link)
        assert "Forgotten password" in again.text
        assert "Ask for a new one" in again.text

    def test_the_sign_in_page_offers_a_way_through_to_it(self, client):
        _sign_up(client)
        client.post("/signout")
        assert "/forgot" in client.get("/signin").text

    def test_with_no_mail_service_it_says_so_instead_of_promising(self, client, monkeypatch):
        """Saying "check your inbox" when nothing can send is the worst possible answer."""
        monkeypatch.setattr(app_module.mailer, "configured", lambda: False)
        page = client.get("/forgot").text
        assert "not set up yet" in page
        assert "Check your email" not in page


# ---------------------------------------------------------------------------
# rate limiting
# ---------------------------------------------------------------------------


class TestTheLimitItself:
    def test_it_allows_exactly_the_stated_number(self):
        t = Throttle(Limit(attempts=3, per_seconds=60))
        for _ in range(3):
            assert t.retry_after("k") == 0
            t.record("k")
        assert t.retry_after("k") > 0

    def test_a_success_clears_the_count(self):
        t = Throttle(Limit(attempts=2, per_seconds=60))
        t.record("k")
        t.record("k")
        assert t.retry_after("k") > 0
        t.clear("k")
        assert t.retry_after("k") == 0

    def test_the_window_passes(self):
        t = Throttle(Limit(attempts=1, per_seconds=0.05))
        t.record("k")
        assert t.retry_after("k") > 0
        import time as _t

        _t.sleep(0.08)
        assert t.retry_after("k") == 0

    def test_keys_do_not_interfere(self):
        t = Throttle(Limit(attempts=1, per_seconds=60))
        t.record("one")
        assert t.retry_after("one") > 0
        assert t.retry_after("two") == 0

    def test_the_longest_wait_among_several_keys_wins(self):
        t = Throttle(Limit(attempts=1, per_seconds=60))
        t.record("email:someone")
        assert t.retry_after("ip:1.2.3.4", "email:someone") > 0

    def test_it_does_not_hold_on_to_keys_that_have_gone_quiet(self):
        t = Throttle(Limit(attempts=5, per_seconds=0.05))
        for i in range(50):
            t.record(f"ip:{i}")
        import time as _t

        _t.sleep(0.08)
        for i in range(50):
            t.retry_after(f"ip:{i}")
        assert len(t._hits) == 0

    @pytest.mark.parametrize("seconds", [5, 45, 120, 3600, 7200])
    def test_the_message_never_says_how_many_attempts_are_left(self, seconds):
        message = wait_message(seconds)
        assert "attempt" not in message.lower().replace("attempts from here", "")
        assert any(word in message for word in ("second", "minute", "hour"))


class TestGuessingIsSlowedDown:
    def test_a_wrong_password_eventually_locks_out(self, client):
        _sign_up(client)
        client.post("/signout")
        last = None
        for _ in range(11):
            last = client.post("/signin", data={"email": EMAIL, "password": "wrong-one"})
        assert "Too many attempts" in last.text

    def test_the_real_password_stops_working_too_once_locked(self, client):
        """Otherwise the limit is decoration - guess until locked, then use the real one."""
        _sign_up(client)
        client.post("/signout")
        for _ in range(11):
            client.post("/signin", data={"email": EMAIL, "password": "wrong-one"})
        blocked = client.post(
            "/signin", data={"email": EMAIL, "password": PASSWORD}, follow_redirects=False
        )
        assert blocked.status_code == 200
        assert "Too many attempts" in blocked.text

    def test_signing_in_correctly_does_not_count_towards_the_limit(self, client):
        """A person who uses the site normally must never meet this."""
        _sign_up(client)
        for _ in range(20):
            client.post("/signout")
            got = client.post(
                "/signin", data={"email": EMAIL, "password": PASSWORD}, follow_redirects=False
            )
            assert got.status_code == 303, "an honest sign-in was rate limited"

    def test_making_accounts_is_limited(self, client):
        last = None
        for i in range(6):
            last = client.post(
                "/signup", data={"email": f"person{i}@example.com", "password": PASSWORD}
            )
        assert "Too many attempts" in last.text

    def test_asking_for_reset_links_is_limited(self, client):
        _sign_up(client)
        last = None
        for _ in range(5):
            last = client.post("/forgot", data={"email": EMAIL})
        assert "Too many attempts" in last.text
        assert len(client.outbox) <= 4

    def test_the_limit_counts_the_forwarded_address_not_the_proxy(self, client):
        """Behind a proxy every request arrives from the proxy. Counting that locks out
        everybody at once the first time one person guesses."""
        _sign_up(client)
        client.post("/signout")
        for _ in range(11):
            client.post(
                "/signin",
                data={"email": EMAIL, "password": "wrong-one"},
                headers={"fly-client-ip": "203.0.113.9"},
            )
        # A different origin, same account: the per-address limit still bites, which is
        # what stops one account being attacked from many machines.
        other = client.post(
            "/signin",
            data={"email": EMAIL, "password": "wrong-one"},
            headers={"fly-client-ip": "198.51.100.4"},
        )
        assert "Too many attempts" in other.text

        # A different account from a fresh origin is unaffected.
        _ = client.post("/signup", data={"email": "other@example.com", "password": PASSWORD})
        fresh = client.post(
            "/signin",
            data={"email": "other@example.com", "password": PASSWORD},
            headers={"fly-client-ip": "198.51.100.4"},
            follow_redirects=False,
        )
        assert fresh.status_code == 303, "an unrelated account was caught by the limit"
