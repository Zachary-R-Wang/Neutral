"""The HTML for the one page.

Server-rendered, no frontend framework, no build step - CLAUDE.md section 4. The only
interactivity is a <details> element, which needs no JavaScript at all.

Everything that came from a person is escaped before it reaches the page. The prompt is
typed by a user and the answers come from a model; neither is trusted as markup.
"""

from __future__ import annotations

from html import escape

from neutral.core import NeutralResult, SegmentKind
from neutral.invariants import BANNER

CSS = """
:root{--surface:#fcfcfb;--plane:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--line:#e1e0d9;--accent:#2a78d6;--warn:#fab219;--hold:#d03b3b;color-scheme:light}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--surface:#1a1a19;
--plane:#0d0d0d;--ink:#fff;--ink2:#c3c2b7;--muted:#898781;--line:#2c2c2a;--accent:#3987e5;
color-scheme:dark}}
*{box-sizing:border-box}
body{margin:0;background:var(--plane);color:var(--ink);
font:16px/1.6 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1040px;margin:0 auto;padding:28px 16px 72px}
.banner{background:var(--warn);color:#0b0b0b;padding:11px 16px;border-radius:8px;
font-weight:600;font-size:14px;margin-bottom:26px}
h1{font-size:27px;margin:0 0 4px;letter-spacing:-.02em}
.tag{color:var(--ink2);margin:0 0 26px;font-size:15px}
form{margin:0 0 26px}
textarea{width:100%;min-height:140px;padding:14px;border:1px solid var(--line);
border-radius:10px;background:var(--surface);color:var(--ink);font:inherit;resize:vertical}
textarea:focus{outline:2px solid var(--accent);outline-offset:1px}
.row{display:flex;gap:12px;align-items:center;margin-top:12px;flex-wrap:wrap}
button{background:var(--accent);color:#fff;border:0;border-radius:8px;padding:11px 22px;
font:inherit;font-weight:600;cursor:pointer}
button:hover{filter:brightness(1.08)}
.hint{color:var(--muted);font-size:13px}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:760px){.cols{grid-template-columns:1fr}}
.card{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:18px}
.card h2{font-size:15px;margin:0 0 3px;letter-spacing:-.01em}
.card .sub{color:var(--muted);font-size:13px;margin:0 0 12px}
.answer{white-space:pre-wrap;font-size:15px}
details{background:var(--surface);border:1px solid var(--line);border-radius:12px;
padding:14px 18px;margin-bottom:16px}
summary{cursor:pointer;font-weight:600;font-size:15px}
table{border-collapse:collapse;width:100%;font-size:14px;margin-top:14px}
th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--ink2);font-weight:600}
code{background:var(--plane);padding:1px 5px;border-radius:4px;font-size:13px}
.prompt{white-space:pre-wrap;background:var(--plane);border:1px solid var(--line);
border-radius:8px;padding:12px;font-size:14px;margin-top:12px}
.del{background:rgba(208,59,59,.16);text-decoration:line-through;border-radius:3px;padding:0 2px}
.ins{background:rgba(42,120,214,.16);border-radius:3px;padding:0 2px;font-weight:600}
.hold{background:var(--hold);color:#fff;padding:12px 16px;border-radius:10px;
margin-bottom:16px;font-size:14px}
.note{background:var(--surface);border:1px solid var(--line);border-left:3px solid var(--warn);
border-radius:8px;padding:12px 16px;margin-bottom:16px;font-size:14px;color:var(--ink2)}
footer{color:var(--muted);font-size:13px;margin-top:34px;line-height:1.7}
"""

PLACEHOLDER = (
    "Paste a prompt. For example: Write the areas-for-development section of Emily "
    "Carter's performance review. She shipped the refund API redesign but missed the "
    "reconciliation deadline by three weeks."
)

HOW_IT_READS = {
    "person_name": "a name carries ethnicity, gender, and the expectations attached to it",
    "pronoun": "a gendered pronoun states the gender of the person it refers to",
}


def _marked_prompt(result: NeutralResult) -> str:
    """The original prompt with each change shown in place."""
    out = []
    for segment in result.segments:
        if segment.kind is SegmentKind.COPY:
            out.append(escape(segment.text))
        elif segment.kind is SegmentKind.REPLACE and segment.source:
            was = segment.source.text_in(result.original_prompt)
            out.append(f'<span class="del">{escape(was)}</span>')
            out.append(f'<span class="ins">{escape(segment.text)}</span>')
        else:
            out.append(f'<span class="ins">{escape(segment.text)}</span>')
    return "".join(out)


def _changes_table(result: NeutralResult) -> str:
    if not result.transforms:
        return "<p class='sub'>Nothing was changed.</p>"
    rows = "".join(
        f"<tr><td><code>{escape(t.detected)}</code></td>"
        f"<td><code>{escape(t.replacement)}</code></td>"
        f"<td>{escape(HOW_IT_READS.get(t.detected_kind, t.detected_kind))}</td>"
        f"<td>{escape(t.policy)}/{escape(t.policy_version)}</td></tr>"
        for t in result.transforms
    )
    return (
        "<table><thead><tr><th>Was</th><th>Became</th><th>Why it was removed</th>"
        f"<th>Policy</th></tr></thead><tbody>{rows}</tbody></table>"
    )


def render_result(result: NeutralResult) -> str:
    parts = []

    if result.refused:
        parts.append(
            '<div class="hold">The model declined this request. Its refusal is shown '
            "below exactly as it was given. Neutral did not rewrite the prompt, retry "
            "it, or send it again.</div>"
        )
    elif result.passthrough:
        parts.append(
            f'<div class="hold">Neutral did not change this prompt. '
            f"{escape(result.passthrough_reason or '')}</div>"
        )

    if not result.passthrough:
        parts.append(
            "<details open><summary>What Neutral changed, and why</summary>"
            f"{_changes_table(result)}"
            "<p class='sub' style='margin-top:16px'>Your prompt, with the changes shown "
            "in place. Struck-through red was removed; blue was put in its place.</p>"
            f'<div class="prompt">{_marked_prompt(result)}</div>'
            "</details>"
        )

    if not (result.original_response or result.processed_response):
        # Nothing came back from the model, so there is nothing to compare. Showing two
        # empty boxes would imply otherwise.
        return "".join(parts)

    if result.passthrough:
        # Both answers exist and are the same text. S2 is satisfied by showing it; two
        # identical boxes would only suggest a difference that is not there.
        parts.append(
            '<div class="card"><h2>The model\'s answer</h2>'
            '<p class="sub">Neutral made no changes, so there is one answer, not two. '
            "This is exactly what the model said to your prompt as written.</p>"
            f'<div class="answer">{escape(result.original_response)}</div></div>'
        )
        return "".join(parts)

    left_title = "Through Neutral"
    left_sub = (
        "what the model said to your prompt as written"
        if result.passthrough
        else "identity removed, then put back so it reads naturally"
    )
    parts.append(
        '<div class="cols">'
        f'<div class="card"><h2>{escape(left_title)}</h2>'
        f'<p class="sub">{escape(left_sub)}</p>'
        f'<div class="answer">{escape(result.processed_response)}</div></div>'
        '<div class="card"><h2>Original</h2>'
        '<p class="sub">what the model said to your prompt as written</p>'
        f'<div class="answer">{escape(result.original_response)}</div></div>'
        "</div>"
    )
    return "".join(parts)


def page(*, prompt: str = "", result: NeutralResult | None = None, error: str = "") -> str:
    body = []
    if error:
        body.append(f'<div class="hold">{escape(error)}</div>')
    if result is not None:
        body.append(render_result(result))

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Neutral</title><style>{CSS}</style></head><body><div class="wrap">

<div class="banner">{escape(BANNER)}</div>

<h1>Neutral</h1>
<p class="tag">Removes signals about <em>who is asking</em> before your prompt reaches the
model, then puts them back so the answer still reads naturally. Both answers are always
shown, so you can see for yourself what difference it made.</p>

<form method="post" action="/">
  <textarea name="prompt" placeholder="{escape(PLACEHOLDER)}">{escape(prompt)}</textarea>
  <div class="row">
    <button type="submit">Run it through Neutral</button>
    <span class="hint">Nothing you type is saved. Names exist in memory for this request
    only, then are discarded.</span>
  </div>
</form>

{"".join(body)}

<footer>
Phase 1 — personal names and the gendered pronouns bound to them. Order neutralisation,
person neutralisation and comparison framing are not built yet.<br>
Neutral never adds anything to your prompt, and never rewrites a prompt where identity
could affect whether the request is safe to answer — those are passed through untouched
and the reason is shown.
</footer>

</div></body></html>
"""
