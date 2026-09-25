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

import random
import re
from html import escape

from neutral.conversation import Conversation, Turn
from neutral.invariants import BANNER

PLACEHOLDER = "Ask anything!"

# The server cannot know the visitor's local time, so the greeting is chosen in the
# browser. A time-neutral one is rendered first, which is what someone with JavaScript
# disabled keeps, and the script below swaps it before paint - no flash of the wrong one.
ANYTIME_GREETINGS = (
    "Hello!",
    "Hi there!",
    "Hey!",
    "Welcome back!",
    "What's on your mind?",
    "Where shall we start?",
    "Ready when you are.",
)

GREETING_JS = """
(function(){
  var el=document.getElementById('greeting'); if(!el) return;
  var anytime=['Hello!','Hi there!','Hey!','Welcome back!',"What's on your mind?",
               'Where shall we start?','Ready when you are.'];
  var h=new Date().getHours(), timed;
  if(h>=5&&h<12) timed=['Good morning!','Morning!'];
  else if(h>=12&&h<17) timed=['Good afternoon!','Afternoon!'];
  else if(h>=17&&h<22) timed=['Good evening!','Evening!'];
  else timed=['Good night!','Still up?','Working late?'];
  var pool=anytime.concat(timed);
  var text=pool[Math.floor(Math.random()*pool.length)];

  var still=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if(still){ el.textContent=text; return; }

  el.textContent='';
  var caret=document.createElement('span'); caret.className='caret';
  el.appendChild(caret);
  var i=0;
  (function tick(){
    if(i>=text.length) return;
    caret.insertAdjacentText('beforebegin', text.charAt(i++));
    setTimeout(tick, 42 + Math.random()*38);
  })();
})();
"""

CSS = """
/* Values taken from vercel.com and its Geist design system, read off the live site
   rather than approximated: text hsl(0 0% 9%) on hsl(0 0% 98%), borders at 92% light and
   18% dark, headings at weight 400 with tight negative tracking, 6px radii, and almost no
   colour at all. The restraint is the point - nothing here is decorative. */
/* A deep, woody green - the reference is a panelled library, not a product page. The
   light is confined to a band near the top and the plane falls away quickly to something
   close to #001D00 at the foot. Ink is a warm parchment rather than white, because pure
   white on green reads clinical and the brief was bookish. */
:root{
  --panel:hsl(150 18% 13%);
  --subtle:hsl(152 18% 10%);
  --fg:hsl(44 16% 92%);
  --fg-2:hsl(140 9% 70%);
  --fg-3:hsl(140 8% 53%);
  --line:hsl(150 15% 22%);
  --line-2:hsl(150 15% 29%);
  --solid:hsl(44 16% 92%);
  --on-solid:hsl(152 30% 8%);
  --amber:hsl(38 76% 62%);
  --hold:hsl(4 62% 62%);
  /* The corner cut. One value so every octagon agrees. */
  --cut:6px;
  --glow-1:hsl(272 60% 62% / .10);
  --glow-2:hsl(272 60% 62% / .05);
  --plane-foot:hsl(157 50% 3.5%);
  color-scheme:dark;
}
/* Dark preference goes a shade further down the same axis rather than to a different
   palette - there is no light counterpart to design, because the design is dark. */
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){
  --panel:hsl(150 17% 10.5%);
  --subtle:hsl(152 16% 8%);
  --line:hsl(150 14% 19%);
  --line-2:hsl(150 14% 26%);
  --plane-foot:hsl(159 55% 2%);
}}
*{box-sizing:border-box}
html,body{height:100%}
body{
  margin:0;color:var(--fg);
  background:linear-gradient(
    180deg,
    hsl(143 22% 33%) 0%,
    hsl(146 25% 26%) 11%,
    hsl(149 30% 18%) 27%,
    hsl(152 36% 11.5%) 47%,
    hsl(155 43% 7%) 73%,
    var(--plane-foot) 100%);
  background-attachment:fixed;
  font-family:"Geist","Geist Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,
    "Helvetica Neue",Arial,sans-serif;
  font-size:15px;line-height:1.6;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:720px;margin:0 auto;padding:20px 24px 32px;min-height:100%;
  display:flex;flex-direction:column}

/* Octagonal corners: a 45-degree cut instead of a radius. A clipped element cannot
   also carry a border, so the shape is drawn twice - an outer one filled with the line
   colour, and an inner one inset by a pixel filled with the surface. The glow sits on a
   wrapper outside both, because drop-shadow follows a clipped silhouette where
   box-shadow would square it off. */
.oct{
  clip-path:polygon(
    var(--cut) 0, calc(100% - var(--cut)) 0,
    100% var(--cut), 100% calc(100% - var(--cut)),
    calc(100% - var(--cut)) 100%, var(--cut) 100%,
    0 calc(100% - var(--cut)), 0 var(--cut));
}
.edge{background:var(--line);padding:1px}
.glow{filter:drop-shadow(0 0 4px var(--glow-1)) drop-shadow(0 0 16px var(--glow-2));
  transition:filter .18s}
.glow:focus-within{filter:drop-shadow(0 0 5px var(--glow-1))
  drop-shadow(0 0 20px var(--glow-2))}

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
.asked-wrap{align-self:flex-end;max-width:82%}
.asked{background:var(--panel);padding:10px 14px;white-space:pre-wrap;
  font-size:14.5px;color:var(--fg-2)}
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
  padding:10px 13px;margin-bottom:10px}

/* the original answer, opening in place ------------------------------------- */
details.original{margin-top:10px}
details.original>summary{display:inline-flex;align-items:center;gap:6px;cursor:pointer;
  font-size:12.5px;color:var(--fg-3);border:1px solid var(--line);
  clip-path:polygon(4px 0,calc(100% - 4px) 0,100% 4px,100% calc(100% - 4px),
    calc(100% - 4px) 100%,4px 100%,0 calc(100% - 4px),0 4px);
  padding:4px 11px;list-style:none;user-select:none;transition:color .12s,border-color .12s}
details.original>summary::-webkit-details-marker{display:none}
details.original>summary::before{content:"";width:0;height:0;
  border-left:4px solid currentColor;border-top:3.5px solid transparent;
  border-bottom:3.5px solid transparent;transition:transform .12s}
details.original[open]>summary::before{transform:rotate(90deg)}
details.original>summary:hover,details.original[open]>summary{color:var(--fg-2);
  border-color:var(--line-2)}
.raw{margin-top:8px;background:var(--subtle);padding:13px 15px}
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

/* the caret that types out the greeting, then rests blinking at the end */
.caret{display:inline-block;width:2px;height:.78em;background:currentColor;
  margin-left:3px;vertical-align:baseline;transform:translateY(1px);
  animation:caret 1.05s step-end infinite}
@keyframes caret{50%{opacity:0}}

/* the model is composing */
.typing-wrap{display:inline-block}
.typing{display:inline-flex;gap:5px;align-items:center;background:var(--panel);
  padding:13px 15px}
.typing i{width:6px;height:6px;border-radius:50%;background:var(--fg-3);
  animation:think 1.3s infinite both}
.typing i:nth-child(2){animation-delay:.16s}
.typing i:nth-child(3){animation-delay:.32s}
@keyframes think{
  0%,72%,100%{opacity:.22;transform:translateY(0)}
  36%{opacity:.85;transform:translateY(-3px)}}
@media(prefers-reduced-motion:reduce){
  .caret,.typing i{animation:none}
  .caret{opacity:1}}

/* composer ------------------------------------------------------------------ */
form.composer{position:sticky;bottom:0;padding:12px 0 0}
form.composer.sticky::before{content:"";position:absolute;inset:-26px 0 auto 0;height:26px;
  background:linear-gradient(to bottom, transparent, var(--plane-foot));
  pointer-events:none}

.box{display:flex;gap:8px;align-items:flex-end;background:var(--panel);
  padding:9px 9px 9px 15px}
textarea{flex:1;border:0;background:transparent;color:var(--fg);font:inherit;
  font-size:15px;resize:none;outline:none;max-height:184px;min-height:40px;padding:8px 0}
textarea::placeholder{color:var(--fg-3)}
button{background:var(--solid);color:var(--on-solid);border:0;
  clip-path:polygon(4px 0,calc(100% - 4px) 0,100% 4px,100% calc(100% - 4px),
    calc(100% - 4px) 100%,4px 100%,0 calc(100% - 4px),0 4px);
  padding:9px 17px;font:inherit;font-size:13.5px;font-weight:500;cursor:pointer;
  white-space:nowrap;transition:opacity .12s}
button:hover{opacity:.85}
button:disabled{opacity:.4;cursor:default}
button.ghost{background:transparent;color:var(--fg-3);border:1px solid var(--line);
  font-weight:400;font-size:12.5px;padding:3px 9px}
button.ghost:hover{color:var(--fg-2);border-color:var(--line-2);opacity:1}
.hint{color:var(--fg-3);font-size:12px;margin:9px 2px 0;letter-spacing:-.005em}
.foot{margin-top:28px;padding-top:16px;border-top:1px solid var(--line);
  display:flex;gap:16px;font-size:12px;color:var(--fg-3)}
.foot a{color:var(--fg-3);text-decoration:none}
.foot a:hover{color:var(--fg-2)}
.legal{max-width:640px}
.legal h2{font-size:28px;font-weight:400;letter-spacing:-.035em;margin:0 0 20px}
.legal .prose h3{margin-top:26px}
.back{display:inline-block;margin-bottom:22px;font-size:13px;color:var(--fg-3);
  text-decoration:none}
.back:hover{color:var(--fg-2)}
.fillin{background:hsl(38 76% 62% / .16);border-bottom:1.5px solid var(--amber);
  padding:0 3px;border-radius:2px;font-weight:500}
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
    return f'<div class="oct flag{stop}">{escape(turn.note)}</div>'


def _changes(turn: Turn) -> str:
    if not turn.changes:
        return ""
    items = ", ".join(
        f"<code>{escape(c.detected)}</code> &rarr; <code>{escape(c.replacement)}</code>"
        for c in turn.changes
    )
    return f'<div class="changes">Removed before sending: {items}</div>'


def _turn(turn: Turn) -> str:
    parts = [
        f'<div class="asked-wrap oct edge"><div class="oct asked">{escape(turn.asked)}</div></div>'
    ]

    reply = [f'<div class="reply">{_flag(turn)}']
    if turn.answer:
        reply.append(f'<div class="prose">{markdown(turn.answer)}</div>')

    if turn.failed and turn.changes:
        reply.append(
            '<details class="original" open><summary>What Neutral would have removed'
            '</summary><div class="oct raw"><div class="label">Computed locally, nothing '
            f"was sent</div>{_changes(turn)}</div></details>"
        )

    # The same reply, before names were put back. No second call; this is what the model
    # actually wrote, which is the honest thing to show under "what did Neutral do".
    if turn.neutral_answer and not turn.untouched:
        reply.append(
            '<details class="original">'
            "<summary>Before names were put back</summary>"
            '<div class="oct raw"><div class="label">What the model wrote, with the '
            "identity still removed</div>"
            f'<div class="prose small">{markdown(turn.neutral_answer)}</div>'
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
  var btn=f.querySelector('button[type=submit]');

  // Deliberately not called on load. At that point the layout has not settled and
  // scrollHeight comes back as 180 on an empty box, which then sticks - the natural
  // height from CSS is 32px and correct. Growth only matters once someone types.
  function grow(){ t.style.height='0px';
    t.style.height=Math.max(40,Math.min(t.scrollHeight,184))+'px'; }
  t.addEventListener('input',grow);

  function oct(cls, inner){
    var wrap=document.createElement('div'); wrap.className='oct edge '+cls;
    var box=document.createElement('div'); box.className='oct '+inner;
    wrap.appendChild(box); return wrap;
  }

  // The thread is created on the first message rather than waiting for a reply, so the
  // page never sits on the opening screen while a request is in flight.
  function enterThread(){
    var thread=document.querySelector('.thread');
    if(thread) return thread;
    var opening=document.querySelector('.opening');
    thread=document.createElement('div'); thread.className='thread';
    if(opening){
      opening.parentNode.insertBefore(thread, opening);
      opening.parentNode.insertBefore(f, opening);
      opening.remove();
      f.classList.add('sticky');
      t.placeholder='Reply...';
      if(btn) btn.textContent='Send';
    }
    return thread;
  }

  function showAsked(thread, text){
    var wrap=oct('asked-wrap','asked');
    wrap.firstChild.textContent=text;
    thread.appendChild(wrap);
  }

  function showTyping(thread){
    var reply=document.createElement('div'); reply.className='reply';
    var wrap=oct('typing-wrap','typing');
    for(var i=0;i<3;i++) wrap.firstChild.appendChild(document.createElement('i'));
    reply.appendChild(wrap); thread.appendChild(reply);
    return reply;
  }

  function toBottom(){ window.scrollTo({top:document.body.scrollHeight,behavior:'smooth'}); }

  f.addEventListener('submit', function(e){
    var text=t.value.trim(); if(!text) { e.preventDefault(); return; }
    if(!window.fetch || !window.DOMParser) return;   // no script, normal form post
    e.preventDefault();

    var thread=enterThread();
    showAsked(thread, text);
    var pending=showTyping(thread);
    t.value=''; grow(); if(btn) btn.disabled=true;
    toBottom();

    var body=new FormData(); body.append('prompt', text);
    fetch('/', {method:'POST', body:body, headers:{'X-Requested-With':'fetch'}})
      .then(function(r){ return r.text(); })
      .then(function(html){
        var doc=new DOMParser().parseFromString(html,'text/html');
        var fresh=doc.querySelector('.thread');
        if(fresh) thread.innerHTML=fresh.innerHTML; else pending.remove();
        var top=doc.querySelector('.top');
        if(top) document.querySelector('.top').innerHTML=top.innerHTML;
      })
      .catch(function(){
        pending.innerHTML='<div class="oct flag stop">That did not reach the model. '+
          'Check your connection and try again.</div>';
      })
      .finally(function(){ if(btn) btn.disabled=false; t.focus(); toBottom(); });
  });

  t.addEventListener('keydown',function(e){
    if(e.key==='Enter' && !e.shiftKey && !e.isComposing){
      e.preventDefault();
      if(t.value.trim()) f.requestSubmit();
    }
  });
  t.focus();
})();
"""


def _composer(*, opening: bool) -> str:
    label = "Start" if opening else "Send"
    return f"""<form class="composer{"" if opening else " sticky"}" method="post" action="/">
  <div class="glow"><div class="oct edge"><div class="oct box">
    <textarea name="prompt" rows="1" autofocus
      placeholder="{escape(PLACEHOLDER) if opening else "Reply..."}"></textarea>
    <button type="submit">{label}</button>
  </div></div></div>
  <p class="hint">Enter to send. Nothing is saved.</p>
</form>"""


def page(conversation: Conversation | None = None, *, error: str = "") -> str:
    started = conversation is not None and conversation.started

    if started:
        thread = "".join(_turn(t) for t in conversation.turns)
        body = f'<div class="thread">{thread}</div>{_composer(opening=False)}'
    else:
        greeting = escape(random.choice(ANYTIME_GREETINGS))
        body = f"""<div class="opening">
  <h2 id="greeting">{greeting}</h2>
  <p>Neutral removes signals that can introduce bias or indicate your identity
  before your prompt reaches the model.</p>
  {_composer(opening=True)}
</div>\n<script>{GREETING_JS}</script>"""

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
<div class="foot">
  <a href="/terms">Terms</a><a href="/privacy">Privacy</a>
  <span style="margin-left:auto">Phase 1 &mdash; names and bound pronouns only</span>
</div>
</div><script>{COMPOSER_JS}</script></body></html>
"""


FILL_IN_NOTE = (
    "This page is not finished. Every highlighted item must be replaced before anyone "
    "outside the project can reach this site."
)


def legal_page(title: str, body: str) -> str:
    """Render a terms or privacy page.

    Unfilled placeholders are highlighted rather than left as plain text, because a
    terms page that quietly ships saying "FILL_IN" is worse than not having one.
    """
    rendered = markdown(body)
    unfilled = "[[" in rendered
    rendered = re.sub(
        r"\[\[(.+?)\]\]",
        lambda m: f'<span class="fillin">FILL IN &mdash; {m.group(1).strip()}</span>',
        rendered,
    )
    warning = f'<div class="flag">{escape(FILL_IN_NOTE)}</div>' if unfilled else ""

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} &mdash; Neutral</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet"
  href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&family=Geist+Mono&display=swap">
<style>{CSS}</style></head><body><div class="wrap legal">
<div class="top">
  <h1>Neutral</h1>
  <div class="notice">{escape(BANNER)}</div>
</div>
<div class="rule"></div>
<a class="back" href="/">&larr; Back</a>
{warning}
<h2>{escape(title)}</h2>
<div class="prose">{rendered}</div>
<div class="foot"><a href="/terms">Terms</a><a href="/privacy">Privacy</a></div>
</div></body></html>
"""
