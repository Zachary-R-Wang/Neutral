"""Stage 1 - DETECT. Find the spans in a prompt that carry identity signal.

Detection only finds things. It never decides what to do about them; that is the policy
engine's job, and keeping the two apart is what CLAUDE.md section 4 means by separating
policy from execution.

Phase 1 detects personal names and the pronouns bound to them, and nothing else.

How detection works, and why: a model is asked to list the names, with a fixed prompt and
a structured reply. The obvious alternative - a rule that treats capitalised words as
names - misfires constantly on ordinary prompts ("Senior", "Monday", "Sev-1", "HR"), and
every misfire means a real word replaced by a placeholder in the text sent onward.

Everything the model returns is then verified against the original text. A span it claims
that cannot be found verbatim is discarded rather than trusted. That check is what keeps a
detector hallucination from becoming an S1 violation.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache

from pydantic import BaseModel, Field

from neutral.core import Span

DETECT_SYSTEM = """You identify personal names in text. You do not rewrite anything.

Return every span that identifies a specific person:
  - personal names, given or family or both, exactly as they are written
  - possessive forms, such as "Emily's"

Do NOT return:
  - job titles, team names, company names, product names
  - days, months, places, or any other capitalised word that is not a person's name
  - pronouns - those are handled separately
  - a name that appears inside a quoted passage being assessed, where it belongs to
    someone other than a participant

Copy each span exactly as it appears, character for character. Do not correct spelling,
expand abbreviations, or change capitalisation. If there are no personal names, return an
empty list."""


class DetectedSpan(BaseModel):
    text: str = Field(description="The span exactly as it appears in the prompt.")
    kind: str = Field(description="Always 'person_name' at this phase.")


class Detection(BaseModel):
    spans: list[DetectedSpan] = Field(description="Every personal name found.")


@dataclass(frozen=True)
class Finding:
    """One detected span, verified to exist at this exact position in the original."""

    span: Span
    text: str
    kind: str


# Pronouns are resolved by rule, not by the model: the set is closed, and a closed set is
# better served by a lookup than by a model that might return something outside it.
PRONOUNS = {
    "he": "they",
    "him": "them",
    "his": "their",
    "himself": "themselves",
    "she": "they",
    "her": "them",
    "hers": "theirs",
    "herself": "themselves",
}

_WORD = re.compile(r"\b\w+(?:'\w+)?\b")
_CONTRACTED = re.compile(r"(he|she)'(?:s|ll|d|re|ve)", re.I)


def verify(prompt: str, claimed: list[DetectedSpan]) -> list[Finding]:
    """Keep only the spans that genuinely appear in the prompt, at a real position.

    A detector that invents a span would otherwise let the transform stage replace text
    that was never there, which is how a rewrite stops being traceable to its source.
    """
    findings: list[Finding] = []
    taken: list[tuple[int, int]] = []

    for item in sorted(claimed, key=lambda s: len(s.text), reverse=True):
        if not item.text.strip():
            continue
        for match in re.finditer(re.escape(item.text), prompt):
            start, end = match.start(), match.end()
            if any(start < t_end and end > t_start for t_start, t_end in taken):
                continue
            findings.append(Finding(Span(start, end), item.text, item.kind))
            taken.append((start, end))

    return sorted(findings, key=lambda f: f.span.start)


def find_pronouns(prompt: str, skip: list[Finding]) -> list[Finding]:
    """Gendered pronouns, by lookup. Spans already claimed by a name are left alone, and
    so is the work being assessed: "she" in a quoted joke is the joke's."""
    from neutral.work import inside, work_spans

    work = work_spans(prompt)
    claimed = [(f.span.start, f.span.end) for f in skip]
    findings = []
    for match in _WORD.finditer(prompt):
        word = match.group(0)
        start, end = match.start(), match.end()
        if word.lower() not in PRONOUNS:
            # "she's", "he'll", "she'd" are one word to the pattern above, and used to go
            # through untouched - gender and all. The pronoun is the part before the
            # apostrophe; the contraction is left for the grammar to adjust.
            contracted = _CONTRACTED.fullmatch(word)
            if not contracted:
                continue
            word = contracted.group(1)
            end = start + len(word)
        if any(start < c_end and end > c_start for c_start, c_end in claimed):
            continue
        if inside(start, work):
            continue
        findings.append(Finding(Span(start, end), word, "pronoun"))
    return findings


def detect_names(prompt: str, adapter) -> tuple[list[Finding], str | None]:
    """Find personal names. Returns (findings, error).

    An error is returned rather than raised: S4 requires the caller to fail open to the
    original prompt, and it cannot do that if detection throws.
    """
    parsed, completion = adapter.parse(
        f"Find the personal names in the text below.\n\n---\n{prompt}\n---",
        Detection,
        system=DETECT_SYSTEM,
    )
    if parsed is None:
        return [], completion.error or "the name detector did not return a usable answer"
    return verify(prompt, parsed.spans), None


# --------------------------------------------------------------------------------------
# Offline detection
# --------------------------------------------------------------------------------------

# A title belongs to the name it introduces and is substituted along with it. "Mr Nell"
# is one person, not two - and "Mr" states that person's gender, which is exactly the
# kind of signal this mechanism exists to remove.
TITLES = frozenset(
    """mr mrs ms miss mx dr prof professor sir dame lord lady rev reverend fr father
    capt captain sgt sergeant lt lieutenant col colonel gen general hon judge""".split()
)

# Capitalised words that are not people. Far from complete, and it does not need to be:
# this path exists so the rewriting can be shown without calling a model, not so it can
# be relied on.
_NOT_NAMES = (
    frozenset(
        """monday tuesday wednesday thursday friday saturday sunday january february march
        april may june july august september october november december senior junior lead
        principal staff director manager engineer engineering designer design product sales
        marketing finance legal hr operations ops support team teams company north south east
        west api apis sql python java sev ceo cto coo cfo vp svp evp phd mba english spanish
        french german write writing review reviews notes rate please assess draft summary
        section quarter q1 q2 q3 q4 the this that these those they their there here when what
        how why should would could must
        give given tell explain describe list provide consider imagine suppose create make
        help can does did is are was were i we you my our your if as at in on for with an and
        but or so then now also however based using it its from about after before during
        while because although unless until since each every some any all both either neither
        one two three first second third last next previous another other same different
        following above below here yes no ok okay thanks thank hello hi dear regards sincerely
        assume note edit revise improve shorten lengthen compare contrast teacher
        ask asks send sends email emails find get show check look read put take keep
        see say want need try use identify suggest recommend prepare outline""".split()
    )
    | set(PRONOUNS)  # a pronoun is never a name; they are found by lookup instead
    | TITLES  # nor is a bare title, with no name after it
)

_NAME = r"[A-Z][a-z]{1,}(?:'s)?"
_TITLE = "|".join(sorted({t.capitalize() for t in TITLES}, key=len, reverse=True))
# An optional title, then one to three capitalised words. The title is matched here rather
# than left out, because a full stop after "Mr" would otherwise split one person into two.
_CANDIDATE = re.compile(rf"\b(?:(?:{_TITLE})\.?\s+)?{_NAME}(?:\s+{_NAME}){{0,2}}\b")


def _bare(word: str) -> str:
    return re.sub(r"['’]s$|\.$", "", word).lower()


def detect_names_offline(prompt: str) -> list[Finding]:
    """Find likely personal names with rules only, making no network call.

    This is deliberately not the detector the product uses. Capitalisation is a poor
    signal for names in English and this will both miss real ones and flag words that are
    not names. It exists so the interface can show what Neutral does to a prompt when
    there is no model connected, clearly labelled as an approximation.
    """
    findings: list[Finding] = []
    for match in _CANDIDATE.finditer(prompt):
        text = match.group(0)
        parts = text.split()
        plain = [_bare(w) for w in parts]

        # Trim stopwords off each end rather than rejecting the whole candidate: without
        # this, "Tell Mark how..." loses Mark because Tell opens the sentence. A title is
        # kept when a name follows it, since it belongs to that person's reference.
        first, last = 0, len(parts)
        while first < last and plain[first] in _NOT_NAMES:
            if plain[first] in TITLES and last - first > 1:
                break
            first += 1
        while last > first and plain[last - 1] in _NOT_NAMES:
            last -= 1
        if first >= last or (last - first == 1 and plain[first] in TITLES):
            continue

        kept = " ".join(parts[first:last])
        start = prompt.index(kept, match.start(), match.end())
        findings.append(Finding(Span(start, start + len(kept)), kept, "person_name"))
    return findings


# --------------------------------------------------------------------------------------
# Local detection - the default
# --------------------------------------------------------------------------------------

_NLP = None
_NLP_FAILED = False


# Which spaCy model finds the names. Overridable so that the accuracy of one against
# another can be measured rather than argued about - see RESULTS.md. Whatever is named
# here must also be a declared dependency in pyproject.toml, or the next `uv sync` prunes
# it and detection silently degrades to rules.
DEFAULT_NER_MODEL = "en_core_web_lg"


def ner_model_name() -> str:
    """Which model was ASKED for. Not necessarily the one doing the work."""
    return os.environ.get("NEUTRAL_NER_MODEL", "").strip() or DEFAULT_NER_MODEL


def active_detector() -> str:
    """What is actually finding the names, having tried to load the model.

    The difference between this and ner_model_name matters more than it looks. A missing
    model degrades to rules silently and on purpose - a web request should not fail
    because of it. But a comparison of detectors that reports the name it asked for,
    while one of them quietly fell back to rules, measures the same thing twice and
    reports it under two names. That happened, and it inverted the conclusion.
    """
    return ner_model_name() if _model() is not None else "rules-only"


@lru_cache(maxsize=64)
def parse(text: str):
    """The parsed prompt, shared by every stage that needs one. None without a parser.

    Each mechanism used to parse the same prompt again - a dozen times for some prompts.
    Nothing modifies a parsed document, so one parse per text is safe to share."""
    nlp = _model()
    return nlp(text) if nlp is not None else None


def _model():
    """Load the local name recogniser once, or give up quietly and let rules take over."""
    global _NLP, _NLP_FAILED
    if _NLP is not None or _NLP_FAILED:
        return _NLP
    try:
        import spacy

        _NLP = spacy.load(ner_model_name())
    except Exception:  # noqa: BLE001 - a missing model must degrade, never crash
        _NLP_FAILED = True
    return _NLP


def _repeat_mentions(prompt: str, found: list[Finding]) -> list[Finding]:
    """Later mentions of a name already found: "Emily Carter", then just "Emily".

    A statistical recogniser reliably catches the full name and often not the short form
    that follows it. Left alone, the first mention is anonymised and the rest are not,
    which defeats the mechanism entirely - the model still learns who it is reading about.

    Only exact words taken from names already detected are matched, so this can never
    introduce a name that was not found in the first place.
    """
    taken = [(f.span.start, f.span.end) for f in found]
    words: set[str] = set()
    for finding in found:
        for word in finding.text.split():
            bare = re.sub(r"['\u2019]s$|\.$", "", word)
            if len(bare) >= 3 and bare[:1].isupper() and bare.lower() not in TITLES:
                words.add(bare)

    extra: list[Finding] = []
    for word in sorted(words, key=len, reverse=True):
        for match in re.finditer(rf"\b{re.escape(word)}(?:['\u2019]s)?\b", prompt):
            start, end = match.start(), match.end()
            if any(start < t_end and end > t_start for t_start, t_end in taken):
                continue
            taken.append((start, end))
            extra.append(Finding(Span(start, end), match.group(0), "person_name"))
    return extra


def detect_names_local(prompt: str) -> list[Finding]:
    """Find personal names on this machine: no network call, no cost, a few milliseconds.

    A statistical recogniser running locally, then the same two rules the offline path
    uses, because the recogniser has blind spots that rules cover cheaply:

      * it returns "Nell" for "Mr. Nell", dropping a title that states the person's
        gender - the span is extended backwards to take it in
      * it sometimes swallows the verb in front of a name, returning "Tell Mark" - leading
        stopwords are trimmed

    Falls back to rules entirely if the model cannot be loaded, so the product works on a
    machine where the download never happened.
    """
    nlp = _model()
    if nlp is None:
        return detect_names_offline(prompt)

    findings: list[Finding] = []
    taken: list[tuple[int, int]] = []

    for entity in nlp(prompt).ents:
        if entity.label_ != "PERSON":
            continue
        start, end = entity.start_char, entity.end_char

        # Trim leading words the recogniser wrongly absorbed.
        while start < end:
            first = prompt[start:end].split(" ", 1)[0]
            if _bare(first) in _NOT_NAMES and _bare(first) not in TITLES:
                start += len(first) + 1
            else:
                break
        if start >= end:
            continue

        # Extend backwards over a title, which belongs to the name and carries gender.
        before = prompt[:start].rstrip()
        for title in TITLES:
            for spelling in (title.capitalize(), title.upper()):
                for form in (spelling + ".", spelling):
                    if before.endswith(form) and (
                        len(before) == len(form) or not before[-len(form) - 1].isalnum()
                    ):
                        start = len(before) - len(form)
                        break

        text = prompt[start:end]
        if not text.strip() or _bare(text) in _NOT_NAMES:
            continue
        if any(start < t_end and end > t_start for t_start, t_end in taken):
            continue
        taken.append((start, end))
        findings.append(Finding(Span(start, end), text, "person_name"))

    findings.extend(_repeat_mentions(prompt, findings))
    return sorted(findings, key=lambda f: f.span.start)
