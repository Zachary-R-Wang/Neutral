"""Sign in, sign up, and connecting a model.

Three pages, no JavaScript needed for any of them to work. The one script here toggles
which model list is showing; with it switched off all four lists appear and the form
still submits correctly.

The wording matters more than usual on these pages. Someone being shown this in a pitch
meeting will read exactly two things: what it wants from them, and what it does with it.
So the key field says where the key goes and how long it stays, in the same size type as
the label rather than in small print.
"""

from __future__ import annotations

import json
from html import escape

from neutral.adapters.providers import ORDER, PROVIDERS, looks_like_model
from neutral.invariants import BANNER
from neutral.web.legal import CONTACT
from neutral.web.page import CORNER, CSS

MODEL_JS = """
(function(){
  var lists = Array.prototype.slice.call(document.querySelectorAll('.models'));
  var link = document.getElementById('keylink');
  var where = JSON.parse(document.getElementById('keyurls').textContent);
  function show(){
    var picked = document.querySelector('input[name=provider]:checked');
    if(!picked) return;
    lists.forEach(function(l){ l.hidden = (l.dataset.provider !== picked.value); });
    // Without this the page would keep telling you to fetch a key from whichever
    // provider happened to be selected when the page was rendered.
    if(link && where[picked.value]){
      link.href = where[picked.value];
      link.textContent = where[picked.value].split('//')[1].split('/')[0];
    }
  }
  document.querySelectorAll('input[name=provider]').forEach(function(r){
    r.addEventListener('change', show);
  });
  show();

  // The free model box only exists while it is ticked for. Hidden and disabled
  // otherwise: a disabled field is not autofilled and is not sent.
  var tick = document.getElementById('use_custom');
  var wrap = document.getElementById('custom_wrap');
  var field = document.getElementById('custom_model');
  function custom(){
    var on = !!(tick && tick.checked);
    if(wrap) wrap.hidden = !on;
    if(field){ field.disabled = !on; if(on) field.focus(); }
  }
  if(tick){ tick.addEventListener('change', custom); }
  if(wrap) wrap.hidden = !(tick && tick.checked);
  if(field) field.disabled = !(tick && tick.checked);
})();
"""


# The connect page has a text box followed by a password box, which is exactly what a
# browser takes to be a username and password - so it filled the saved email into the
# model box. autocomplete="off" is ignored in that position, so every hint that exists is
# given, and none of them is relied on: the server ignores the box unless it was ticked.
_NOT_A_LOGIN = (
    'autocomplete="off" autocapitalize="off" spellcheck="false" '
    'data-1p-ignore data-lpignore="true" data-bwignore data-form-type="other"'
)


def _host(url: str) -> str:
    """Just the domain, so the link reads as a place rather than a path."""
    return url.split("//")[-1].split("/")[0]


def _shell(title: str, body: str, *, script: str = "", corner: bool = True) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} &mdash; Neutral</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet"
  href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&family=Geist+Mono&display=swap">
<style>{CSS}</style></head><body>{CORNER if corner else ""}<div class="wrap">
<div class="top">
  <h1>Neutral</h1>
  <div class="notice">{escape(BANNER)}</div>
</div>
{body}
<div class="foot">
  <a href="/terms">Terms</a><a href="/privacy">Privacy</a>
  <span>Phase 1 &mdash; names and bound pronouns only</span>
</div>
</div>{f"<script>{script}</script>" if script else ""}</body></html>
"""


def _flag(message: str) -> str:
    return f'<div class="flag">{escape(message)}</div>' if message else ""


def _field(
    label: str,
    name: str,
    *,
    kind: str = "text",
    value: str = "",
    placeholder: str = "",
    note: str = "",
    autofocus: bool = False,
    autocomplete: str = "",
    not_a_login: bool = False,
) -> str:
    attrs = [
        f'type="{kind}"',
        *([_NOT_A_LOGIN] if not_a_login else []),
        f'name="{name}"',
        f'value="{escape(value, quote=True)}"',
        f'placeholder="{escape(placeholder, quote=True)}"',
    ]
    if autofocus:
        attrs.append("autofocus")
    if autocomplete:
        attrs.append(f'autocomplete="{autocomplete}"')
    if kind != "text":
        attrs.append("required")
    return f"""<div class="field">
  <label for="{name}">{escape(label)}</label>
  <div class="glow"><div class="oct edge on-light"><div class="oct pad">
    <input id="{name}" {" ".join(attrs)}>
  </div></div></div>
  {f'<p class="note">{note}</p>' if note else ""}
</div>"""


def trouble_page(message: str, *, back: str = "/") -> str:
    """The page shown when something failed that nobody predicted.

    CLAUDE.md section 2: "Error messages must say what went wrong and what to do about
    it, in English, not a stack trace alone." A bare 500 from the web server is the exact
    thing that forbids, so nothing is allowed to reach one.
    """
    return _shell(
        "Something went wrong",
        f"""<div class="card">
  <h2>Something went wrong</h2>
  <p class="lede">{escape(message)}</p>
  <p class="alt"><a href="{escape(back, quote=True)}">Back to Neutral</a></p>
</div>""",
    )


# ---------------------------------------------------------------------------
# sign up and sign in
# ---------------------------------------------------------------------------


def signup_page(*, error: str = "", email: str = "") -> str:
    address = _field(
        "Email",
        "email",
        kind="email",
        value=email,
        placeholder="you@company.com",
        autofocus=True,
        autocomplete="email",
    )
    secret = _field(
        "Password",
        "password",
        kind="password",
        placeholder="At least 10 characters",
        autocomplete="new-password",
    )
    body = f"""<div class="card">
  <h2>Sign Up</h2>
  <div class="intro">
    <p class="lede">Neutral removes signals that can introduce bias or indicate your
    identity before your prompt reaches the model.</p>
    <p class="sub">An account remembers your email and which model you send to. It never
    stores your prompts, and it never stores your API key.</p>
  </div>
  {_flag(error)}
  <form method="post" action="/signup">
    {address}
    {secret}
    <button type="submit" class="wide">Create account</button>
  </form>
  <p class="alt">Already have one? <a href="/signin">Sign in</a></p>
</div>"""
    return _shell("Sign Up", body)


def signin_page(*, error: str = "", email: str = "") -> str:
    address = _field(
        "Email",
        "email",
        kind="email",
        value=email,
        placeholder="you@company.com",
        autofocus=True,
        autocomplete="email",
    )
    body = f"""<div class="card">
  <h2>Sign In</h2>
  <p class="lede">Neutral removes signals that can introduce bias or indicate your
  identity before your prompt reaches the model.</p>
  {_flag(error)}
  <form method="post" action="/signin">
    {address}
    {_field("Password", "password", kind="password", autocomplete="current-password")}
    <button type="submit" class="wide">Sign in</button>
  </form>
  <p class="alt"><a href="/forgot">Forgotten your password?</a></p>
  <p class="alt">No account yet? <a href="/signup">Create one</a></p>
</div>"""
    return _shell("Sign In", body)


# ---------------------------------------------------------------------------
# forgotten passwords
# ---------------------------------------------------------------------------


def forgot_page(*, error: str = "", email: str = "", sent: bool = False) -> str:
    """Ask for an address to send a reset link to.

    The confirmation is deliberately the same whether or not that address has an account.
    Telling an enquirer "no account here" turns this form into a way of asking who has
    signed up, which is nobody's business but theirs.
    """
    if sent:
        body = """<div class="card">
  <h2>Check your email</h2>
  <p class="lede">If that address has an account, a link to set a new password is on its
  way. It works once and expires in an hour.</p>
  <p class="alt"><a href="/signin">Back to sign in</a></p>
</div>"""
        return _shell("Check your email", body)

    address = _field(
        "Email",
        "email",
        kind="email",
        value=email,
        placeholder="you@company.com",
        autofocus=True,
        autocomplete="email",
    )
    body = f"""<div class="card">
  <h2>Forgotten password</h2>
  <p class="lede">Enter the address you signed up with and we will send a link to set a
  new one.</p>
  {_flag(error)}
  <form method="post" action="/forgot">
    {address}
    <button type="submit" class="wide">Send the link</button>
  </form>
  <p class="alt"><a href="/signin">Back to sign in</a></p>
</div>"""
    return _shell("Forgotten password", body)


def reset_page(token: str, *, error: str = "") -> str:
    """Set a new password, having arrived from a link."""
    secret = _field(
        "New password",
        "password",
        kind="password",
        placeholder="At least 10 characters",
        autofocus=True,
        autocomplete="new-password",
    )
    body = f"""<div class="card">
  <h2>Set a new password</h2>
  <p class="lede">This link works once. Choosing a new password signs out anywhere the
  old one was used.</p>
  {_flag(error)}
  <form method="post" action="/reset">
    <input type="hidden" name="token" value="{escape(token, quote=True)}">
    {secret}
    <button type="submit" class="wide">Set password and sign in</button>
  </form>
</div>"""
    return _shell("Set a new password", body)


def reset_unavailable_page() -> str:
    """Shown when no email service is configured, instead of a promise nothing keeps."""
    body = f"""<div class="card">
  <h2>Reset is not set up yet</h2>
  <p class="lede">Neutral cannot send email on this installation, so there is no way to
  reset a password automatically. Email {escape(CONTACT)} and it will be done by hand.</p>
  <p class="alt"><a href="/signin">Back to sign in</a></p>
</div>"""
    return _shell("Reset is not set up yet", body)


# ---------------------------------------------------------------------------
# connecting a model
# ---------------------------------------------------------------------------


def _providers_field(selected: str) -> str:
    pills = "".join(
        f"""<label>
      <input type="radio" name="provider" value="{key}"
        {"checked" if key == selected else ""}>
      <span class="pill">{escape(PROVIDERS[key].label)}</span>
    </label>"""
        for key in ORDER
    )
    return f"""<div class="field">
  <label>Model provider</label>
  <div class="choice">{pills}</div>
</div>"""


def _models_field(selected_provider: str, selected_model: str) -> str:
    """The model choice, as octagons rather than a dropdown.

    A native <select> opens the operating system's own menu, which arrives in whatever
    the machine's chrome looks like and has nothing to do with the rest of this page.
    These are the same pills as the provider row above, one row per provider, with the
    flagship first because it is also the default.

    Underneath is a field for anything not listed. The list is a convenience and never a
    restriction - vendors rename models faster than this file gets edited, and anyone on
    a custom deployment or a fine-tune would never find themselves on it.
    """
    known = {name for spec in PROVIDERS.values() for name in spec.models}
    # Only a saved custom model that could plausibly be one is offered back. The first
    # version put back whatever had been saved - which, after autofill, was an email.
    custom = (
        selected_model
        if selected_model and selected_model not in known and looks_like_model(selected_model)
        else ""
    )

    rows = []
    for key in ORDER:
        spec = PROVIDERS[key]
        # Every row checks one of its OWN models. Testing against the model chosen for
        # some other provider leaves the whole row blank the moment you switch provider.
        checked = selected_model if selected_model in spec.models else spec.models[0]
        pills = "".join(
            f"""<label>
        <input type="radio" name="model_{key}" value="{escape(name, quote=True)}"
          {"checked" if name == checked else ""}>
        <span class="pill">{escape(name)}</span>
      </label>"""
            for name in spec.models
        )
        hidden = "" if key == selected_provider else " hidden"
        rows.append(
            f'<div class="models" data-provider="{key}"{hidden}>'
            f'<div class="choice free">{pills}</div></div>'
        )

    return f"""<div class="field">
  <label>Model</label>
  {"".join(rows)}
  <label class="tick" for="use_custom">
    <input type="checkbox" id="use_custom" name="use_custom"{" checked" if custom else ""}>
    Use a model that is not listed
  </label>
  <div class="custom" id="custom_wrap">
    <div class="glow"><div class="oct edge on-light"><div class="oct pad">
      <input id="custom_model" name="custom_model" type="text" {_NOT_A_LOGIN}
        value="{escape(custom, quote=True)}" placeholder="e.g. gpt-6-sol, or a fine-tune id">
    </div></div></div>
  </div>
</div>"""


def connect_page(
    *,
    provider: str = "anthropic",
    model: str = "",
    error: str = "",
    email: str = "",
    replacing: bool = False,
) -> str:
    """The page that asks for a key. The only page in Neutral that does."""
    spec = PROVIDERS.get(provider) or PROVIDERS["anthropic"]
    heading = "Change model" if replacing else "Connect a model"
    key_note = (
        "Held in memory for this session only. It is not written to disk, not saved to "
        "your account, and gone when you sign out. Keys: "
        f'<a id="keylink" href="{spec.key_url}" target="_blank" rel="noreferrer noopener">'
        f"{escape(_host(spec.key_url))}</a>"
    )
    key_urls = json.dumps({key: PROVIDERS[key].key_url for key in ORDER})
    key_field = _field(
        "API key",
        "api_key",
        kind="password",
        placeholder="Paste your key",
        note=key_note,
        not_a_login=True,
    )
    body = f"""<div class="card wide-card">
  <h2>{escape(heading)}</h2>
  <p class="lede">Neutral does not have a model of its own. Prompts go to whichever
  provider you connect, using your own key, on your own account.</p>
  {_flag(error)}
  <script type="application/json" id="keyurls">{key_urls}</script>
  <form method="post" action="/connect">
    {_providers_field(spec.key)}
    {_models_field(spec.key, model or spec.default_model)}
    {key_field}
    <button type="submit" class="wide">
      {"Use this model" if replacing else "Connect and start"}</button>
  </form>
  <div class="alt">{escape(email)} &nbsp;<span class="sep">&middot;</span>&nbsp;
    <form method="post" action="/signout">
      <button type="submit" class="ghost">Sign out</button></form></div>
</div>"""
    return _shell(heading, body, script=MODEL_JS)
