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
APPEARANCE, CLASS = "appearance", "class"
ATTRIBUTE_KINDS = (AGE, GENDER, FAMILY, ORIGIN, RELIGION, ORIENTATION, APPEARANCE, CLASS)

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
    "guy": "person",
    "guys": "people",
    "dude": "person",
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
# Nationalities, so a tagger slip does not decide who is protected: spaCy tags "Filipino"
# as a language. Adjective forms only; country names are handled as "from <place>".
DEMONYMS = set(
    """afghan albanian algerian american angolan argentine argentinian armenian australian
    austrian azerbaijani bahraini bangladeshi belarusian belgian bolivian bosnian brazilian
    british bulgarian burmese cambodian cameroonian canadian chilean chinese colombian
    congolese croatian cuban cypriot czech danish dominican dutch ecuadorian egyptian emirati
    english eritrean estonian ethiopian fijian filipino filipina finnish french georgian german
    ghanaian greek guatemalan haitian honduran hungarian icelandic indian indonesian iranian
    iraqi irish israeli italian ivorian jamaican japanese jordanian kazakh kenyan korean
    kosovar kurdish kuwaiti kyrgyz lao latvian lebanese liberian libyan lithuanian malagasy
    malawian malaysian malian maltese mauritian mexican moldovan mongolian montenegrin
    moroccan mozambican namibian nepalese nepali nicaraguan nigerian nigerien norwegian omani
    pakistani palestinian panamanian paraguayan persian peruvian polish portuguese
    puerto-rican qatari romanian russian rwandan salvadoran samoan saudi scottish senegalese
    serbian sierra-leonean singaporean slovak slovenian somali south-african spanish
    sri-lankan sudanese swedish swiss syrian taiwanese tajik tanzanian thai tibetan togolese
    tongan trinidadian tunisian turkish turkmen ugandan ukrainian uruguayan uzbek venezuelan
    vietnamese welsh yemeni zambian zimbabwean arab arabic african european caribbean
    scandinavian slavic balkan middle-eastern chinese-american korean-american
    mexican-american indian-american japanese-american african-american asian-american
    italian-american irish-american""".split()
)
_APPEARANCE = {
    "pretty",
    "attractive",
    "beautiful",
    "handsome",
    "cute",
    "gorgeous",
    "hot",
    "sexy",
    "ugly",
    "unattractive",
    "overweight",
    "fat",
    "skinny",
    "obese",
    "chubby",
    "petite",
    "sweet",
    "plus-size",
}
# Where someone comes from, said as a noun or a phrase rather than an adjective.
ORIGIN_NOUNS = {
    "immigrant": "person",
    "immigrants": "people",
    "migrant": "person",
    "migrants": "people",
    "refugee": "person",
    "refugees": "people",
    "expat": "person",
    "expats": "people",
    "foreigner": "person",
    "foreigners": "people",
}
_ORIGIN_PHRASES = re.compile(
    r"(?:,?\s+and\s+|,\s+)?(?:who\s+)?(?:speaks|speaking)\s+English\s+as\s+(?:a|his|her|their)\s+"
    r"(?:second|third|foreign)\s+language"
    r"|\bnon-native(?:\s+English)?(?:\s+speaker)?\b"
    r"|(?:,?\s+and\s+|,\s+)?(?:who\s+)?(?:has|with)\s+an?\s+(?:heavy|strong|thick|foreign|slight)\s+accent"
    r"(?:\s+on\s+the\s+phone)?",
    re.I,
)
_CLASS = re.compile(
    r"\b(?:Harvard|Yale|Princeton|Stanford|MIT|Oxford|Cambridge|Ivy[- ]League)[- ]"
    r"(?:educated|trained)\b"
    r"|,?\s*an?\s+(?:sophomore|freshman|junior|senior|student|dropout)\s+at\s+a\s+community\s+college"
    r"|\b(?:an?\s+)?(?:Harvard|Yale|Princeton|Stanford|MIT|Oxford|Cambridge)\s+"
    r"(?:graduate|grad|alum|alumnus|alumna)\s+(?=building|launching|running|working|pitching)",
)
# List items that describe a person: "Assess this candidate: 45, divorced, two kids, ..."
_LIST_AGE = re.compile(r"(?<=[:,]\s)(?:1[89]|[2-9]\d)(?:,\s+)(?=[a-z])")
_LIST_FAMILY = re.compile(
    r"(?<=[:,]\s)(?:married|divorced|widowed|separated|single|childless|"
    r"(?:no|one|two|three|four|five|six|\d)\s+(?:kids|children|sons|daughters))(?:,\s+)(?=[a-z0-9])",
)
# A parent counted: "a mother of two" is a description of family, not of work.
_PARENT_OF = re.compile(
    r"\b(?:mother|father|mom|mum|dad|parent)\s+of\s+(?:one|two|three|four|five|six|\d+)\b", re.I
)

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


def _inside(start: int, spans) -> bool:
    return any(s.start <= start < s.end for s in spans)


def _has_person_subject(verb) -> bool:
    subjects = [c for c in verb.children if c.dep_ in ("nsubj", "nsubjpass")]
    return any(
        s.lower_ in ("he", "she", "they", "i", "we", "you") or _is_person(s) for s in subjects
    )


def detect_attributes(prompt: str, claimed: list[Span] | None = None) -> list[Finding]:
    """Every description of a person in the prompt, outside quoted work.

    `claimed` are spans already found by name detection; nothing overlapping them is
    returned, so a name and a description are never replaced twice.
    """
    from neutral.detect import _model
    from neutral.work import work_spans

    quoted = work_spans(prompt)
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
    for match in _ORIGIN_PHRASES.finditer(prompt):
        add(match.start(), match.end(), ORIGIN)
    for match in _CLASS.finditer(prompt):
        add(match.start(), match.end(), CLASS)
    for match in _LIST_AGE.finditer(prompt):
        add(match.start(), match.end(), AGE)
    for match in _LIST_FAMILY.finditer(prompt):
        add(match.start(), match.end(), FAMILY)
    for match in _PARENT_OF.finditer(prompt):
        add(match.start(), match.end(), FAMILY)

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
            if low in ORIGIN_NOUNS:
                add(start, end, ORIGIN)
                # "an immigrant from Mexico": where from goes with it.
                for child in token.rights:
                    if child.dep_ == "prep" and child.lower_ == "from":
                        tail = max(t.idx + len(t.text) for t in child.subtree)
                        add(child.idx - 1, tail, ORIGIN)
                continue

        # An age said beside a name or a person: "Ms. Nguyen, 58, and", "candidate: 45,".
        if token.like_num and token.dep_ == "appos" and _is_person(head):
            try:
                years = int(token.text)
            except ValueError:
                years = 0
            if 18 <= years <= 99:
                before = prompt[:start]
                lead = len(before) - len(before.rstrip(" ,"))
                if before.rstrip(" ").endswith(","):
                    add(start - lead, end, AGE)
                continue

        # Said of a person after "is": "He's Polish", "She's 21", "They are gorgeous".
        if token.dep_ in ("attr", "acomp") and _has_person_subject(head):
            if low in DEMONYMS or low in _RACES or token.ent_type_ in ("NORP", "LANGUAGE"):
                add(start, end, ORIGIN if low not in _RELIGIONS else RELIGION)
                continue
            if low in _APPEARANCE:
                add(start, end, APPEARANCE)
                continue
            if low in _ORIENTATIONS:
                add(start, end, ORIENTATION)
                continue
            if token.like_num and token.text.isdigit() and 18 <= int(token.text) <= 99:
                add(start, end, AGE)
                for child in token.children:  # "She's 21, super sweet and pretty"
                    if child.lower_ in _APPEARANCE:
                        add(child.idx, child.idx + len(child.text), APPEARANCE)
                        for c in child.conjuncts:
                            if c.lower_ in _APPEARANCE:
                                add(c.idx, c.idx + len(c.text), APPEARANCE)
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
        elif low in _APPEARANCE:
            add(start, end, APPEARANCE)
        elif low in DEMONYMS:
            add(start, end, ORIGIN)
        elif low in _GENDER_MODIFIERS:
            add(start, end, GENDER)
        elif low in _RELIGIONS:
            add(start, end, RELIGION)
        elif low in _ORIENTATIONS:
            add(start, end, ORIENTATION)
        elif low in _RACES or (token.ent_type_ in ("NORP", "LANGUAGE") and low not in _RELIGIONS):
            add(start, end, ORIGIN)

    return sorted(found, key=lambda f: f.span.start)
