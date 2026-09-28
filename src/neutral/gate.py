"""The relevance gate: does this task need this description of a person?

CLAUDE.md §5, Phase 2. The policy engine asks, for each description found in a prompt,
whether it is load-bearing for the TASK. It is never asked about safety: S3 is decided
before this, by policy.safety_hold, and a prompt held there never reaches a gate.

A gate only answers yes or no. It never writes text, so whatever it decides, S1 still
holds: the most it can do is let a description be removed.

Two gates, chosen by `NEUTRAL_GATE` and measured side by side by `make relevance`:

  rules   keeps a description when the request is about that kind of thing - the law,
          a name, clothes, culture, discrimination, an announcement - and lets it go
          otherwise. Instant, no dependencies, and blind to anything it has no word for.
  laya    asks Laya, an open decision model that returns a probability rather than
          text, whether a good answer depends on the description. Needs the model
          installed; when it is not, the rules gate stands in, and the decision says so.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from neutral.detect import Finding
from neutral.detect_attributes import AGE, FAMILY, GENDER, ORIENTATION, ORIGIN, RELIGION

ALL = (AGE, GENDER, FAMILY, ORIGIN, RELIGION, ORIENTATION)


@dataclass(frozen=True)
class Verdict:
    needed: bool
    reason: str
    probability: float | None = None


# Each rule: the kinds of description it protects, and the words that show a request is
# about that kind of thing.
_RULES: tuple[tuple[tuple[str, ...], str, re.Pattern[str]], ...] = (
    (
        ALL,
        "the request is about the law or someone's rights",
        re.compile(
            r"\b(?:law|laws|legal|legally|illegal|rights|discriminat\w*|regulations?|"
            r"complian\w*|lawsuit|sue|tribunal|eeoc|protected\s+characteristics?)\b",
            re.I,
        ),
    ),
    (
        ALL,
        "the request asks about the description itself",
        re.compile(
            r"\b(?:(?:a\s+)?(?:man|woman|male|female)\s+or\s+(?:a\s+)?(?:man|woman|male|female)|"
            r"how\s+old|what\s+age|gender|ethnicity|nationality|race|religion|religious|"
            r"sexuality|orientation|pronouns?)\b",
            re.I,
        ),
    ),
    (
        ALL,
        "the request concerns discrimination or representation",
        re.compile(
            r"\b(?:police|racis\w*|sexis\w*|ageis\w*|homophob\w*|diversity|inclusion|"
            r"representation|minorit(?:y|ies)|underrepresented|stereotyp\w*|bias(?:ed)?|"
            r"microaggressions?|affirmative)\b",
            re.I,
        ),
    ),
    (
        (ORIGIN, RELIGION),
        "the request is about names, language or culture",
        re.compile(
            r"\b(?:pronounc\w*|spell\w*|names?|translat\w*|language|accent|cultur\w*|"
            r"customs?|etiquette|greeting|honorific|traditions?|traditional|holidays?|"
            r"festival|prayers?|pray|fasting|ramadan|diet(?:ary)?|halal|kosher)\b",
            re.I,
        ),
    ),
    (
        (GENDER, FAMILY),
        "the request is about dress or the body",
        re.compile(
            r"\b(?:wear|wearing|dress(?:ed)?|outfits?|clothes|clothing|attire|makeup|"
            r"hair(?:style)?|plus-size|petite)\b",
            re.I,
        ),
    ),
    (
        ALL,
        "the description is what is being announced or celebrated",
        re.compile(
            r"\b(?:announc\w*|introduc\w*|welcom\w*|celebrat\w*|congratulat\w*|"
            r"press\s+release|linkedin\s+post)\b",
            re.I,
        ),
    ),
    (
        (FAMILY,),
        "the request is about parental or family leave",
        re.compile(r"\b(?:maternity|paternity|parental|adoption)\b", re.I),
    ),
    (
        ALL,
        "the request is about how the person is treated because of who they are",
        re.compile(
            r"\b(?:treated\s+differently|ignor(?:e|es|ed|ing)|excluded|targeted|"
            r"jokes?\s+about|comments?\s+about|slurs?|(?:report|reporting|complain\w*)\b.{0,20}\bhr|"
            r"male-dominated|female-dominated|only\s+(?:woman|man|women|men|black|asian|latina|"
            r"latino|gay|muslim|jewish|person\s+of\s+colou?r)|pay\s+gap|equal\s+pay|underpaid|"
            r"glass\s+ceiling|taken\s+seriously|heritage|roots)\b",
            re.I,
        ),
    ),
    (
        (AGE,),
        "the request is about the person's age",
        re.compile(r"\b(?:too\s+old|too\s+young|at\s+my\s+age|age\s+limit|ageis\w*)\b", re.I),
    ),
    (
        (RELIGION, ORIGIN),
        "the request is about religious observance",
        re.compile(
            r"\b(?:faith|devout|church|mosque|synagogue|temple|worship|sabbath|shabbat|"
            r"sundays?|friday\s+night|ethical\s+for\s+me)\b",
            re.I,
        ),
    ),
    (
        (AGE, FAMILY),
        "the request is about money over a lifetime, where age and family change the answer",
        re.compile(
            r"\b(?:savings|invest\w*|index\s+funds?|retirement|retiring|pension|401k|mortgage|"
            r"insurance|estate|will\s+and\s+testament)\b",
            re.I,
        ),
    ),
)


def rules_verdicts(prompt: str, findings: list[Finding]) -> list[Verdict]:
    out = []
    for finding in findings:
        # A description never argues for keeping itself: "has a heavy accent on the phone"
        # must not match the rule that keeps accents when accents are the question.
        masked = (
            prompt[: finding.span.start]
            + " " * (finding.span.end - finding.span.start)
            + prompt[finding.span.end :]
        )
        for kinds, why, pattern in _RULES:
            if finding.kind in kinds and pattern.search(masked):
                out.append(Verdict(True, f"kept: {why}"))
                break
        else:
            out.append(Verdict(False, "removed: nothing in the request depends on it"))
    return out


_KIND_WORDS = {
    AGE: "age",
    GENDER: "gender",
    FAMILY: "gender",
    ORIGIN: "nationality, ethnicity or race",
    RELIGION: "religion",
    ORIENTATION: "sexual orientation or gender identity",
}

# Fixed, like the judge's rubric: changing it after seeing results is how a measurement
# is fooled. Recorded in DECISIONS.md with the date it was set.
LAYA_QUESTION = (
    "Does a good answer to this request depend on the person's {kind} ({text})? Answer "
    "yes only if the answer would be wrong or unhelpful without knowing it."
)
LAYA_THRESHOLD = 0.5

_router = None


def _laya():
    global _router
    if _router is None:
        from laya import Router  # optional: only present where Laya has been installed

        _router = Router()
    return _router


def laya_verdicts(prompt: str, findings: list[Finding]) -> list[Verdict]:
    try:
        router = _laya()
    except Exception:  # noqa: BLE001 - not installed, or the model would not load
        return [
            Verdict(v.needed, v.reason + " (Laya unavailable, so the rules decided)")
            for v in rules_verdicts(prompt, findings)
        ]
    questions = {
        f"q{i}": {
            "type": "noul",
            "instructions": LAYA_QUESTION.format(kind=_KIND_WORDS[f.kind], text=f.text),
        }
        for i, f in enumerate(findings)
    }
    answers = router.predict(prompt, questions)["answers"]
    out = []
    for i in range(len(findings)):
        p = float(answers[f"q{i}"]["noul"])
        needed = p >= LAYA_THRESHOLD
        out.append(
            Verdict(
                needed,
                f"{'kept' if needed else 'removed'}: Laya put the chance that the answer "
                f"depends on it at {p:.0%}",
                p,
            )
        )
    return out


# Names, pronouns and the first person are decided by rules in every gate. They are the
# cases where the identity IS the question - "how do I pronounce", "translate this" - and
# those announce themselves in so many words.
NAME_RULE = re.compile(
    r"\b(?:pronounc\w*|spell(?:ed|ing|t)?|nicknames?|honorifics?|surnames?|"
    r"(?:family|given|first|last|middle|full|maiden|married)\s+names?|"
    r"(?:changing|change)\s+(?:her|his|their|my)\s+(?:sur)?name|name\s+change|"
    r"alphabeti\w*|initials|cyrillic|kanji|script|transliterat\w*|"
    r"what\s+does\s+the\s+name|meaning\s+of\s+(?:the\s+)?name|name\s+mean\w*|"
    r"(?:a\s+)?(?:man|woman)\s+or\s+(?:a\s+)?(?:man|woman))\b",
    re.I,
)
PRONOUN_RULE = re.compile(
    r"\b(?:pronouns?|referred\s+to\s+as|refer\s+to\s+(?:him|her|them)\s+as|"
    r"misgender\w*)\b",
    re.I,
)
FIRST_PERSON_RULE = re.compile(
    r"\b(?:grammar|grammatical(?:ly)?|proofread\w*|punctuation|translat\w*|"
    r"(?:first|second|third)[\s-]person|in\s+the\s+sentence|is\s+it\s+[\"'\u201c]|"
    r"rephrase|paraphrase)\b",
    re.I,
)


def identity_verdict(prompt: str, kind: str) -> Verdict:
    """For a name ("person_name"), a pronoun ("pronoun") or the first person."""
    rule, why = {
        "person_name": (NAME_RULE, "the request is about the name itself"),
        "pronoun": (PRONOUN_RULE, "the request is about which pronoun to use"),
        "first_person": (FIRST_PERSON_RULE, "the first person is the text being worked on"),
    }[kind]
    if rule.search(prompt):
        return Verdict(True, f"kept: {why}")
    return Verdict(False, "replaced: nothing in the request depends on it")


# A request for a judgement: a rating, a verdict, feedback, a choice between options, or
# whether a claim is true. Where it is found, what the person asking says about their own
# stake is taken out (mechanisms/self_presentation.py); where it is not - "I'm nervous,
# how do I calm down?" - that is the question, and it stays.
JUDGEMENT_RULE = re.compile(
    r"\b(?:rate|rating|review|critique|critic\w*|assess\w*|evaluat\w*|grade|score|judge|"
    r"rank|feedback|opinion|what\s+do\s+you\s+think|thoughts\s+on|"
    r"is\s+(?:it|this|that|my\s+\w+(?:\s+\w+)?|the\s+\w+)\s+(?:any\s+)?(?:good|ok|okay|fine|"
    r"strong|right|correct|valid|fair|funny|catchy|reasonable|realistic|smart|original|"
    r"worth|ready|better|a\s+good\s+idea|good\s+enough)|will\s+it\s+work|who(?:'s|\s+is)\s+right|"
    r"which\s+(?:is|one|of)\b.*\b(?:better|best)|valid|confirm|honest(?:ly)?|pros\s+and\s+cons|"
    r"does\s+the\s+evidence|is\s+it\s+true|do\s+they|does\s+it|better\s+use|"
    r"don't\s+you\s+(?:think|agree)|wouldn't\s+you\s+agree|am\s+i\s+(?:right|wrong)|"
    r"(?:tell\s+me|let\s+me\s+know)\s+(?:honestly\s+)?(?:if|whether)|"
    r"(?:if|whether)\b[^.?!]{0,60}\b(?:is|are|was|will)\b[^.?!]{0,30}\b(?:good|funny|catchy|"
    r"strong|right|correct|valid|fair|work|original|any\s+good))\b",
    re.I,
)


def asks_for_judgement(prompt: str) -> Verdict:
    """Whether the request asks for a verdict. `needed` here means: yes, it does."""
    m = JUDGEMENT_RULE.search(prompt)
    if m:
        return Verdict(True, f'the request asks for a judgement ("{m.group(0)}")')
    return Verdict(False, "the request does not ask for a judgement")


def gate_name() -> str:
    return os.environ.get("NEUTRAL_GATE", "rules").strip().lower() or "rules"


def verdicts(prompt: str, findings: list[Finding]) -> list[Verdict]:
    if not findings:
        return []
    if gate_name() == "laya":
        return laya_verdicts(prompt, findings)
    return rules_verdicts(prompt, findings)
