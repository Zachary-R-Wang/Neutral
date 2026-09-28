"""Stage 1 - DETECT, continued. Descriptions of a person that carry who they are.

Names and pronouns are one way a prompt says who someone is. Most prompts people actually
type use another: "an 18 year old model", "my female colleague", "a Nigerian engineer",
"a mother of three". On 2026-09-28 the founder measured the result of ignoring them -
nothing changed in nineteen prompts of twenty - and `make relevance` agreed: none of the
29 descriptions in the everyday set was touched.

This module only finds. Whether a description is needed for the task is the policy's
question (policy.py), and what it is replaced with is Mechanism 1's. A word is only
found when it describes a PERSON: "a young founder" but not "a young company", "an Indian
applicant" but not "Indian food". Text in quotation marks is the work being assessed and
is never searched.

Kinds:
  age          "58-year-old", "aged 26", "50-something", "in her forties", "They are 24."
  gender       "female", "male", and "woman", "man", "actress", "chairman" as nouns
  family       "mother", "wife", "son" - a relationship that also states a gender
  origin       nationality, ethnicity, race: "Nigerian", "Latina", "Black"
  religion     "Muslim", "Jewish", "hijab-wearing"
  orientation  "gay", "lesbian", "transgender"
"""

from __future__ import annotations

import re

from neutral.core import Span
from neutral.detect import Finding

AGE, GENDER, FAMILY, ORIGIN, RELIGION, ORIENTATION = (
    "age",
    "gender",
    "family",
    "origin",
    "religion",
    "orientation",
)
ATTRIBUTE_KINDS = (AGE, GENDER, FAMILY, ORIGIN, RELIGION, ORIENTATION)

_QUOTED = re.compile(r'"[^"]*"|“[^”]*”|(?<=:\s)\'[^\']+\'', re.S)

_NUMBER_WORDS = "twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety"
_AGE_PATTERNS = (
    # "58-year-old", "18 year old", "a 45 yr old"
    re.compile(r"\b\d{1,3}(?:\s*|-)(?:years?|yrs?)(?:\s*|-)old\b", re.I),
    # "50-something", "thirty-something"
    re.compile(rf"\b(?:\d0|{_NUMBER_WORDS})(?:-|\s)something\b", re.I),
    # "in her forties", "in their early 30s"
    re.compile(
        r"\bin\s+(?:his|her|their|my|your)\s+(?:early\s+|mid-?\s*|late\s+)?"
        r"(?:\d0s|\d0's|twenties|thirties|forties|fifties|sixties|seventies|eighties|nineties)\b",
        re.I,
    ),
    # ", aged 26" and "(aged 26)" - the punctuation goes with it
    re.compile(r",\s*aged\s+\d{1,3}\b|\s*\(aged?\s+\d{1,3}\)", re.I),
    # "Someone aged 29 has asked..." - no comma, and the space before goes with it
    re.compile(r"(?<=\w)\s+aged\s+\d{1,3}\b", re.I),
)
# A sentence that does nothing but state an age: "They are 24." Removed whole.
_AGE_SENTENCE = re.compile(
    r"(?:(?<=[.!?])\s+|^)(?:They|He|She|I|We)\s*(?:are|is|am|'m|'re|’m|’re)\s+"
    r"\d{1,3}(?:\s+years\s+old)?\s*[.!]",
)

_AGE_WORDS = {"young", "elderly", "middle-aged", "aging", "ageing", "youthful", "old"}
_GENERATIONS = re.compile(r"\b(?:millennial|boomer|zoomer|gen[\s-]?[zx])s?\b", re.I)

_GENDER_MODIFIERS = {"female", "male"}
# Gendered nouns, and the neutral noun Mechanism 1 puts in their place.
GENDER_NOUNS = {
    "woman": "person",
    "women": "people",
    "man": "person",
    "men": "people",
    "lady": "person",
    "ladies": "people",
    "gentleman": "person",
    "gentlemen": "people",
    "gal": "person",
    "actress": "actor",
    "actresses": "actors",
    "waitress": "server",
    "waiter": "server",
    "businessman": "businessperson",
    "businesswoman": "businessperson",
    "chairman": "chair",
    "chairwoman": "chair",
    "salesman": "salesperson",
    "saleswoman": "salesperson",
    "spokesman": "spokesperson",
    "spokeswoman": "spokesperson",
    "policeman": "police officer",
    "policewoman": "police officer",
    "fireman": "firefighter",
    "stewardess": "flight attendant",
    "housewife": "homemaker",
    "headmaster": "head teacher",
    "headmistress": "head teacher",
    "foreman": "supervisor",
}
FAMILY_NOUNS = {
    "mother": "parent",
    "mom": "parent",
    "mum": "parent",
    "mommy": "parent",
    "father": "parent",
    "dad": "parent",
    "daddy": "parent",
    "mothers": "parents",
    "moms": "parents",
    "mums": "parents",
    "fathers": "parents",
    "dads": "parents",
    "wife": "spouse",
    "husband": "spouse",
    "wives": "spouses",
    "husbands": "spouses",
    "girlfriend": "partner",
    "boyfriend": "partner",
    "daughter": "child",
    "son": "child",
    "daughters": "children",
    "sons": "children",
    "sister": "sibling",
    "brother": "sibling",
    "sisters": "siblings",
    "brothers": "siblings",
    "aunt": "relative",
    "uncle": "relative",
    "niece": "relative",
    "nephew": "relative",
    "grandmother": "grandparent",
    "grandfather": "grandparent",
    "grandma": "grandparent",
    "grandpa": "grandparent",
}

_RELIGIONS = {
    "muslim",
    "christian",
    "jewish",
    "hindu",
    "sikh",
    "buddhist",
    "catholic",
    "protestant",
    "mormon",
    "evangelical",
    "orthodox",
    "atheist",
}
_RELIGIOUS_DRESS = re.compile(
    r"\b(?:hijab|turban|kippah|yarmulke|niqab|burqa|headscarf|veil)-wearing\b", re.I
)
_ORIENTATIONS = {
    "gay",
    "lesbian",
    "bisexual",
    "queer",
    "transgender",
    "trans",
    "nonbinary",
    "non-binary",
    "lgbt",
    "lgbtq",
    "lgbtq+",
}
_RACES = {"black", "white", "brown", "asian", "hispanic", "latino", "latina", "latinx"}

# Nouns that name a person. Listed where a suffix would not catch them, and a suffix
# rule for the rest: an "-er", "-ist", "-ant" is usually somebody.
_PERSON_NOUNS = {
    "person",
    "people",
    "colleague",
    "coworker",
    "co-worker",
    "boss",
    "candidate",
    "applicant",
    "employee",
    "staff",
    "hire",
    "intern",
    "graduate",
    "student",
    "founder",
    "executive",
    "exec",
    "chef",
    "nurse",
    "doctor",
    "model",
    "creator",
    "influencer",
    "couple",
    "family",
    "friend",
    "neighbour",
    "neighbor",
    "client",
    "customer",
    "patient",
    "guest",
    "individual",
    "adult",
    "cashier",
    "clerk",
    "analyst",
    "architect",
    "artist",
    "coach",
    "cook",
    "coordinator",
    "director",
    "engineer",
    "lawyer",
    "attorney",
    "lead",
    "mentor",
    "mentee",
    "officer",
    "partner",
    "pilot",
    "president",
    "professional",
    "professor",
    "rep",
    "representative",
    "scientist",
    "specialist",
    "surgeon",
    "teacher",
    "tech",
    "technician",
    "veteran",
    "volunteer",
    "worker",
    "recruit",
    "trainee",
    "apprentice",
    "author",
    "writer",
    "entrepreneur",
    "freelancer",
    "contractor",
    "consultant",
    "athlete",
    "musician",
    "actor",
    "player",
}
_NOT_PEOPLE = {
    "paper",
    "computer",
    "water",
    "center",
    "centre",
    "order",
    "error",
    "number",
    "letter",
    "matter",
    "power",
    "answer",
    "sector",
    "factor",
    "content",
    "event",
    "document",
    "department",
    "government",
    "environment",
    "payment",
    "market",
    "restaurant",
    "chapter",
    "quarter",
    "cancer",
    "counter",
    "filter",
    "folder",
    "header",
    "layer",
    "server",
    "cluster",
    "poster",
    "summer",
    "winter",
    "corner",
    "border",
    "tier",
    "career",
    "tenure",
    "major",
    "minor",
    "mirror",
    "motor",
    "vendor",
    "monitor",
    "sensor",
    "tutorial",
    "moment",
    "comment",
    "element",
    "segment",
    "statement",
    "agreement",
    "assignment",
    "judgment",
    "argument",
    "investment",
    "component",
    "equipment",
    "management",
    "requirement",
    "treatment",
    "percent",
    "cent",
    "talent",
    "variant",
    "plant",
    "grant",
    "account",
}


def _is_person(noun) -> bool:
    low = noun.lemma_.lower()
    text = noun.text.lower()
    if noun.pos_ == "PROPN" or noun.ent_type_ == "PERSON":
        return True
    if noun.pos_ not in ("NOUN",):
        return False
    if low in _PERSON_NOUNS or text in _PERSON_NOUNS:
        return True
    if low in GENDER_NOUNS or low in FAMILY_NOUNS or text in GENDER_NOUNS:
        return True
    if low in _NOT_PEOPLE:
        return False
    return low.endswith(("er", "or", "ist", "ian", "ant", "ent", "ee", "ess", "person"))


def _quoted(prompt: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _QUOTED.finditer(prompt)]


def _inside(start: int, spans: list[tuple[int, int]]) -> bool:
    return any(s <= start < e for s, e in spans)


def detect_attributes(prompt: str, claimed: list[Span] | None = None) -> list[Finding]:
    """Every description of a person in the prompt, outside quoted work.

    `claimed` are spans already found by name detection; nothing overlapping them is
    returned, so a name and a description are never replaced twice.
    """
    from neutral.detect import _model

    quoted = _quoted(prompt)
    taken: list[tuple[int, int]] = [(c.start, c.end) for c in claimed or []]
    found: list[Finding] = []

    def add(start: int, end: int, kind: str) -> None:
        if start >= end or _inside(start, quoted):
            return
        if any(start < e and end > s for s, e in taken):
            return
        taken.append((start, end))
        found.append(Finding(Span(start, end), prompt[start:end], kind))

    for match in _AGE_SENTENCE.finditer(prompt):
        add(match.start(), match.end(), AGE)
    for pattern in _AGE_PATTERNS:
        for match in pattern.finditer(prompt):
            add(match.start(), match.end(), AGE)
    for match in _GENERATIONS.finditer(prompt):
        add(match.start(), match.end(), AGE)
    for match in _RELIGIOUS_DRESS.finditer(prompt):
        add(match.start(), match.end(), RELIGION)

    nlp = _model()
    if nlp is None:
        # Without the parser there is no telling "a young founder" from "a young
        # company". The patterns above are unambiguous and stand; the rest waits.
        return sorted(found, key=lambda f: f.span.start)

    doc = nlp(prompt)
    for token in doc:
        low = token.text.lower()
        start, end = token.idx, token.idx + len(token.text)
        head = token.head

        # Nouns that are themselves the description: "woman", "actress", "wife".
        if token.pos_ == "NOUN" and token.dep_ != "compound":
            if low in GENDER_NOUNS:
                add(start, end, GENDER)
                continue
            if low in FAMILY_NOUNS:
                add(start, end, FAMILY)
                continue

        # Words that describe a person noun: "female colleague", "Nigerian engineer".
        modifies_person = token.dep_ in ("amod", "compound", "nmod", "appos") and _is_person(head)
        # "a 22-year-old gay man": the parser sometimes hangs the second adjective off
        # the first. Follow the chain up to the noun.
        if (
            not modifies_person
            and token.dep_ in ("amod", "compound")
            and head.dep_
            in (
                "amod",
                "compound",
            )
        ):
            modifies_person = _is_person(head.head)
        if not modifies_person:
            continue
        if low in _AGE_WORDS:
            add(start, end, AGE)
        elif low in _GENDER_MODIFIERS:
            add(start, end, GENDER)
        elif low in _RELIGIONS:
            add(start, end, RELIGION)
        elif low in _ORIENTATIONS:
            add(start, end, ORIENTATION)
        elif low in _RACES or (token.ent_type_ == "NORP" and low not in _RELIGIONS):
            add(start, end, ORIGIN)

    return sorted(found, key=lambda f: f.span.start)
