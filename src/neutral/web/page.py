"""The page: a conversation, not a form.

Server-rendered, no frontend framework, no build step - CLAUDE.md section 4. Expanding an
original answer is a <details> element, so it needs no JavaScript and works with the page
JavaScript disabled.

What is shown, and what is not:

  * The thread shows the answers the user came for - the ones with names put back.
  * The rewritten prompt is NOT shown. It is machinery, and putting it in the thread makes
    the conversation unreadable.
  * Every answer carries a small control that opens, in place, the answer the model gave
    to the prompt as written. That is S2: the original is always one click away, never
    hidden, and never in a modal that covers the conversation.

Everything a person or a model produced is escaped before it reaches the page.
"""

from __future__ import annotations

from html import escape

from neutral.conversation import Conversation, Turn
from neutral.invariants import BANNER

PLACEHOLDER = (
    "Ask anything. For example: Write the areas-for-development section of Emily "
    "Carter's performance review. She shipped the refund API redesign but missed the "
    "reconciliation deadline by three weeks."
)

CSS = """
:root{--surface:#fcfcfb;--plane:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--line:#e1e0d9;--accent:#2a78d6;--warn:#fab219;--hold:#d03b3b;
--raw:#f2f0ea;--raw-line:#d8d5c8;color-scheme:light}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--surface:#1a1a19;
--plane:#0d0d0d;--ink:#fff;--ink2:#c3c2b7;--muted:#898781;--line:#2c2c2a;--accent:#3987e5;
--raw:#232321;--raw-line:#3a3a36;color-scheme:dark}}
*{box-sizing:border-box}
body{margin:0;background:var(--plane);color:var(--ink);
font:16px/1.65 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:780px;margin:0 auto;padding:22px 16px 40px;min-height:100vh;
display:flex;flex-direction:column}
.banner{background:var(--warn);color:#0b0b0b;padding:9px 14px;border-radius:8px;
font-weight:600;font-size:13px;margin-bottom:20px}
.brand{display:flex;align-items:center;gap:10px;margin-bottom:6px}
.brand h1{font-size:21px;margin:0;letter-spacing:-.02em}
.brand span{color:var(--muted);font-size:13px}

/* ---- opening state ---- */
.opening{flex:1;display:flex;flex-direction:column;justify-content:center;
align-items:center;text-align:center;padding-bottom:12vh}
.opening h2{font-size:27px;margin:0 0 10px;letter-spacing:-.02em}
.opening p{color:var(--ink2);margin:0 0 26px;max-width:30em}
.opening form{width:100%;max-width:640px}

/* ---- conversation ---- */
.thread{flex:1;display:flex;flex-direction:column;gap:22px;margin-bottom:26px}
.asked{align-self:flex-end;max-width:86%;background:var(--accent);color:#fff;
padding:10px 15px;border-radius:15px 15px 4px 15px;white-space:pre-wrap;font-size:15px}
.reply{align-self:flex-start;max-width:96%}
.reply .text{white-space:pre-wrap;font-size:15.5px}
.flag{background:var(--surface);border:1px solid var(--line);border-left:3px solid var(--warn);
border-radius:8px;padding:9px 13px;font-size:13px;color:var(--ink2);margin-bottom:9px}
.flag.stop{border-left-color:var(--hold)}

/* ---- the original answer, opening in place ---- */
details.original{margin-top:7px}
details.original>summary{display:inline-flex;align-items:center;gap:5px;cursor:pointer;
font-size:12px;color:var(--muted);border:1px solid var(--line);border-radius:999px;
padding:2px 10px;list-style:none;user-select:none}
details.original>summary::-webkit-details-marker{display:none}
details.original>summary:hover{color:var(--ink2);border-color:var(--raw-line)}
details.original>summary::before{content:"\\25B8";font-size:9px;transition:transform .12s}
details.original[open]>summary::before{transform:rotate(90deg)}
details.original[open]>summary{color:var(--ink2)}
.raw{margin-top:6px;background:var(--raw);border:1px solid var(--raw-line);
border-left:3px solid var(--raw-line);border-radius:8px;padding:10px 13px}
.raw .label{font-size:11px;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);
margin-bottom:5px}
.raw .text{white-space:pre-wrap;font-size:13.5px;line-height:1.5;color:var(--ink2)}
.raw .changes{margin-top:9px;padding-top:8px;border-top:1px solid var(--raw-line);
font-size:12px;color:var(--muted)}
.raw .changes code{background:var(--plane);padding:0 4px;border-radius:3px}

/* ---- composer ---- */
form.composer{position:sticky;bottom:0;background:var(--plane);padding-top:8px}
.box{display:flex;gap:9px;align-items:flex-end;border:1px solid var(--line);
border-radius:14px;background:var(--surface);padding:8px 8px 8px 14px}
.box:focus-within{border-color:var(--accent)}
textarea{flex:1;border:0;background:transparent;color:var(--ink);font:inherit;
font-size:15px;resize:none;outline:none;max-height:180px;min-height:26px;padding:4px 0}
button{background:var(--accent);color:#fff;border:0;border-radius:10px;
padding:9px 17px;font:inherit;font-weight:600;cursor:pointer;white-space:nowrap}
button:hover{filter:brightness(1.08)}
button.ghost{background:transparent;color:var(--muted);border:1px solid var(--line);
font-weight:500;font-size:12px;padding:4px 11px;border-radius:999px}
button.ghost:hover{color:var(--ink2);filter:none}
.hint{color:var(--muted);font-size:12px;margin:8px 2px 0;line-height:1.55}
.hint a{color:var(--muted)}
"""


def _flag(turn: Turn) -> str:
    if not turn.note:
        return ""
    stop = " stop" if turn.failed or turn.untouched else ""
    return f'<div class="flag{stop}">{escape(turn.note)}</div>'


def _changes(turn: Turn) -> str:
    if not turn.changes:
        return ""
    items = ", ".join(
        f"<code>{escape(c.detected)}</code> &rarr; <code>{escape(c.replacement)}</code>"
        for c in turn.changes
    )
    return f'<div class="changes">Removed before sending: {items}</div>'


def _turn(turn: Turn) -> str:
    parts = [f'<div class="asked">{escape(turn.asked)}</div>']

    reply = [f'<div class="reply">{_flag(turn)}']
    if turn.answer:
        reply.append(f'<div class="text">{escape(turn.answer)}</div>')

    if turn.failed and turn.changes:
        reply.append(
            '<details class="original" open><summary>What Neutral would have removed'
            '</summary><div class="raw"><div class="label">Computed locally, nothing '
            f"was sent</div>{_changes(turn)}</div></details>"
        )

    # S2 - the unmodified answer is always reachable, in place, never in a modal.
    if turn.original_answer and not turn.untouched:
        reply.append(
            '<details class="original">'
            "<summary>Original response</summary>"
            '<div class="raw"><div class="label">What the model said to your prompt '
            "as written</div>"
            f'<div class="text">{escape(turn.original_answer)}</div>'
            f"{_changes(turn)}</div></details>"
        )
    reply.append("</div>")
    parts.append("".join(reply))
    return "".join(parts)


def _composer(*, opening: bool) -> str:
    label = "Start" if opening else "Send"
    return f"""<form class="composer" method="post" action="/">
  <div class="box">
    <textarea name="prompt" rows="1" autofocus
      placeholder="{escape(PLACEHOLDER) if opening else "Reply..."}"></textarea>
    <button type="submit">{label}</button>
  </div>
  <p class="hint">Nothing is saved. Names are held in memory for one request, then
  discarded. Each reply is shown with the identity put back; the original is one click
  away.</p>
</form>"""


def page(conversation: Conversation | None = None, *, error: str = "") -> str:
    started = conversation is not None and conversation.started

    if started:
        thread = "".join(_turn(t) for t in conversation.turns)
        body = f'<div class="thread">{thread}</div>{_composer(opening=False)}'
    else:
        body = f"""<div class="opening">
  <h2>What do you want to ask?</h2>
  <p>Neutral removes signals about who is asking before your prompt reaches the model,
  then puts them back so the answer reads normally.</p>
  {_composer(opening=True)}
</div>"""

    banner_error = f'<div class="flag stop">{escape(error)}</div>' if error else ""
    reset = (
        '<form method="post" action="/new" style="margin-left:auto">'
        '<button type="submit" class="ghost">New conversation</button></form>'
        if started
        else ""
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Neutral</title><style>{CSS}</style></head><body><div class="wrap">
<div class="banner">{escape(BANNER)}</div>
<div class="brand"><h1>Neutral</h1>
<span>identity removed before the model sees it</span>{reset}</div>
{banner_error}
{body}
</div></body></html>
"""
