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

import re
from html import escape

from neutral.conversation import Conversation, Turn
from neutral.invariants import BANNER

PLACEHOLDER = (
    "Ask anything. For example: Write the areas-for-development section of Emily "
    "Carter's performance review. She shipped the refund API redesign but missed the "
    "reconciliation deadline by three weeks."
)

CSS = """
/* Values taken from vercel.com and its Geist design system, read off the live site
   rather than approximated: text hsl(0 0% 9%) on hsl(0 0% 98%), borders at 92% light and
   18% dark, headings at weight 400 with tight negative tracking, 6px radii, and almost no
   colour at all. The restraint is the point - nothing here is decorative. */
:root{
  --bg:hsl(0 0% 98%); --panel:hsl(0 0% 100%); --subtle:hsl(0 0% 95%);
  --fg:hsl(0 0% 9%); --fg-2:hsl(0 0% 30%); --fg-3:hsl(0 0% 56%);
  --line:hsl(0 0% 92%); --line-2:hsl(0 0% 90%);
  --solid:hsl(0 0% 9%); --on-solid:hsl(0 0% 100%);
  --amber:hsl(38 92% 45%);
  color-scheme:light;
}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){
  --bg:hsl(0 0% 0%); --panel:hsl(0 0% 4%); --subtle:hsl(0 0% 10%);
  --fg:hsl(0 0% 93%); --fg-2:hsl(0 0% 63%); --fg-3:hsl(0 0% 56%);
  --line:hsl(0 0% 18%); --line-2:hsl(0 0% 22%);
  --solid:hsl(0 0% 93%); --on-solid:hsl(0 0% 4%);
  --amber:hsl(38 92% 58%);
  color-scheme:dark;
}}
*{box-sizing:border-box}
html,body{height:100%}
body{
  margin:0;background:var(--bg);color:var(--fg);
  font-family:"Geist","Geist Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,
    "Helvetica Neue",Arial,sans-serif;
  font-size:15px;line-height:1.6;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:720px;margin:0 auto;padding:20px 24px 32px;min-height:100%;
  display:flex;flex-direction:column}

/* header -------------------------------------------------------------------- */
.top{display:flex;align-items:center;gap:12px;padding-bottom:16px}
.top h1{font-size:15px;font-weight:500;margin:0;letter-spacing:-.01em}
.notice{display:flex;align-items:center;gap:7px;margin-left:auto;font-size:12px;
  color:var(--fg-3);letter-spacing:-.005em}
.notice::before{content:"";width:5px;height:5px;border-radius:50%;
  background:var(--amber);flex:none}
.rule{height:1px;background:var(--line);margin-bottom:28px}

/* opening ------------------------------------------------------------------- */
.opening{flex:1;display:flex;flex-direction:column;justify-content:center;
  padding-bottom:14vh}
.opening h2{font-size:38px;font-weight:400;letter-spacing:-.045em;line-height:1.05;
  margin:0 0 12px}
.opening p{color:var(--fg-2);margin:0 0 28px;max-width:34em;font-size:15px}

/* thread -------------------------------------------------------------------- */
.thread{flex:1;display:flex;flex-direction:column;gap:26px;margin-bottom:28px}
.asked{align-self:flex-end;max-width:82%;background:var(--panel);
  border:1px solid var(--line);border-radius:10px;padding:9px 13px;
  white-space:pre-wrap;font-size:14.5px;color:var(--fg-2)}
.reply .prose{font-size:15px}
.prose>*:first-child{margin-top:0}
.prose>*:last-child{margin-bottom:0}
.prose p{margin:0 0 13px}
.prose h3,.prose h4,.prose h5,.prose h6{font-size:15px;font-weight:600;
  letter-spacing:-.012em;margin:20px 0 9px}
.prose ul,.prose ol{margin:0 0 13px;padding-left:20px}
.prose li{margin:0 0 5px}
.prose li::marker{color:var(--fg-3)}
.prose strong{font-weight:600}
.prose code{font-family:"Geist Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
  font-size:.86em;background:var(--subtle);padding:1.5px 5px;border-radius:4px}
.prose hr{border:0;border-top:1px solid var(--line);margin:18px 0}
.flag{font-size:13px;color:var(--fg-2);background:var(--subtle);
  border-radius:8px;padding:9px 12px;margin-bottom:10px}

/* the original answer, opening in place ------------------------------------- */
details.original{margin-top:10px}
details.original>summary{display:inline-flex;align-items:center;gap:6px;cursor:pointer;
  font-size:12.5px;color:var(--fg-3);border:1px solid var(--line);border-radius:6px;
  padding:3px 9px;list-style:none;user-select:none;transition:color .12s,border-color .12s}
details.original>summary::-webkit-details-marker{display:none}
details.original>summary::before{content:"";width:0;height:0;
  border-left:4px solid currentColor;border-top:3.5px solid transparent;
  border-bottom:3.5px solid transparent;transition:transform .12s}
details.original[open]>summary::before{transform:rotate(90deg)}
details.original>summary:hover,details.original[open]>summary{color:var(--fg-2);
  border-color:var(--line-2)}
.raw{margin-top:8px;background:var(--subtle);border-radius:8px;padding:12px 14px}
.raw .label{font-size:11px;letter-spacing:.02em;color:var(--fg-3);margin-bottom:6px}
.prose.small{font-size:13px;line-height:1.55;color:var(--fg-2)}
.prose.small p{margin:0 0 9px}
.prose.small h3,.prose.small h4,.prose.small h5,.prose.small h6{font-size:13px;
  margin:13px 0 6px}
.prose.small ul,.prose.small ol{margin:0 0 9px;padding-left:18px}
.prose.small li{margin:0 0 3px}
.prose.small hr{margin:12px 0}
.raw .changes{margin-top:10px;padding-top:9px;border-top:1px solid var(--line-2);
  font-size:12px;color:var(--fg-3)}
.raw .changes code{font-family:"Geist Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
  font-size:11.5px;color:var(--fg-2)}

/* composer ------------------------------------------------------------------ */
form.composer{position:sticky;bottom:0;background:var(--bg);padding:10px 0 0}
.box{display:flex;gap:8px;align-items:flex-end;border:1px solid var(--line);
  border-radius:12px;background:var(--panel);padding:8px 8px 8px 14px;
  transition:border-color .12s}
.box:focus-within{border-color:var(--fg-3)}
textarea{flex:1;border:0;background:transparent;color:var(--fg);font:inherit;
  font-size:15px;resize:none;outline:none;max-height:184px;min-height:26px;padding:4px 0}
textarea::placeholder{color:var(--fg-3)}
button{background:var(--solid);color:var(--on-solid);border:0;border-radius:6px;
  padding:7px 14px;font:inherit;font-size:13.5px;font-weight:500;cursor:pointer;
  white-space:nowrap;transition:opacity .12s}
button:hover{opacity:.85}
button:disabled{opacity:.4;cursor:default}
button.ghost{background:transparent;color:var(--fg-3);border:1px solid var(--line);
  font-weight:400;font-size:12.5px;padding:3px 9px}
button.ghost:hover{color:var(--fg-2);border-color:var(--line-2);opacity:1}
.hint{color:var(--fg-3);font-size:12px;margin:9px 2px 0;letter-spacing:-.005em}
@media(max-width:640px){.opening h2{font-size:30px}.wrap{padding:16px 16px 24px}}
"""


def markdown(text: str) -> str:
    """Render the small part of Markdown that models actually use.

    Models answer in Markdown whether or not they were asked to, and showing a literal
    "**On execution:**" in the thread makes a finished product look unfinished.

    The order here is the whole safety story: **everything is escaped first**, so by the
    time any formatting runs, the text cannot contain markup. Every tag emitted below is
    one this function wrote. Nothing from a model or a person can become an element.
    """
    safe = escape(text)
    out: list[str] = []
    bullets: list[str] = []
    numbers: list[str] = []

    def close_lists() -> None:
        nonlocal bullets, numbers
        if bullets:
            out.append("<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>")
            bullets = []
        if numbers:
            out.append("<ol>" + "".join(f"<li>{n}</li>" for n in numbers) + "</ol>")
            numbers = []

    def inline(chunk: str) -> str:
        chunk = re.sub(r"`([^`]+)`", r"<code>\1</code>", chunk)
        chunk = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", chunk)
        chunk = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", chunk)
        return chunk

    paragraph: list[str] = []

    def close_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            out.append("<p>" + inline(" ".join(paragraph)) + "</p>")
            paragraph = []

    for line in safe.split("\n"):
        stripped = line.strip()

        if not stripped:
            close_paragraph()
            close_lists()
            continue

        heading = re.match(r"(#{1,4})\s+(.*)", stripped)
        if heading:
            close_paragraph()
            close_lists()
            level = min(len(heading.group(1)) + 2, 6)
            out.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
            continue

        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            close_paragraph()
            close_lists()
            out.append("<hr>")
            continue

        bullet = re.match(r"[-*+]\s+(.*)", stripped)
        if bullet:
            close_paragraph()
            if numbers:
                close_lists()
            bullets.append(inline(bullet.group(1)))
            continue

        number = re.match(r"\d+[.)]\s+(.*)", stripped)
        if number:
            close_paragraph()
            if bullets:
                close_lists()
            numbers.append(inline(number.group(1)))
            continue

        close_lists()
        paragraph.append(stripped)

    close_paragraph()
    close_lists()
    return "".join(out)


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
        reply.append(f'<div class="prose">{markdown(turn.answer)}</div>')

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
            f'<div class="prose small">{markdown(turn.original_answer)}</div>'
            f"{_changes(turn)}</div></details>"
        )
    reply.append("</div>")
    parts.append("".join(reply))
    return "".join(parts)


# The only script on the page. Enter sends, Shift-Enter makes a new line, and the box
# grows with what is typed - the three things a person expects from a message box, none
# of which a plain <textarea> does by itself. The page still works without it: the form
# posts normally and the button always submits.
COMPOSER_JS = """
(function(){
  var f=document.querySelector('form.composer'); if(!f) return;
  var t=f.querySelector('textarea');
  function grow(){ t.style.height='auto'; t.style.height=Math.min(t.scrollHeight,180)+'px'; }
  t.addEventListener('input',grow); grow();
  t.addEventListener('keydown',function(e){
    if(e.key==='Enter' && !e.shiftKey && !e.isComposing){
      e.preventDefault();
      if(t.value.trim()) f.requestSubmit();
    }
  });
  f.addEventListener('submit',function(){
    var b=f.querySelector('button[type=submit]');
    if(b){ b.disabled=true; b.textContent='Sending...'; }
  });
  t.focus();
})();
"""


def _composer(*, opening: bool) -> str:
    label = "Start" if opening else "Send"
    return f"""<form class="composer" method="post" action="/">
  <div class="box">
    <textarea name="prompt" rows="1" autofocus
      placeholder="{escape(PLACEHOLDER) if opening else "Reply..."}"></textarea>
    <button type="submit">{label}</button>
  </div>
  <p class="hint">Enter to send. Nothing is saved.</p>
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

    banner_error = f'<div class="flag">{escape(error)}</div>' if error else ""
    reset = (
        '<form method="post" action="/new"><button type="submit" class="ghost">New</button></form>'
        if started
        else ""
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Neutral</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet"
  href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&family=Geist+Mono&display=swap">
<style>{CSS}</style></head><body><div class="wrap">
<div class="top">
  <h1>Neutral</h1>
  <div class="notice">{escape(BANNER)}</div>
  {reset}
</div>
<div class="rule"></div>
{banner_error}
{body}
</div><script>{COMPOSER_JS}</script></body></html>
"""
