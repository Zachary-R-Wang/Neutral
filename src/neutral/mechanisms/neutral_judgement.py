"""Mechanism 3, continued: a request for a verdict, asked without one built in.

"I think my code is really clean and efficient. Can you confirm?" asks the model to agree.
Take out "I think" and it still does: the owner ("my"), the intensifier ("really") and the
verdict ("clean and efficient", as a yes/no) are all still there. The founder, 2026-09-28:
"Something like 'Evaluate the efficiency of the code' would obviously work a trillion
times better." It does, and this module is that.

A request for a judgement becomes an instruction to assess, with:
  no owner         "my code" -> "the code"
  no intensifier   "really", "very", "so" go
  no polarity      the claimed verdict becomes what to assess: "clean and efficient" ->
                   "the cleanliness and efficiency"; "better" -> "better or worse"
  no yes/no        "Is my argument valid?" -> "Evaluate the validity of the argument."

The thing being judged is never touched: only the words around it are replaced, so a
quoted name or a block of code passes through exactly. The words that replace them -
"Evaluate", "the cleanliness of" - say nothing about anybody (S1).
"""

from __future__ import annotations

import re

from neutral.core import Span
from neutral.mechanisms.self_presentation import Edit

KIND = "neutral_judgement"
REASON = (
    "a request for a verdict, asked without the verdict, the owner or the intensity the "
    "person asking brought to it"
)

# The verdict someone hopes for, turned into the quality to assess. None means the word is
# pure praise with nothing to measure: "Evaluate the code" says all of it.
DIMENSIONS = {
    "clean": "cleanliness",
    "efficient": "efficiency",
    "fast": "speed",
    "readable": "readability",
    "maintainable": "maintainability",
    "secure": "security",
    "scalable": "scalability",
    "correct": "correctness",
    "right": "correctness",
    "valid": "validity",
    "sound": "soundness",
    "fair": "fairness",
    "funny": "humour",
    "catchy": "catchiness",
    "original": "originality",
    "realistic": "feasibility",
    "feasible": "feasibility",
    "reasonable": "reasonableness",
    "clear": "clarity",
    "persuasive": "persuasiveness",
    "convincing": "persuasiveness",
    "professional": "professionalism",
    "memorable": "memorability",
    "profitable": "profitability",
    "accurate": "accuracy",
    "ready": "readiness",
    "appropriate": "appropriateness",
    "strong": None,
    "good": None,
    "great": None,
    "brilliant": None,
    "perfect": None,
    "amazing": None,
    "excellent": None,
    "solid": None,
    "nice": None,
    "impressive": None,
    "smart": None,
    "clever": None,
    "fine": None,
    "ok": None,
    "okay": None,
    "the best": None,
    "any good": None,
}
_INTENSIFIERS = (
    r"(?:(?:really|very|super|so|extremely|quite|pretty|incredibly|totally|absolutely|truly|"
    r"honestly|genuinely|actually)\s+)*"
)
_ADJ = "|".join(sorted((re.escape(k) for k in DIMENSIONS), key=len, reverse=True))
# "really clean and efficient", "clean, fast and readable"
_VERDICT = rf"{_INTENSIFIERS}(?:{_ADJ})(?:\s*(?:,|,?\s+and)\s+{_INTENSIFIERS}(?:{_ADJ}))*"
_CONFIRM = (
    r"(?:can you confirm|could you confirm|just confirm|confirm|right|agree|do you agree|"
    r"am i right|correct|yes or no|(?:do|does|is|are|will|would|can)\s+"
    r"(?:they|it|he|she|that|this|those|these))\??"
)
_CAUSAL = (
    r"kill|kills|hurt|hurts|harm|harms|help|helps|improve|improves|boost|boosts|reduce|"
    r"reduces|increase|increases|raise|raises|lower|lowers|cause|causes|destroy|destroys|"
    r"create|creates|damage|damages|benefit|benefits"
)
# What people ask to have judged. "my" in front of one of these becomes "the".
ARTIFACTS = (
    r"code|function|script|query|pr|pull request|essay|poem|story|short story|novel|"
    r"chapter|draft|thesis|paper|article|post|tweet|caption|bio|resume|cv|cover letter|"
    r"letter|email|pitch|pitch deck|deck|plan|business plan|idea|startup idea|startup|"
    r"business|business name|name|logo|design|app|website|product|proposal|grant proposal|"
    r"abstract|argument|answer|presentation|presentation outline|outline|report|lab report|"
    r"song|chorus|lyrics|joke|listing|apartment listing|profile|dating profile|photo|"
    r"painting|drawing|portfolio|slide|slides|speech|toast|haiku|solution|approach|strategy"
)
# Whoever it belongs to: "my code", and equally "a colleague's cover letter", so that the
# two halves of a matched pair become the same prompt.
_OWNED = re.compile(
    r"\b(?:(?:my|our)|(?:a|my|our|his|her|their)\s+(?:colleague|coworker|co-worker|friend|"
    r"classmate|teammate|peer|employee|report|manager|boss|client|partner)'s)\s+"
    rf"(?=(?:[\w-]+\s+){{0,2}}(?:{ARTIFACTS})\b)",
    re.I,
)
_MADE_BY_ME = re.compile(
    rf"\b(?:{ARTIFACTS})(\s+(?:that\s+)?i(?:'ve|\s+have)?\s+(?:just\s+)?"
    r"(?:wrote|written|made|created|designed|built|drew|drawn|composed|painted|coded)\b)",
    re.I,
)


_MINE_OR_THEIRS = re.compile(
    r"\b(?:my|our)\s+([\w-]+)\s+or\s+(?:my|our|his|her|their|a|the)\s+[\w-]+'s\b", re.I
)


def _dimensions(verdict: str) -> list[str]:
    words = re.sub(_INTENSIFIERS, "", verdict.lower())
    out: list[str] = []
    for part in re.split(r"\s*(?:,|\band\b)\s*", words):
        part = part.strip()
        dim = DIMENSIONS.get(part)
        if dim and dim not in out:
            out.append(dim)
    return out


def _of(dims: list[str]) -> str:
    """ "the cleanliness and efficiency of " - or "" when the verdict was pure praise."""
    if not dims:
        return ""
    joined = dims[0] if len(dims) == 1 else ", ".join(dims[:-1]) + " and " + dims[-1]
    return f"the {joined} of "


def _owner_free(prompt: str, span: Span) -> tuple[Span, str]:
    """If the object opens with "my"/"our", the opening goes into the framing as "the"."""
    m = re.match(r"(?i)(?:my|our)\s+", prompt[span.start : span.end])
    if m:
        return Span(span.start + m.end(), span.end), "the "
    return span, ""


def _sentences(prompt: str) -> list[Span]:
    spans, start = [], 0
    for m in re.finditer(r"[.!?]+(?=\s|$)|\n{2,}", prompt):
        if prompt[start : m.end()].strip():
            lead = len(prompt[start : m.end()]) - len(prompt[start : m.end()].lstrip())
            spans.append(Span(start + lead, m.end()))
        start = m.end()
    if prompt[start:].strip():
        lead = len(prompt[start:]) - len(prompt[start:].lstrip())
        spans.append(Span(start + lead, len(prompt.rstrip())))
    return spans


def _frame(prompt: str, head: int, words: str, obj: Span, tail: int, end: str) -> list[Edit]:
    """Replace what is before and after the object; the object itself stays original."""
    obj, owner = _owner_free(prompt, obj)
    capital = not prompt[:head].strip() or re.search(r"[.!?]\s*$", prompt[:head])
    words = words[:1].upper() + words[1:] if capital else words[:1].lower() + words[1:]
    return [
        Edit(Span(head, obj.start), words + owner, KIND, prompt[head : obj.start]),
        Edit(Span(obj.end, tail), end, KIND, prompt[obj.end : tail]),
    ]


def find(prompt: str, protected: list[Span]) -> list[Edit]:
    """Edits that turn each request for a verdict in the prompt into one without it."""

    def in_work(pos: int) -> bool:
        return any(w.start <= pos < w.end for w in protected)

    edits: list[Edit] = []
    sentences = _sentences(prompt)
    used: set[int] = set()
    for i, s in enumerate(sentences):
        if i in used or in_work(s.start):
            continue
        text = prompt[s.start : s.end]
        nxt = sentences[i + 1] if i + 1 < len(sentences) else None
        nxt_text = prompt[nxt.start : nxt.end] if nxt else ""
        # Leading words that ask for candour stay: "Be honest, is this chorus catchy?"
        lead = re.match(
            r"(?i)(?:please\s+)?(?:be\s+(?:\w+\s+)?(?:honest|brutal|blunt|frank)|honestly|"
            r"seriously|frankly)[,:.]?\s+",
            text,
        )
        at = s.start + (lead.end() if lead else 0)
        body = prompt[at : s.end]

        # 1. "I think X is really clean and efficient. Can you confirm?"
        m = re.match(
            rf"(?i)(?:(?:honestly|personally),?\s+)?i\s+(?:really\s+|honestly\s+|truly\s+)?"
            rf"(?:think|believe|feel)(?:\s+that)?\s+(.+?)\s+(?:is|are|looks|seems)\s+({_VERDICT})[.!]?$",
            body,
        )
        if m and nxt and re.fullmatch(rf"(?i){_CONFIRM}", nxt_text.strip()):
            obj = Span(at + m.start(1), at + m.end(1))
            words = f"Evaluate {_of(_dimensions(m.group(2)))}"
            edits += _frame(prompt, at, words, obj, nxt.end, ".")
            used.add(i + 1)
            continue

        # 2. "I think minimum wage increases kill jobs. Do they?"
        m = re.match(
            rf"(?i)(?:.*?\band\s+)?i\s+(?:really\s+)?(?:think|believe|feel)(?:\s+that)?\s+"
            rf"(.+)\s+(?:{_CAUSAL})\s+(.+?)[.!]?$",
            body,
        )
        if m and nxt and re.fullmatch(rf"(?i){_CONFIRM}", nxt_text.strip()):
            start = at + m.start(0)
            subj = Span(at + m.start(1), at + m.end(1))
            obj = Span(at + m.start(2), at + m.end(2))
            capital = not prompt[:start].strip() or re.search(r"[.!?]\s*$", prompt[:start])
            edits += [
                Edit(
                    Span(start, subj.start),
                    ("E" if capital else "e") + "valuate the effect of ",
                    KIND,
                    prompt[start : subj.start],
                ),
                Edit(Span(subj.end, obj.start), " on ", KIND, prompt[subj.end : obj.start]),
                Edit(Span(obj.end, nxt.end), ".", KIND, prompt[obj.end : nxt.end]),
            ]
            used.add(i + 1)
            continue

        # 3. "Don't you think remote work is better for productivity?"
        m = re.match(
            rf"(?i)(?:don't|doesn't|wouldn't|isn't|aren't)\s+(?:you|it|this|that)\s+"
            rf"(?:think|agree|feel)(?:\s+that)?\s+(.+?)\s+(is|are)\s+(?:{_INTENSIFIERS})"
            rf"(better|worse|({_ADJ}))(.*?)\?$",
            body,
        )
        if m:
            obj = Span(at + m.start(1), at + m.end(1))
            rest = m.group(5)
            if m.group(3).lower() in ("better", "worse"):
                edits += _frame(
                    prompt,
                    at,
                    "Evaluate whether ",
                    obj,
                    s.end,
                    f" {m.group(2)} better or worse{rest}.",
                )
            else:
                dims = _dimensions(m.group(3))
                edits += _frame(prompt, at, f"Evaluate {_of(dims)}", obj, s.end, f"{rest}.")
            continue

        # 4. "Is my argument valid?", "Is this chorus catchy?", "Is it good enough for X?"
        m = re.match(
            rf"(?i)(?:is|are)\s+((?:my|our|the|this|that|these|those|it)\b(?:\s+[\w'&-]+){{0,4}}?)"
            rf"\s+({_VERDICT})(\s+enough)?((?:\s+(?:for|as|to)\s+[^?]+)?)\?$",
            body,
        )
        if m and not (
            m.group(1).lower() in ("this", "that", "these", "those")
            and not _dimensions(m.group(2))
            and not m.group(3)
        ):
            # ("Is that ok?" has nothing to assess and no object to name: left as asked.)
            obj = Span(at + m.start(1), at + m.end(1))
            dims = _dimensions(m.group(2))
            rest = m.group(4)
            if m.group(3):  # "good enough for a literary magazine"
                dims, rest = ["suitability"], rest
            if prompt[obj.start : obj.end].lower() == "it":
                framing = "Evaluate its " + (" and ".join(dims) if dims else "quality")
                edits += [
                    Edit(Span(at, obj.end), framing, KIND, prompt[at : obj.end]),
                    Edit(Span(obj.end, s.end), f"{rest}.", KIND, prompt[obj.end : s.end]),
                ]
            else:
                edits += _frame(prompt, at, f"Evaluate {_of(dims)}", obj, s.end, f"{rest}.")
            continue

        # 5. "Is this a good opening line for my dating profile?" / "Is this a good idea?"
        m = re.match(
            rf"(?i)is\s+(this|that|it)\s+an?\s+{_INTENSIFIERS}(?:{_ADJ})\s+([\w\s'-]+?)\?$", body
        )
        if m:
            obj = Span(at + m.start(2), at + m.end(2))
            edits += _frame(prompt, at, f"Evaluate {m.group(1).lower()} ", obj, s.end, ".")
            continue

        # 6. "Tell me honestly if my business name 'Glow & Grind' is good."
        m = re.match(
            rf"(?i)(?:tell\s+me|let\s+me\s+know)\s+(?:honestly\s+)?(?:if|whether)\s+(.+?)\s+"
            rf"(?:is|are)\s+({_VERDICT})[.!?]?$",
            body,
        )
        if m:
            obj = Span(at + m.start(1), at + m.end(1))
            dims = _dimensions(m.group(2))
            edits += _frame(prompt, at, f"Evaluate {_of(dims)}", obj, s.end, ".")
            continue

        # 7. "What do you think of my plan to learn Spanish in 3 months?"
        m = re.match(r"(?i)what\s+do\s+you\s+think\s+(?:of|about)\s+(.+?)\?$", body)
        if m:
            obj = Span(at + m.start(1), at + m.end(1))
            edits += _frame(prompt, at, "Evaluate ", obj, s.end, ".")
            continue

    return sorted(edits, key=lambda e: e.span.start)


def unowned(prompt: str, protected: list[Span], taken: list[Span]) -> list[Edit]:
    """Anywhere else in a request for a verdict, nobody owns the thing being judged:
    "my code" -> "the code", "a poem I wrote" -> "a poem". Applied last, around whatever
    the other edits have already taken."""

    def in_work(pos: int) -> bool:
        return any(w.start <= pos < w.end for w in protected)

    edits: list[Edit] = []
    # "my design or my coworker's": whose is whose, gone from both.
    for m in _MINE_OR_THEIRS.finditer(prompt):
        span = Span(m.start(), m.end())
        if in_work(span.start) or any(span.start < t.end and span.end > t.start for t in taken):
            continue
        edits.append(Edit(span, f"the first {m.group(1)} or the second", KIND, m.group(0)))
        taken = [*taken, span]
    for m in _OWNED.finditer(prompt):
        span = Span(m.start(), m.end())
        if in_work(span.start) or any(span.start < t.end and span.end > t.start for t in taken):
            continue
        word = m.group(0)
        edits.append(Edit(span, ("The " if word[0].isupper() else "the "), KIND, word))
    for m in _MADE_BY_ME.finditer(prompt):
        span = Span(m.start(1), m.end(1))
        if not in_work(span.start) and not any(
            span.start < t.end and span.end > t.start for t in taken
        ):
            edits.append(Edit(span, "", KIND, m.group(1).strip()))
    return sorted(edits, key=lambda e: e.span.start)
