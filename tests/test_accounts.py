"""Accounts, sessions, and the gate in front of the model.

The tests that matter most in this file are the two at the bottom. One reads the raw bytes
of the account database and asserts a person's API key is not in them. The other reads
every page the app can render while a key is loaded and asserts the key is not in any of
them. Those two are the reason the split between accounts.db and web/sessions.py exists,
and they are the ones that should fail loudly if somebody later adds a convenient
"remember my key" checkbox.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from neutral import accounts
from neutral.accounts import COLUMNS, AccountError
from neutral.adapters.base import Completion
from neutral.conversation import Conversation
from neutral.web import app as app_module
from neutral.web.sessions import Session, Sessions

EMAIL = "hiring@example.com"
PASSWORD = "a-long-enough-password"
KEY = "sk-ant-thisisthesecretkeythatmustnotleak"


@pytest.fixture
def db(tmp_path):
    return accounts.connect(tmp_path / "accounts.db")


# ---------------------------------------------------------------------------
# what the table may hold
# ---------------------------------------------------------------------------


class TestTheSchemaCannotHoldWhatItShouldNot:
    def test_the_columns_are_exactly_the_declared_list(self, db):
        found = tuple(row["name"] for row in db.execute("PRAGMA table_info(accounts)").fetchall())
        assert found == COLUMNS

    def test_there_is_no_column_for_an_api_key(self, db):
        found = " ".join(COLUMNS).lower()
        for forbidden in ("api_key", "apikey", "key", "secret", "token", "credential"):
            assert forbidden not in found.split()

    def test_there_is_no_column_that_could_hold_a_prompt(self, db):
        found = " ".join(COLUMNS).lower()
        for forbidden in ("prompt", "message", "turn", "answer", "response", "name"):
            assert forbidden not in found.split()


class TestPasswords:
    def test_the_password_is_not_in_what_gets_stored(self, db):
        accounts.create(db, EMAIL, PASSWORD)
        row = db.execute("SELECT password FROM accounts").fetchone()
        assert PASSWORD not in row["password"]
        assert row["password"].startswith("scrypt$")

    def test_the_right_password_is_accepted(self, db):
        made = accounts.create(db, EMAIL, PASSWORD)
        assert accounts.authenticate(db, EMAIL, PASSWORD).id == made.id

    def test_the_wrong_password_is_not(self, db):
        accounts.create(db, EMAIL, PASSWORD)
        with pytest.raises(AccountError):
            accounts.authenticate(db, EMAIL, PASSWORD + "x")

    def test_two_hashes_of_one_password_differ(self):
        """Each row gets its own salt, so identical passwords do not look identical."""
        assert accounts.hash_password(PASSWORD) != accounts.hash_password(PASSWORD)

    def test_a_damaged_hash_fails_closed(self):
        for broken in ("", "nonsense", "scrypt$bad", "md5$1$1$1$aa$bb"):
            assert not accounts.check_password(PASSWORD, broken)


class TestSigningUp:
    def test_the_email_is_normalised(self, db):
        accounts.create(db, "  Hiring@Example.COM ", PASSWORD)
        assert accounts.authenticate(db, EMAIL, PASSWORD).email == EMAIL

    def test_the_same_address_cannot_be_taken_twice(self, db):
        accounts.create(db, EMAIL, PASSWORD)
        with pytest.raises(AccountError, match="already an account"):
            accounts.create(db, EMAIL.upper(), PASSWORD)

    @pytest.mark.parametrize("bad", ["", "   ", "nope", "no@domain", "@example.com"])
    def test_something_that_is_not_an_address_is_refused(self, db, bad):
        with pytest.raises(AccountError):
            accounts.create(db, bad, PASSWORD)

    def test_a_short_password_is_refused_with_the_length_in_the_message(self, db):
        with pytest.raises(AccountError, match="at least 10"):
            accounts.create(db, EMAIL, "short")

    def test_the_failure_message_does_not_reveal_who_has_an_account(self, db):
        accounts.create(db, EMAIL, PASSWORD)
        with pytest.raises(AccountError) as wrong_password:
            accounts.authenticate(db, EMAIL, "not-the-password")
        with pytest.raises(AccountError) as no_such_person:
            accounts.authenticate(db, "stranger@example.com", PASSWORD)
        assert str(wrong_password.value) == str(no_such_person.value)


class TestTheRememberedModel:
    def test_a_new_account_starts_with_a_working_default(self, db):
        account = accounts.create(db, EMAIL, PASSWORD)
        assert account.provider == "anthropic"
        assert account.model == "claude-sonnet-5"

    def test_a_choice_survives_signing_out_and_back_in(self, db):
        account = accounts.create(db, EMAIL, PASSWORD)
        accounts.set_model(db, account.id, "google", "gemini-2.5-flash")
        again = accounts.authenticate(db, EMAIL, PASSWORD)
        assert (again.provider, again.model) == ("google", "gemini-2.5-flash")

    def test_an_unknown_provider_is_refused(self, db):
        account = accounts.create(db, EMAIL, PASSWORD)
        with pytest.raises(AccountError):
            accounts.set_model(db, account.id, "not-a-provider", "x")

    def test_an_empty_model_falls_back_to_that_providers_default(self, db):
        account = accounts.create(db, EMAIL, PASSWORD)
        assert accounts.set_model(db, account.id, "xai", "  ").model == "grok-4"


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------


class TestSessionsLiveAndDie:
    def test_a_new_cookie_gets_a_session_and_the_same_cookie_gets_it_back(self):
        store = Sessions()
        key, first = store.get(None)
        assert store.get(key)[1] is first

    def test_an_idle_session_is_dropped_with_its_key(self):
        store = Sessions(idle_seconds=-1)
        key, session = store.get(None)
        session.api_key = KEY
        assert store.get(key)[1].api_key == ""

    def test_nothing_is_ready_until_there_is_both_an_account_and_a_key(self):
        session = Session()
        assert not session.ready
        session.adopt(accounts.Account(1, EMAIL, "openai", "gpt-5"))
        assert session.signed_in and not session.ready
        session.connect("openai", "gpt-5", KEY)
        assert session.ready

    def test_signing_out_takes_the_key_and_the_conversation(self):
        session = Session()
        session.adopt(accounts.Account(1, EMAIL, "anthropic", "claude-sonnet-5"))
        session.connect("anthropic", "claude-sonnet-5", KEY)
        session.conversation = Conversation()
        session.sign_out()
        assert session.api_key == "" and not session.signed_in


# ---------------------------------------------------------------------------
# the app
# ---------------------------------------------------------------------------


class _Adapter:
    """Answers without a network. Records what it was built with."""

    built: list[tuple[str, str, str]] = []

    def __init__(self, provider: str, api_key: str, model: str):
        _Adapter.built.append((provider, api_key, model))

    def complete(self, prompt, *, system="", history=()):
        return Completion(text="An assessment.", model="test")


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A live app with its own database, and nothing that can reach a network."""
    path = tmp_path / "accounts.db"
    monkeypatch.setenv("NEUTRAL_ACCOUNTS_DB", str(path))
    monkeypatch.setattr(app_module, "_db", None)
    monkeypatch.setattr(app_module, "sessions", Sessions())
    _Adapter.built = []
    monkeypatch.setattr(
        app_module,
        "build",
        lambda provider, api_key, model="", **kw: _Adapter(provider, api_key, model),
    )
    with TestClient(app_module.app) as running:
        running.db_path = path
        yield running


def _sign_up(client, email: str = EMAIL) -> None:
    got = client.post(
        "/signup", data={"email": email, "password": PASSWORD}, follow_redirects=False
    )
    assert got.status_code == 303, got.text


def _connect(client, provider: str = "anthropic", model: str = "") -> None:
    got = client.post(
        "/connect",
        data={"provider": provider, f"model_{provider}": model, "api_key": KEY},
        follow_redirects=False,
    )
    assert got.status_code == 303, got.text


class TestNothingReachesAModelWithoutAnAccountAndAKey:
    def test_a_stranger_is_sent_to_sign_in(self, client):
        got = client.get("/", follow_redirects=False)
        assert got.status_code == 303
        assert got.headers["location"] == "/signin"

    def test_a_signed_in_person_with_no_key_is_sent_to_connect(self, client):
        _sign_up(client)
        got = client.get("/", follow_redirects=False)
        assert got.headers["location"] == "/connect"

    def test_posting_a_prompt_with_no_key_sends_no_prompt_anywhere(self, client):
        _sign_up(client)
        got = client.post("/", data={"prompt": "Assess Ravi."}, follow_redirects=False)
        assert got.headers["location"] == "/connect"
        assert _Adapter.built == []

    def test_posting_a_prompt_while_signed_out_sends_no_prompt_anywhere(self, client):
        got = client.post("/", data={"prompt": "Assess Ravi."}, follow_redirects=False)
        assert got.headers["location"] == "/signin"
        assert _Adapter.built == []

    def test_once_both_are_present_the_prompt_goes_through(self, client):
        _sign_up(client)
        _connect(client)
        client.post("/", data={"prompt": "Assess Ravi Menon."}, follow_redirects=False)
        assert len(_Adapter.built) == 1


class TestTheUserChoosesWhereTheirPromptGoes:
    @pytest.mark.parametrize(
        ("provider", "model"),
        [
            ("anthropic", "claude-opus-5"),
            ("openai", "gpt-5-mini"),
            ("google", "gemini-2.5-flash"),
            ("xai", "grok-3"),
            ("deepseek", "deepseek-reasoner"),
        ],
    )
    def test_the_chosen_provider_and_model_are_what_gets_used(self, client, provider, model):
        _sign_up(client)
        _connect(client, provider, model)
        client.post("/", data={"prompt": "Assess Ravi."}, follow_redirects=False)
        assert _Adapter.built == [(provider, KEY, model)]

    def test_the_header_says_which_model_is_connected(self, client):
        _sign_up(client)
        _connect(client, "google", "gemini-2.5-pro")
        page = client.get("/").text
        assert "Gemini gemini-2.5-pro" in page
        assert EMAIL in page

    def test_a_missing_key_is_refused_in_plain_english(self, client):
        _sign_up(client)
        got = client.post(
            "/connect", data={"provider": "openai", "api_key": "  "}, follow_redirects=False
        )
        assert got.status_code == 200
        assert "Paste an API key for OpenAI" in got.text

    def test_an_invented_provider_falls_back_rather_than_erroring(self, client):
        _sign_up(client)
        got = client.post(
            "/connect",
            data={"provider": "../../etc/passwd", "api_key": KEY},
            follow_redirects=False,
        )
        assert got.status_code == 303
        client.post("/", data={"prompt": "Hello."}, follow_redirects=False)
        assert _Adapter.built[0][0] == "anthropic"


class TestTheFirstPageSaysWhatTheProductIs:
    """A visitor who has never heard of Neutral lands on the sign-up page.

    Before accounts existed, the opening page carried this sentence. Moving sign-up in
    front of it meant the first thing a stranger saw was a form asking for an email with
    no explanation of what for. These tests keep the sentence on every page someone can
    reach before they are signed in.
    """

    EXPLANATION = "removes signals that can introduce bias or indicate your"

    @pytest.mark.parametrize("path", ["/", "/signin", "/signup"])
    def test_every_page_before_signing_in_explains_what_neutral_does(self, client, path):
        assert self.EXPLANATION in client.get(path).text

    def test_it_is_still_there_once_a_second_person_signs_up(self, client):
        """The first visit shows sign-up; later visits show sign-in. Both must say it."""
        _sign_up(client)
        client.post("/signout", follow_redirects=False)
        assert self.EXPLANATION in client.get("/signin").text

    def test_it_comes_before_the_form(self, client):
        """Stated as an ordering, because underneath the fields is the same as absent."""
        body = client.get("/signup").text
        assert body.index(self.EXPLANATION) < body.index('name="email"')

    def test_the_opening_of_a_conversation_still_says_it_too(self, client):
        _sign_up(client)
        _connect(client)
        assert self.EXPLANATION in client.get("/").text


class TestSigningInAndOut:
    def test_the_very_first_visit_offers_to_create_an_account(self, client):
        assert "Create an account" in client.get("/signin").text

    def test_once_someone_exists_the_page_asks_them_to_sign_in(self, client):
        _sign_up(client)
        client.post("/signout", follow_redirects=False)
        body = client.get("/signin").text
        assert "Sign in" in body and "Create an account" not in body

    def test_a_wrong_password_shows_a_sentence_not_a_stack_trace(self, client):
        _sign_up(client)
        client.post("/signout", follow_redirects=False)
        got = client.post(
            "/signin", data={"email": EMAIL, "password": "wrong-one"}, follow_redirects=False
        )
        assert got.status_code == 200
        assert "do not match an account" in got.text
        assert "Traceback" not in got.text

    def test_a_duplicate_signup_is_explained_rather_than_failing(self, client):
        _sign_up(client)
        client.post("/signout", follow_redirects=False)
        got = client.post(
            "/signup", data={"email": EMAIL, "password": PASSWORD}, follow_redirects=False
        )
        assert "already an account" in got.text

    def test_signing_out_and_back_in_needs_the_key_again(self, client):
        _sign_up(client)
        _connect(client, "openai", "gpt-5")
        client.post("/signout", follow_redirects=False)
        client.post("/signin", data={"email": EMAIL, "password": PASSWORD}, follow_redirects=False)
        got = client.get("/", follow_redirects=False)
        assert got.headers["location"] == "/connect"
        # The remembered choice comes back; the credential does not.
        assert "gpt-5" in client.get("/connect").text

    def test_the_session_cookie_is_not_readable_by_scripts(self, client):
        _sign_up(client)
        header = client.post(
            "/signup", data={"email": "other@example.com", "password": PASSWORD}
        ).headers.get("set-cookie", "")
        assert "httponly" in header.lower()

    def test_two_people_do_not_see_each_others_conversations(self, client, tmp_path):
        _sign_up(client)
        _connect(client)
        client.post("/", data={"prompt": "Assess Ravi Menon for promotion."})
        assert "Ravi Menon" in client.get("/").text

        other = TestClient(app_module.app)
        _sign_up(other, "second@example.com")
        _connect(other)
        assert "Ravi Menon" not in other.get("/").text


class TestAFailingDatabaseIsExplainedNotThrown:
    """CLAUDE.md section 2: an error says what happened and what to do, in English.

    These exist because signing up really did answer with a blank "Internal Server Error"
    after accounts.db was deleted while the server was running. The page gave a person
    with no way to debug it precisely nothing.
    """

    def test_a_deleted_database_is_reopened_rather_than_breaking_every_write(self, client):
        _sign_up(client)
        client.db_path.unlink()

        got = client.post(
            "/signup",
            data={"email": "after@example.com", "password": PASSWORD},
            follow_redirects=False,
        )
        assert got.status_code == 303, "signing up should work again, not fail"
        assert client.db_path.exists()

    def test_a_storage_failure_reads_as_a_sentence(self, client, monkeypatch):
        def broken(*a, **k):
            raise sqlite3.OperationalError("attempt to write a readonly database")

        monkeypatch.setattr(app_module.accounts, "create", broken)
        got = client.post(
            "/signup", data={"email": EMAIL, "password": PASSWORD}, follow_redirects=False
        )
        assert got.status_code == 500
        assert "Internal Server Error" not in got.text
        assert "Something went wrong" in got.text
        assert "OperationalError" not in got.text and "Traceback" not in got.text

    def test_the_readable_message_says_what_to_do_about_it(self, db, tmp_path):
        """Against a genuinely read-only database, which is the error that was hit."""
        accounts.create(db, EMAIL, PASSWORD)
        readonly = sqlite3.connect(f"file:{tmp_path / 'accounts.db'}?mode=ro", uri=True)
        readonly.row_factory = sqlite3.Row

        with pytest.raises(AccountError) as caught:
            accounts.create(readonly, "other@example.com", PASSWORD)

        message = str(caught.value)
        assert "make dev" in message
        assert "readonly" not in message and "sqlite" not in message.lower()

    @pytest.mark.parametrize("path", ["/", "/signin", "/signup", "/connect"])
    def test_no_page_can_answer_with_a_bare_server_error(self, client, monkeypatch, path):
        monkeypatch.setattr(
            app_module, "db", lambda: (_ for _ in ()).throw(RuntimeError("nothing works"))
        )
        got = client.get(path)
        assert "Internal Server Error" not in got.text
        assert "Traceback" not in got.text


# ---------------------------------------------------------------------------
# the two that matter
# ---------------------------------------------------------------------------


class TestTheKeyIsNeverWrittenDown:
    def test_it_is_not_in_the_database_file(self, client):
        _sign_up(client)
        _connect(client, "openai", "gpt-5")
        client.post("/", data={"prompt": "Assess Ravi Menon."})

        raw = client.db_path.read_bytes()
        assert KEY.encode() not in raw
        # The preference is there, so this is not passing because the file is empty.
        assert b"gpt-5" in raw

    def test_nor_is_the_prompt_or_anybody_named_in_it(self, client):
        _sign_up(client)
        _connect(client)
        client.post("/", data={"prompt": "Assess Ravi Menon for promotion."})

        raw = client.db_path.read_bytes()
        for leaked in (b"Ravi", b"Menon", b"promotion", b"Person A"):
            assert leaked not in raw

    def test_the_table_holds_one_row_and_nothing_else_accumulates(self, client):
        _sign_up(client)
        _connect(client)
        for i in range(3):
            client.post("/", data={"prompt": f"Assess Ravi Menon, question {i}."})

        raw = sqlite3.connect(client.db_path)
        tables = [r[0] for r in raw.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        assert tables == ["accounts"]
        assert raw.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1


class TestTheKeyIsNeverShownBack:
    @pytest.mark.parametrize("path", ["/", "/connect?change=1", "/terms", "/privacy"])
    def test_no_page_echoes_it_while_it_is_loaded(self, client, path):
        _sign_up(client)
        _connect(client, "openai", "gpt-5")
        body = client.get(path).text
        assert KEY not in body
        # Not even a fragment long enough to be useful.
        assert KEY[8:24] not in body

    def test_the_connect_form_comes_back_empty_rather_than_prefilled(self, client):
        _sign_up(client)
        _connect(client)
        body = client.get("/connect?change=1").text
        assert 'name="api_key"' in body
        assert 'value=""' in body
        assert KEY not in body

    def test_the_page_says_where_the_key_lives(self, client):
        """A person handing over a credential is told the terms in normal-sized type."""
        _sign_up(client)
        body = client.get("/connect").text
        assert "memory for this session only" in body
        assert "not written to disk" in body
