"""Accounts, sessions, and the gate in front of the model.

The tests that matter most in this file are the two at the bottom. One reads the raw bytes
of the account database and asserts a person's API key is not in them. The other reads
every page the app can render while a key is loaded and asserts the key is not in any of
them. Those two are the reason the split between accounts.db and web/sessions.py exists,
and they are the ones that should fail loudly if somebody later adds a convenient
"remember my key" checkbox.
"""

from __future__ import annotations

import re
import sqlite3

import pytest
from fastapi.testclient import TestClient

from neutral import accounts
from neutral.accounts import COLUMNS, AccountError
from neutral.adapters.base import Completion
from neutral.adapters.providers import PROVIDERS
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
        assert account.model == "claude-opus-5-5"

    def test_a_choice_survives_signing_out_and_back_in(self, db):
        account = accounts.create(db, EMAIL, PASSWORD)
        accounts.set_model(db, account.id, "google", "gemini-3.7-flash")
        again = accounts.authenticate(db, EMAIL, PASSWORD)
        assert (again.provider, again.model) == ("google", "gemini-3.7-flash")

    def test_an_unknown_provider_is_refused(self, db):
        account = accounts.create(db, EMAIL, PASSWORD)
        with pytest.raises(AccountError):
            accounts.set_model(db, account.id, "not-a-provider", "x")

    def test_an_empty_model_falls_back_to_that_providers_default(self, db):
        account = accounts.create(db, EMAIL, PASSWORD)
        assert accounts.set_model(db, account.id, "xai", "  ").model == "grok-4.7"


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
        session.adopt(accounts.Account(1, EMAIL, "openai", "gpt-6-astra"))
        assert session.signed_in and not session.ready
        session.connect("openai", "gpt-6-astra", KEY)
        assert session.ready

    def test_signing_out_takes_the_key_and_the_conversation(self):
        session = Session()
        session.adopt(accounts.Account(1, EMAIL, "anthropic", "claude-opus-5-5"))
        session.connect("anthropic", "claude-opus-5-5", KEY)
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
    # The limits are deliberately process-wide in production. In a suite that signs up
    # dozens of times from one address that is cross-contamination, so each test starts
    # with them empty - except the ones below that are about the limits themselves.
    for limit in (app_module.sign_in_limit, app_module.sign_up_limit, app_module.reset_limit):
        limit.reset()
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
            ("anthropic", "claude-sonnet-5"),
            ("openai", "gpt-6-sol"),
            ("google", "gemini-3.7-flash"),
            ("xai", "grok-4.6"),
            ("deepseek", "deepseek-v4-pro"),
        ],
    )
    def test_the_chosen_provider_and_model_are_what_gets_used(self, client, provider, model):
        _sign_up(client)
        _connect(client, provider, model)
        client.post("/", data={"prompt": "Assess Ravi."}, follow_redirects=False)
        assert _Adapter.built == [(provider, KEY, model)]

    def test_the_header_says_which_model_is_connected(self, client):
        _sign_up(client)
        _connect(client, "google", "gemini-3.8-flash")
        page = client.get("/").text
        assert "Gemini gemini-3.8-flash" in page
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


class TestPickingAModel:
    """The model choice is not a dropdown, and not a closed list."""

    def test_no_page_uses_a_native_dropdown(self, client):
        """A <select> opens the operating system's own menu, which is not this design."""
        _sign_up(client)
        assert "<select" not in client.get("/connect").text

    @pytest.mark.parametrize("provider", sorted(PROVIDERS))
    def test_the_flagship_is_listed_first_and_is_the_default(self, provider):
        spec = PROVIDERS[provider]
        assert spec.default_model == spec.models[0]

    @pytest.mark.parametrize("provider", sorted(PROVIDERS))
    def test_every_listed_model_is_offered_on_the_page(self, client, provider):
        _sign_up(client)
        body = client.get("/connect").text
        for name in PROVIDERS[provider].models:
            assert f'value="{name}"' in body, f"{name} is not offered"

    @pytest.mark.parametrize("viewing", sorted(PROVIDERS))
    def test_every_providers_row_has_exactly_one_model_chosen(self, client, viewing):
        """Switching provider must not leave the model row with nothing selected.

        Each row used to be checked against the model picked for whichever provider was
        current, so every other row came up blank.
        """
        _sign_up(client)
        _connect(client, viewing, PROVIDERS[viewing].models[-1])
        body = client.get("/connect?change=1").text

        for key, spec in PROVIDERS.items():
            row = re.search(rf'data-provider="{key}".*?</div></div>', body, re.S)
            assert row, f"no model row for {key}"
            chosen = re.findall(r'value="([^"]+)"[^>]*\s*checked', row.group(0))
            assert len(chosen) == 1, f"{key} has {len(chosen)} models chosen, not 1"
            assert chosen[0] in spec.models

    def test_a_model_name_that_is_not_on_the_list_can_still_be_used(self, client):
        """Vendors rename models faster than this file gets edited."""
        _sign_up(client)
        client.post(
            "/connect",
            data={
                "provider": "openai",
                "model_openai": "gpt-6-luna",
                "model_other": "  ft:my-private-tune  ",
                "api_key": KEY,
            },
            follow_redirects=False,
        )
        client.post("/", data={"prompt": "Assess Ravi."}, follow_redirects=False)
        assert _Adapter.built == [("openai", KEY, "ft:my-private-tune")]

    def test_a_typed_name_comes_back_in_the_field_rather_than_vanishing(self, client):
        _sign_up(client)
        client.post(
            "/connect",
            data={"provider": "xai", "model_other": "grok-9-unreleased", "api_key": KEY},
            follow_redirects=False,
        )
        assert 'value="grok-9-unreleased"' in client.get("/connect?change=1").text

    def test_leaving_the_free_field_empty_uses_the_pill_that_is_selected(self, client):
        _sign_up(client)
        client.post(
            "/connect",
            data={"provider": "xai", "model_xai": "grok-4.5", "model_other": "   ", "api_key": KEY},
            follow_redirects=False,
        )
        client.post("/", data={"prompt": "Assess Ravi."}, follow_redirects=False)
        assert _Adapter.built == [("xai", KEY, "grok-4.5")]


class TestSigningInAndOut:
    def test_an_arriving_visitor_lands_on_the_sign_in_page(self, client):
        """Not on the sign-up page, and not only once somebody has registered.

        /signin used to render the sign-up page while no account existed, which meant
        the "Sign in" link on the sign-up page led back to the sign-up page. See the
        test below - that link is the whole reason this one is written this way.
        """
        landing = client.get("/", follow_redirects=False)
        assert landing.headers["location"] == "/signin"
        assert "<h2>Sign In</h2>" in client.get("/signin").text

    def test_the_sign_in_link_actually_reaches_a_sign_in_page(self, client):
        """The bug as reported: clicking Sign in appeared to do nothing."""
        for accounts_exist in (False, True):
            if accounts_exist:
                _sign_up(client)
                client.post("/signout", follow_redirects=False)

            signup = client.get("/signup").text
            assert 'href="/signin"' in signup, "no way out of the sign-up page"

            arrived = client.get("/signin").text
            assert "<h2>Sign In</h2>" in arrived, (
                f"with accounts_exist={accounts_exist}, the sign-in link led somewhere "
                f"that is not the sign-in page"
            )
            assert 'action="/signin"' in arrived

    def test_the_two_pages_reach_each_other_in_both_directions(self, client):
        assert 'href="/signin"' in client.get("/signup").text
        assert 'href="/signup"' in client.get("/signin").text

    def test_the_heading_does_not_repeat_the_button(self, client):
        """ "Create an account" above a "Create account" button said it twice."""
        body = client.get("/signup").text
        assert "<h2>Sign Up</h2>" in body
        assert "Create an account" not in body
        assert ">Create account</button>" in body

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
        _connect(client, "openai", "gpt-6-astra")
        client.post("/signout", follow_redirects=False)
        client.post("/signin", data={"email": EMAIL, "password": PASSWORD}, follow_redirects=False)
        got = client.get("/", follow_redirects=False)
        assert got.headers["location"] == "/connect"
        # The remembered choice comes back; the credential does not.
        assert "gpt-6-astra" in client.get("/connect").text

    def test_the_cookie_is_marked_secure_when_neutral_is_public(self, tmp_path, monkeypatch):
        """On a public site the session cookie must never travel over plain HTTP."""
        monkeypatch.setenv("NEUTRAL_ACCOUNTS_DB", str(tmp_path / "a.db"))
        monkeypatch.setattr(app_module, "_db", None)
        monkeypatch.setattr(app_module, "sessions", Sessions())
        monkeypatch.setattr(app_module, "PUBLIC", True)

        with TestClient(app_module.app) as public:
            header = public.post(
                "/signup", data={"email": EMAIL, "password": PASSWORD}
            ).headers.get("set-cookie", "")
        assert "secure" in header.lower()

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


def _everything_on_disk(db_path) -> bytes:
    """Every byte SQLite wrote, not just the main file.

    In write-ahead logging mode a recent write lives in accounts.db-wal until it is
    folded into accounts.db, so reading only the main file would scan past exactly the
    data that was written most recently - which is the data worth checking.
    """
    return b"".join(
        found.read_bytes()
        for found in sorted(db_path.parent.glob(db_path.name + "*"))
        if found.is_file()
    )


class TestTheKeyIsNeverWrittenDown:
    def test_it_is_not_in_any_file_the_database_wrote(self, client):
        _sign_up(client)
        _connect(client, "openai", "gpt-6-astra")
        client.post("/", data={"prompt": "Assess Ravi Menon."})

        raw = _everything_on_disk(client.db_path)
        assert KEY.encode() not in raw
        # The preference is there, so this is not passing because the files are empty.
        assert b"gpt-6-astra" in raw

    def test_nor_is_the_prompt_or_anybody_named_in_it(self, client):
        _sign_up(client)
        _connect(client)
        client.post("/", data={"prompt": "Assess Ravi Menon for promotion."})

        raw = _everything_on_disk(client.db_path)
        for leaked in (b"Ravi", b"Menon", b"promotion", b"Person A"):
            assert leaked not in raw

    def test_the_table_holds_one_row_and_nothing_else_accumulates(self, client):
        _sign_up(client)
        _connect(client)
        for i in range(3):
            client.post("/", data={"prompt": f"Assess Ravi Menon, question {i}."})

        raw = sqlite3.connect(client.db_path)
        tables = sorted(
            r[0]
            for r in raw.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if not r[0].startswith("sqlite_")
        )
        assert tables == ["accounts", "password_resets"]
        assert raw.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1
        # Three conversations, and the reset table is untouched. Asking for a link is
        # the only thing that should ever put a row in it.
        assert raw.execute("SELECT COUNT(*) FROM password_resets").fetchone()[0] == 0


class TestTheKeyIsNeverShownBack:
    @pytest.mark.parametrize("path", ["/", "/connect?change=1", "/terms", "/privacy"])
    def test_no_page_echoes_it_while_it_is_loaded(self, client, path):
        _sign_up(client)
        _connect(client, "openai", "gpt-6-astra")
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
