"""Mechanism 3, continued: what the person asking says about themselves and their stake.

"I spent three weeks on it and I think it's the best thing I've written." "I'm a
published author." "My mom says it's perfect." "I've already quit my job to do this."
None of it is information about the thing being judged. All of it tells the model what
the person hopes to hear - the trigger for the favourable treatment CLAUDE.md §1 calls
sycophancy. The broad test set, written 2026-09-28, had 32 such passages; Neutral removed
none of them.

This module finds them. They are only taken out when the request asks for a judgement
(policy: gate.evaluative), because that is where they bend the verdict; in "I'm nervous
about my talk - how do I calm down?" the nerves are the question and stay.

What is found, and what happens to it:
  emotion       "I'm really excited about it", "please be gentle, it means a lot"  removed
  effort        "I spent three weeks on it", "I've put my life savings into it"     removed
  stance        "I think it's the best thing I've written", "I'm pretty sure"      removed
  credential    "I'm a published author", "I've won three grants, so I know"       removed
  social proof  "my mom says it's perfect", "several agents told me it's brilliant" removed
  ideology      "I'm a proud conservative"                                         removed
  ownership     "the second one is mine", "Logo A was designed by me"             removed
  decision      "I've decided to cut the budget"      -> "The plan is to cut the budget"
  leaning       "I'm leaning toward staying in Denver" -> "Another option is staying in Denver"
  someone's advice "My girlfriend thinks I should take the job" -> "One option is to take the job"
  leading question "Don't you think X?"                -> "Evaluate whether X."
  claim + confirm  "I think X. Can you confirm?"       -> "Evaluate whether X."

The last five are restructured rather than removed, because they carry the thing being
judged. The words that frame them ("The plan is", "One option is", "Evaluate whether")
state nothing about anybody; everything else comes from the original, in order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from neutral.core import Span

NAME = "person_neutralisation"

EMOTION, EFFORT, STANCE, CREDENTIAL, SOCIAL, IDEOLOGY, OWNERSHIP = (
    "emotion",
    "effort",
    "stance",
    "credential",
    "social_proof",
    "ideology",
    "ownership",
)
RESTRUCTURED = "restructured"
LEARNED = "learned"

# A trained detector, consulted for a clause the rules have no word for. None until one is
# configured (see neutral/learned.py); the rules decide alone without it.
DETECTOR = None

REASONS = {
    EMOTION: "how the person asking feels about it invites a kinder verdict",
    EFFORT: "how much the person asking has invested invites a kinder verdict",
    STANCE: "the person asking's own verdict anchors the model's",
    CREDENTIAL: "the person asking's standing invites deference",
    SOCIAL: "what others have said anchors the model's verdict",
    IDEOLOGY: "the person asking's politics invites an answer tailored to them",
    OWNERSHIP: "which one belongs to the person asking invites favouritism",
    RESTRUCTURED: "the same content, no longer framed as the person asking's own view",
    LEARNED: "a trained detector judged this to be about the person asking, not the task",
}

_ADV = (
    r"(?:(?:so|really|very|super|quite|pretty|fairly|a bit|a little|kind of|extremely|"
    r"honestly|truly|absolutely|already|just|also)\s+)*"
)

# Each clause is tested against these, lower-cased, with any leading "and"/"but"/"so"
# already stripped. Order matters: the first kind that matches is the one recorded.
_CLAUSES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        IDEOLOGY,
        re.compile(
            rf"^(?:i'm|i am)\s+(?:a\s+|an\s+)?{_ADV}(?:proud\s+|lifelong\s+|committed\s+|"
            r"staunch\s+|die-hard\s+)?(?:conservative|liberal|progressive|republican|democrat|"
            r"socialist|libertarian|leftist|right-winger|centrist|feminist|marxist)\b"
        ),
    ),
    (
        EMOTION,
        re.compile(
            rf"^(?:(?:honestly|personally),?\s+)?(?:i'm|i am)\s+{_ADV}(?:excited|nervous|anxious|"
            r"worried|scared|terrified|proud|thrilled|passionate|invested|attached|stressed|"
            r"emotional|desperate|hopeful|obsessed|in love|dying)\b"
            r"|^(?:please\s+)?be\s+(?:gentle|kind|nice)\b"
            r"|^(?:it|this)\s+means\s+(?:a lot|so much|everything|the world)\s+to\s+me\b"
            rf"|^i\s+{_ADV}(?:love|adore)\s+(?:it|this|them|the\s+\w+)\b"
            r"|^i(?:'d|\s+would)\s+be\s+(?:devastated|crushed|heartbroken)\b"
        ),
    ),
    (
        EFFORT,
        re.compile(
            rf"^i(?:'ve|\s+have)?\s+{_ADV}(?:spent|worked|put|invested|poured|sunk|quit|"
            r"sacrificed|been working on)\b"
            r"|^it\s+took\s+me\b"
            r"|^i\s+wrote\s+(?:it|this)?\s*in\s+(?:\d+|a few|five|ten|two)\s+\w+"
        ),
    ),
    (
        CREDENTIAL,
        re.compile(
            rf"^(?:i'm|i am)\s+(?:a|an|the)\s+(?:[\w-]+\s+){{0,3}}(?:author|writer|novelist|"
            r"engineer|developer|comedian|landlord|ceo|cto|founder|professor|expert|graduate|"
            r"grad|director|producer|investor|consultant|scientist|analyst|chef|musician|"
            r"artist|professional|poet|journalist|editor|designer|critic)\b"
            rf"|^i(?:'ve|\s+have)\s+been\s+(?:a|an|the)\s+.{{0,40}}?\bfor\s+(?:\d+|\w+)\s+years\b"
            rf"|^i(?:'ve|\s+have)\s+{_ADV}(?:won|published|built|sold|founded|raised|shipped)\b"
            rf"|^(?:i'm|i am)\s+{_ADV}(?:smart|intelligent|talented|experienced|gifted|"
            r"a fast learner|junior|new to this|a beginner|an expert)\b"
            r"|^i\s+usually\s+get\s+(?:top marks|straight a's|a's|good grades|high marks)\b"
            r"|^i\s+(?:know|understand)\s+(?:what|the|how|my|this)\b"
        ),
    ),
    (
        STANCE,
        re.compile(
            rf"^(?:(?:honestly|personally),?\s+)?i\s+{_ADV}(?:think|believe|feel|reckon|"
            r"suspect)\b"
            rf"|^(?:i'm|i am)\s+{_ADV}(?:sure|confident|certain|positive|convinced)\b"
            r"|^in\s+my\s+(?:honest\s+)?opinion\b"
            r"|^(?:just\s+)?confirm\b|^can\s+you\s+(?:just\s+)?confirm\b"
        ),
    ),
    (
        SOCIAL,
        re.compile(
            r"^(?:all\s+)?(?:my|our|several|many|most|some|the)\s+(?:[\w-]+\s+){0,2}"
            r"(?:friends?|team|family|mom|mum|dad|mother|father|parents?|wife|husband|partner|"
            r"boyfriend|girlfriend|boss|manager|colleagues?|coworkers?|producer|agents?|"
            r"editors?|teachers?|professors?|investors?|customers?|users?|readers?|mentor)\b"
            r".*\b(?:say|says|said|told|think|thinks|thought|agree|agrees|agreed|love|loves|"
            r"loved|call|calls)\b"
            r"|^(?:everyone|everybody|people)\s+(?:say|says|tell|tells|think|thinks|love|loves)\b"
            r"|^i(?:'ve|\s+have)?\s+(?:been\s+|already\s+been\s+)?(?:told|assured|informed)\b"
        ),
    ),
)

# Evaluations inside a social-proof clause, so "my mom says hi" is not caught.
_VERDICT = re.compile(
    r"\b(?:great|perfect|brilliant|amazing|a hit|good|best|excellent|genius|fantastic|"
    r"incredible|yes|agree|agrees|love|loves|right|strong|ready)\b"
)
# What makes "I think ..." a verdict rather than a situation: "I think it's the best thing
# I've written" is the asker's verdict; "I think I'm going to be late" is the question.
_JUDGED = re.compile(
    r"\b(?:great|perfect|brilliant|amazing|good|better|best|worse|worst|excellent|genius|"
    r"fantastic|incredible|flawless|right|wrong|correct|strong|weak|ready|clean|cleaner|"
    r"efficient|valid|fair|unfair|funny|catchy|original|realistic|solid|impressive|"
    r"masterpiece|groundbreaking|a hit|the one|works|will work|nailed)\b"
)
_HEDGE = re.compile(r"^i\s+(?:\w+\s+)?(?:think|believe|feel|reckon|suspect)\b")
# ...and about the person themselves: "I think I'm going to be late", "I feel like my
# manager ignores me" is their situation, not a verdict on anything.
_ABOUT_ONESELF = re.compile(
    r"^i\s+(?:\w+\s+)?(?:think|believe|feel|reckon|suspect)(?:\s+(?:that|like))?\s+"
    r"(?:i|i'm|i've|i'd|i'll|me|my|we|we're|we've|our)\b"
)
_OWNERSHIP = re.compile(
    r"(?:^|\s)(?:the\s+(?:first|second|third|fourth|last|other)\s+(?:one\s+)?is\s+mine"
    r"(?:\s+and\s+the\s+\w+\s+(?:one\s+)?is\s+my\s+\w+'s)?"
    r"|(?:was|were)?\s*(?:designed|written|made|created|built|drawn)\s+by\s+(?:me|us)"
    r"(?:,\s*[\w ]+?\s+by\s+(?:a|an|the|my)\s+(?:big\s+|professional\s+|famous\s+)?"
    r"(?:agency|designer|professional|studio|firm|friend|colleague))?)",
    re.I,
)
# A clause that must stay whatever it says: it is where the person is applying, or
# what they are building - the credential is then part of the task.
_TASK_CONTEXT = re.compile(
    r"\b(?:applying|apply|application|interview\w*|switch\w*\s+into|move\w*\s+into|"
    r"building|launching|pitching|running|starting)\b"
)
_CONNECTIVE = re.compile(r"^(?:and|but|so|because|although|though|yet)\b\s*", re.I)
# Where a sentence splits into clauses: before "and"/"but"/"so" followed by a new subject,
# and at ", so" / ", but".
_SPLIT = re.compile(
    r",?\s+(?=(?:and|but|so|because)\s+(?:i\b|i'm|i've|i'd|my\b|all\s+my\b|several\b|"
    r"everyone\b|it\s+means\b|honestly\b))|,\s+(?=(?:so|but)\s)",
    re.I,
)
_CONFIRM = re.compile(
    r"^(?:can you confirm|could you confirm|just confirm|confirm|right|agree|do you agree|"
    r"am i right|correct|yes or no|(?:do|does|did|is|are|was|were|will|would|can|could)\s+"
    r"(?:they|it|he|she|that|this|those|these))\??$",
    re.I,
)
# A clause that only explains the one before it goes with it: "I'm nervous because my
# boss will be watching", "I'm a landlord, so I know the market".
_SUBORDINATE = re.compile(r"^(?:because|since|as|so)\b", re.I)


@dataclass(frozen=True)
class Edit:
    span: Span
    replacement: str
    kind: str
    detected: str


def _sentences(prompt: str) -> list[Span]:
    spans, start = [], 0
    for m in re.finditer(r"[.!?]+(?=\s|$)|\n{2,}", prompt):
        end = m.end()
        if prompt[start:end].strip():
            spans.append(Span(start, end))
        start = end
    if prompt[start:].strip():
        spans.append(Span(start, len(prompt)))
    return spans


def _trim(prompt: str, span: Span) -> Span:
    s, e = span.start, span.end
    while s < e and prompt[s].isspace():
        s += 1
    while e > s and prompt[e - 1].isspace():
        e -= 1
    return Span(s, e)


def _clauses(prompt: str, sentence: Span) -> list[Span]:
    text = prompt[sentence.start : sentence.end]
    cuts = [0] + [m.end() for m in _SPLIT.finditer(text)] + [len(text)]
    out = []
    for a, b in zip(cuts, cuts[1:], strict=False):
        span = _trim(prompt, Span(sentence.start + a, sentence.start + b))
        if span.end > span.start:
            out.append(span)
    return out


def _kind(clause: str) -> str | None:
    body = _CONNECTIVE.sub("", clause.strip().lower()).strip(" ,;:!.?")
    body = re.sub(r"^(?:honestly|personally|frankly),?\s+", "", body)
    if not body:
        return None
    for kind, pattern in _CLAUSES:
        if pattern.search(body):
            if kind == SOCIAL and not _VERDICT.search(body):
                continue
            if kind == STANCE and _ABOUT_ONESELF.match(body) and not _JUDGED.search(body):
                continue
            if kind == CREDENTIAL and _TASK_CONTEXT.search(body):
                continue
            return kind
    if _OWNERSHIP.fullmatch(" " + body):
        return OWNERSHIP
    if DETECTOR is not None and _statement(body) and DETECTOR(clause.strip()):
        return LEARNED
    return None


# A trained detector may only take out a statement. Self-presentation is something said
# about oneself; a question or an instruction is the task, whatever it sounds like.
_REQUEST_START = re.compile(
    r"^(?:rate|review|critique|tell|give|evaluate|assess|check|help|write|summari[sz]e|"
    r"explain|grade|score|judge|rank|compare|point|suggest|list|draft|improve|fix|rewrite|"
    r"proofread|edit|translate|should|can|could|would|will|is|are|am|was|were|do|does|did|"
    r"what|how|who|which|why|where|when|please|let|be\s+honest)\b"
)


_FIRST_PERSON = re.compile(r"\b(?:i|i'm|i've|i'd|i'll|me|my|mine|myself)\b")


def _statement(body: str) -> bool:
    """A statement, by the person asking, about themselves or what they have heard."""
    return (
        not body.rstrip().endswith("?")
        and not _REQUEST_START.match(body)
        and _FIRST_PERSON.search(body) is not None
    )


# Restatements. Each finds the framing at the start of a clause; only the framing is
# replaced, so what it frames stays original text for the other mechanisms - "my budget"
# in "I've decided to cut my budget" still becomes "Person A's budget".
_RESTATE: tuple[tuple[re.Pattern[str], str, str | None], ...] = (
    (
        re.compile(r"(?i)^i(?:'ve|\s+have)?\s+(?:already\s+)?decided\s+to\s+"),
        "The plan is to ",
        None,
    ),
    (re.compile(r"(?i)^(?:i'm|i\s+am)\s+leaning\s+towards?\s+"), "Another option is ", None),
    # Who made it, said of anyone - so "I wrote this" and "a colleague wrote this" still
    # become the same prompt.
    (
        re.compile(
            r"(?i)^(?:i|someone|(?:a|my|our)\s+(?:colleague|coworker|co-worker|friend|"
            r"teammate|team|student|client|manager|boss|report|intern))\s+(?:just\s+)?"
            r"(?:wrote|drafted|made|built|designed|created|coded|composed|put\s+together)\s+"
            r"(?:this|the)\s+"
        ),
        "This is the ",
        None,
    ),
    (
        re.compile(
            r"(?i)^(?:my|our)\s+[\w-]+(?:\s+[\w-]+)?\s+(?:thinks|says|wants)\s+i\s+should\s+"
        ),
        "One option is to ",
        None,
    ),
    (
        re.compile(
            r"(?i)^(?:don't|doesn't|wouldn't|isn't|aren't)\s+(?:you|it|this|that)\s+"
            r"(?:think|agree|say|feel)(?:\s+that)?\s+"
        ),
        "Evaluate whether ",
        ".",
    ),
    (
        re.compile(r"(?i)^am\s+i\s+right\s+(?:that|to\s+think(?:\s+that)?)\s+"),
        "Evaluate whether ",
        ".",
    ),
)
_CLAIM = re.compile(
    r"(?i)^(?:(?:honestly|personally),?\s+)?i\s+(?:really\s+|honestly\s+|truly\s+)?"
    r"(?:think|believe|feel)(?:\s+that)?\s+"
)


def _restate(prompt: str, clause: Span) -> list[Edit] | None:
    """Edits that restate a clause without its owner, or None if it is not one of those."""
    words = prompt[clause.start : clause.end]
    lead = _CONNECTIVE.match(words)
    offset = lead.end() if lead else 0
    for pattern, framing, ending in _RESTATE:
        m = pattern.match(words[offset:])
        if not m:
            continue
        head = Span(clause.start, clause.start + offset + m.end())
        edits = [Edit(head, framing, RESTRUCTURED, prompt[head.start : head.end])]
        if ending:
            tail = re.search(r"[.!?]*$", words)
            at = clause.start + tail.start()
            edits.append(Edit(Span(at, clause.end), ending, RESTRUCTURED, prompt[at : clause.end]))
        return edits
    return None


def find(prompt: str, protected: list[Span]) -> list[Edit]:
    """Every passage of self-presentation outside the work, with what replaces it."""

    def overlaps_work(span: Span) -> bool:
        return any(span.start < w.end and span.end > w.start for w in protected)

    edits: list[Edit] = []
    sentences = _sentences(prompt)
    skip_next = False
    for si, sentence in enumerate(sentences):
        if skip_next:
            skip_next = False
            continue
        body = _trim(prompt, sentence)
        text = prompt[body.start : body.end]

        clauses = _clauses(prompt, body)
        found: list = []
        for clause in clauses:
            if overlaps_work(clause):
                found.append(None)
                continue
            restated = _restate(prompt, clause)
            found.append(
                restated if restated is not None else _kind(prompt[clause.start : clause.end])
            )
        for ci in range(1, len(clauses)):
            words = prompt[clauses[ci].start : clauses[ci].end]
            if found[ci] is None and isinstance(found[ci - 1], str) and _SUBORDINATE.match(words):
                found[ci] = found[ci - 1]

        # "I think X. Can you confirm?" / "I think X. Do they?" - one question, asked
        # neutrally, made of this sentence's last clause and the whole of the next.
        if clauses and si + 1 < len(sentences) and not overlaps_work(body):
            last = clauses[-1]
            words = prompt[last.start : last.end]
            lead = _CONNECTIVE.match(words)
            offset = lead.end() if lead else 0
            claim = _CLAIM.match(words[offset:])
            nxt = _trim(prompt, sentences[si + 1])
            if claim and _CONFIRM.match(prompt[nxt.start : nxt.end].strip()):
                head = Span(last.start, last.start + offset + claim.end())
                stop = re.search(r"[.!]*$", words)
                tail = Span(last.start + stop.start(), nxt.end)
                found[-1] = [
                    Edit(head, "Evaluate whether ", RESTRUCTURED, prompt[head.start : head.end]),
                    Edit(tail, ".", RESTRUCTURED, prompt[tail.start : tail.end]),
                ]
                skip_next = True

        if found and all(isinstance(f, str) for f in found):
            # The whole sentence is self-presentation, none of it restated: it goes - but
            # not the line breaks around it, which may be what separates two turns.
            start, end = body.start, body.end
            after = len(re.match(r"[ \t]*", prompt[end:]).group(0))
            if end + after == len(prompt) or prompt[end + after] == "\n":
                # The last sentence of its line: the space before it goes instead.
                start -= len(re.search(r"[ \t]*$", prompt[:start]).group(0))
            else:
                end += after
            edits.append(Edit(Span(start, end), "", sorted(set(found))[0], text))
            continue

        for ci, (clause, f) in enumerate(zip(clauses, found, strict=True)):
            if f is None:
                continue
            if isinstance(f, list):
                edits.extend(f)
                continue
            # The clause goes, with the punctuation that joined it to its neighbour. The
            # sentence keeps its full stop; a leftover "but" at its start is taken later.
            start, end = clause.start, clause.end
            end -= len(prompt[start:end]) - len(prompt[start:end].rstrip(".!?"))
            if ci == 0:
                end += len(re.match(r"[\s,;]*", prompt[end:]).group(0))
            else:
                start -= len(re.search(r"[\s,;]*$", prompt[:start]).group(0))
            edits.append(Edit(Span(start, end), "", f, prompt[clause.start : clause.end]))

        # Ownership said in passing: "Logo A was designed by me, Logo B by a big agency".
        for m in _OWNERSHIP.finditer(text):
            span = Span(body.start + m.start(), body.start + m.end())
            if not overlaps_work(span):
                edits.append(Edit(span, "", OWNERSHIP, m.group(0).strip()))

    # Removals that touch become one; otherwise nothing overlaps, and the earlier, wider
    # edit wins.
    edits.sort(key=lambda e: (e.span.start, -(e.span.end - e.span.start)))
    out: list[Edit] = []
    for e in edits:
        if out and e.span.start <= out[-1].span.end:
            prev = out[-1]
            if not prev.replacement and not e.replacement:
                out[-1] = Edit(
                    Span(prev.span.start, max(prev.span.end, e.span.end)),
                    "",
                    prev.kind,
                    prev.detected,
                )
                continue
            if e.span.start < prev.span.end:
                continue
        out.append(e)
    # A removal that opens the prompt or a paragraph takes the space after it with it.
    for i, e in enumerate(out):
        if e.replacement or prompt[: e.span.start].strip(" \t")[-1:] not in ("", "\n"):
            continue
        gap = len(re.match(r"[ \t]*", prompt[e.span.end :]).group(0))
        nxt = out[i + 1].span.start if i + 1 < len(out) else len(prompt)
        out[i] = Edit(Span(e.span.start, min(e.span.end + gap, nxt)), "", e.kind, e.detected)
    return out + _recapitalise(prompt, out)


def _recapitalise(prompt: str, edits: list[Edit]) -> list[Edit]:
    """A removal at the start of a sentence can leave "but can you review this?" behind:
    the joining word goes too, and the next word takes the capital."""
    extra: list[Edit] = []
    taken = [e.span for e in edits]
    for e in edits:
        if e.replacement:
            continue
        before = prompt[: e.span.start]
        if before.strip() and not re.search(r"[.!?:\n]\s*$", before):
            continue
        m = re.match(r"(\s*)((?:but|and|so)\s+)?([a-zA-Z])", prompt[e.span.end :])
        if not m:
            continue
        start = e.span.end + len(m.group(1))
        letter = e.span.end + m.start(3)
        if not m.group(2) and prompt[letter].isupper():
            continue
        span = Span(start, letter + 1)
        if any(span.start < t.end and span.end > t.start for t in taken):
            continue
        extra.append(Edit(span, prompt[letter].upper(), RESTRUCTURED, prompt[start : letter + 1]))
    return extra
