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

from neutral.adapters.providers import ORDER, PROVIDERS
from neutral.invariants import BANNER
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
})();
"""


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
) -> str:
    attrs = [
        f'type="{kind}"',
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
  <h2>Create an account</h2>
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
    return _shell("Create an account", body)


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
  <h2>Sign in</h2>
  <p class="lede">Neutral removes signals that can introduce bias or indicate your
  identity before your prompt reaches the model.</p>
  {_flag(error)}
  <form method="post" action="/signin">
    {address}
    {_field("Password", "password", kind="password", autocomplete="current-password")}
    <button type="submit" class="wide">Sign in</button>
  </form>
  <p class="alt">No account yet? <a href="/signup">Create one</a></p>
</div>"""
    return _shell("Sign in", body)


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
    lists = []
    for key in ORDER:
        spec = PROVIDERS[key]
        options = "".join(
            f'<option value="{escape(name, quote=True)}"'
            f"{' selected' if name == selected_model else ''}>{escape(name)}</option>"
            for name in spec.models
        )
        hidden = "" if key == selected_provider else " hidden"
        lists.append(
            f"""<div class="models" data-provider="{key}"{hidden}>
    <div class="glow"><div class="oct edge on-light"><div class="oct pad">
      <select name="model_{key}" aria-label="{escape(spec.label)} model">{options}</select>
    </div></div></div>
  </div>"""
        )
    return f"""<div class="field">
  <label>Model</label>
  {"".join(lists)}
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
        autocomplete="off",
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
