"""Mechanism 3 - person neutralisation.

CLAUDE.md section 7: *"First-person framing ("my essay", "I wrote") signals to the model
that the user is the author, which triggers favourable treatment. Convert to third-person
neutral framing, and convert back on the way out."*

This is the sycophancy half of the product. Mechanism 1 cannot touch it: there is no name
to substitute in "I wrote this and I am thinking of publishing it".

**The thing that makes this dangerous, and the rule that makes it safe.**

A prompt that asks for a piece of work to be assessed contains that work. A cover letter
is full of "I am writing to express my strong interest"; a late-project email is full of
"I know this is not what you want to hear". Converting those would rewrite the very thing
the user asked to have judged, and hand the model a document nobody wrote.

So this mechanism never touches the artifact. It edits only the framing around it - the
sentences where the user says whose work it is - and treats anything inside a quoted
block or an indented block as untouchable. If the boundaries cannot be worked out, it
does nothing at all, which is the S4 answer: fail open to the original.

**Both directions converge on the same wording.** "I wrote this" and "a colleague wrote
this" both become "the author wrote this". Neutralising only the first-person side would
leave the two halves of a matched pair still different, and measure nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from neutral.core import Segment, SegmentKind, Span, TransformRecord
from neutral.policy import POLICY_NAME, POLICY_VERSION

NAME = "person_neutralisation"

# What both framings become. A definite noun phrase rather than a placeholder, because
# the model has to keep reading this as a person who wrote something.
REFERENT = "the author"
POSSESSIVE = "the author's"

# Any other self-reference. "the author" would claim authorship where there is none -
# "How should the author structure a review?" asks a different question - so a person
# talking about their own situation becomes "the asker", which claims nothing.
# Any other self-reference becomes one more person, labelled like everyone else.
#
# The first attempt used "the asker", which the founder rejected on sight: it announces
# that the question is about the person typing, which is exactly what this mechanism
# exists to hide. "Person B thinks Person B's manager is unfair" is somebody else to the
# model. The orchestrator chooses the letter so it follows the people Mechanism 1 has
# already named; used on its own, this defaults to the first.
DEFAULT_SELF_LABEL = "Person A"

# Inside these, nothing is touched: this is the work being assessed.
_QUOTED = re.compile(r'"[^"]*"|\u201c[^\u201d]*\u201d', re.S)
_INDENTED = re.compile(r"(?:^[ \t]*(?:    |\t)\S[^\n]*\n?)+", re.M)

# The gate. Without it this mechanism fires on any "I" at all, and "How should I
# structure a review?" becomes "How should the author structure a review?" - a different
# question, asked on behalf of nobody. CLAUDE.md section 7 is specific: the signal being
# removed is *"my essay", "I wrote"* - a claim to have made the thing being assessed. No
# such claim, nothing to neutralise.
_AUTHORSHIP_VERBS = (
    r"wrote|write|written|drafted|drafting|made|making|built|building|created|creating|designed|"
    r"authored|produced|prepared|put together|came up with|have written|'ve written"
)
# "report" is deliberately not on this list. In the first market for this tool it far
# more often means a person - "my report is asking about promotion" - and turning a
# question about someone's career into "the author's report" is a much worse failure
# than missing one way of saying "my document". When a word is ambiguous, the mechanism
# that edits text should be the one that stands down.
_ARTIFACT_NOUNS = (
    r"essay|draft|email|e-mail|letter|code|memo|writing|passage|function|post|"
    r"article|proposal|deck|slides?|plan|summary|note|notes|script|spec|résumé|resume|cv|"
    r"pitch|cover letter|blurb|paragraph|section|chapter|answer|response|bio|readme"
)
_CLAIMS = re.compile(
    # "I wrote", "a colleague drafted", "we built"
    rf"\b(?:I|we|a\s+colleague|my\s+colleague|the\s+colleague|a\s+coworker|a\s+friend)\s+"
    rf"(?:{_AUTHORSHIP_VERBS})\b"
    # "my essay", "a colleague's draft", "our report"
    rf"|\b(?:my|our|a\s+colleague's|my\s+colleague's|the\s+colleague's)\s+"
    rf"(?:{_ARTIFACT_NOUNS})\b"
    # "written by me", "drafted by a colleague"
    rf"|\b(?:{_AUTHORSHIP_VERBS})\s+by\s+(?:me|us|a\s+colleague)\b",
    re.I,
)


def claims_authorship(prompt: str, protected: list[Span] | None = None) -> bool:
    """Does this prompt say who made the thing it is asking about?"""
    if protected is None:
        protected = protected_spans(prompt)
    return any(not _inside(m.start(), protected) for m in _CLAIMS.finditer(prompt))


# First person, optionally with the auxiliary that has to change number with it. The
# auxiliary is part of the match so that "I am" becomes "the author is" in one piece,
# rather than "the author am".
_FIRST = re.compile(
    # The contraction first. "\bI\b" matches the I of "I'm" and leaves "'m" behind,
    # which is how "The author'm unsure" happened.
    r"\b(I)('m|'ve|'ll|'d)\b"
    r"|\b(I)\b(\s+(?:am|have|will|would|do|was|had|can|could|should|must))?"
    r"|\b(me|my|mine|myself)\b",
    re.I,
)

# The other side of the same coin: the stand-in author a matched pair uses instead.
_COLLEAGUE = re.compile(
    r"\b(?:a|my|the|our)\s+(colleague|coworker|co-worker|friend|teammate)(?:'s)?\b"
    r"|\b(colleague|coworker|co-worker|teammate)(?:'s)?\b",
    re.I,
)

# Once a stand-in author is established, pronouns in the framing refer to them.
_THEY = re.compile(
    r"\b(they)('re|'ve|'ll|'d)\b"
    r"|\b(they)\b(\s+(?:are|have|were|will|would|do|can|could|should|must))?"
    r"|\b(them|their|theirs|themselves)\b",
    re.I,
)

_AGREEMENT = {
    "am": "is",
    "are": "is",
    "have": "has",
    "'ve": "has",
    "'m": "is",
    "'re": "is",
    "do": "does",
    "were": "was",
    "'ll": "will",
    "'d": "would",
}
_POSSESSIVE_WORDS = {"my", "mine", "their", "theirs"}


@dataclass
class PersonRef:
    """One reference to the author, in the framing rather than in the work."""

    span: Span
    text: str
    replacement: str
    kind: str


@dataclass
class Neutralisation:
    segments: tuple[Segment, ...] = ()
    transforms: tuple[TransformRecord, ...] = ()
    # Added to the identity map so restore() turns the answer back. Longest key first is
    # handled by restore itself.
    restoration: dict[str, str] = field(default_factory=dict)
    framing: str = ""
    # For restore(): which phrase stands for the asker, and what it becomes on the way
    # back. Empty when nothing was changed.
    asker: dict[str, str] = field(default_factory=dict)


def protected_spans(prompt: str) -> list[Span]:
    """The parts of the prompt that are the work itself, and are never edited."""
    spans = [Span(m.start(), m.end()) for m in _QUOTED.finditer(prompt)]
    spans += [Span(m.start(), m.end()) for m in _INDENTED.finditer(prompt)]
    return sorted(spans, key=lambda s: s.start)


def _inside(position: int, protected: list[Span]) -> bool:
    return any(s.start <= position < s.end for s in protected)


def _starts_sentence(prompt: str, at: int) -> bool:
    """True when the replacement will begin a sentence and needs a capital."""
    before = prompt[:at].rstrip()
    return not before or before[-1] in ".!?:\n"


def _cased(word: str, capital: bool) -> str:
    return word[0].upper() + word[1:] if capital else word


def _replacement_for(matched: str, prompt: str, start: int, *, pronoun: bool) -> str:
    """What one matched reference becomes, with number and capitalisation sorted out.

    `pronoun` says whether a following word could be an auxiliary that has to change
    number - "I am" does, "a colleague" does not. Treating them the same turned
    "A colleague" into "The author colleague", which is how this argument came to exist.
    """
    words = matched.split()
    capital = _starts_sentence(prompt, start)
    possessive = words[0].lower().rstrip(",.") in _POSSESSIVE_WORDS or matched.rstrip().endswith(
        "'s"
    )
    out = _cased(POSSESSIVE if possessive else REFERENT, capital)

    if not pronoun:
        return out

    # A contraction is one token: "I'm" splits into I + 'm, not two words.
    contraction = re.match(r"^\w+('m|'ve|'ll|'re|'d)$", matched, re.I)
    if contraction:
        return f"{out} {_AGREEMENT[contraction.group(1).lower()]}"
    if len(words) > 1:
        tail = words[1].lower()
        return f"{out} {_AGREEMENT.get(tail, tail)}"
    return out


# First person to third, for the word that agrees with "I". Only a handful of English
# verbs are irregular in the third person singular present; the rest follow spelling.
_THIRD_IRREGULAR = {
    "am": "is",
    "are": "is",
    "have": "has",
    "do": "does",
    "go": "goes",
    "'m": " is",
    "'re": " is",
    "'ve": " has",
}
# Contractions hanging off "I" that would read wrongly after "the asker".
_EXPAND = {"'ll": " will", "'d": " would"}


def _third_person(word: str) -> str:
    low = word.lower()
    if low in _THIRD_IRREGULAR:
        out = _THIRD_IRREGULAR[low]
    elif low.endswith(("s", "x", "z", "ch", "sh", "o")):
        out = word + "es"
    elif len(low) > 1 and low.endswith("y") and low[-2] not in "aeiou":
        out = word[:-1] + "ies"
    else:
        out = word + "s"
    return out[0].upper() + out[1:] if word[:1].isupper() else out


def _agreeing(subject) -> list:
    """The finite verbs that agree with this "I", so they can move to the third person.

    The first auxiliary when there is one ("I have been", "Do I", "I'm"), otherwise the
    verb itself, plus any verb joined to it that has no subject of its own ("I think and
    feel"). Past forms need no change and are never returned.
    """
    head = subject.head
    auxes = sorted(
        (c for c in head.children if c.dep_ in ("aux", "auxpass") and c.tag_ == "VBP"),
        key=lambda t: t.i,
    )
    if auxes:
        return auxes[:1]
    if head.tag_ != "VBP":
        return []
    found = [head]
    # The parser often tags the joined verb as a bare "VB" ("I watch and wait"); joined to
    # a present-tense verb with no subject of its own, it shares that verb's subject.
    for conj in head.conjuncts:
        if conj.tag_ in ("VBP", "VB") and not any(
            c.dep_.startswith("nsubj") for c in conj.children
        ):
            found.append(conj)
    return found


def _first_person_refs(
    prompt: str, protected: list[Span], referent: str, possessive: str
) -> list[PersonRef] | None:
    """Every I, me, my, mine and myself outside the work, with the grammar made to agree.

    Returns None when the parser is unavailable: without it there is no reliable way to
    make "I think" into "the asker thinks", and a prompt with broken grammar is worse
    than one left in the first person.
    """
    from neutral.detect import _model

    nlp = _model()
    if nlp is None:
        return None

    doc = nlp(prompt)
    refs: list[PersonRef] = []

    def add(start: int, end: int, replacement: str, kind: str) -> None:
        refs.append(
            PersonRef(
                span=Span(start, end),
                text=prompt[start:end],
                replacement=replacement,
                kind=kind,
            )
        )

    for token in doc:
        low = token.lower_
        if low not in ("i", "me", "my", "mine", "myself") or token.tag_ not in ("PRP", "PRP$"):
            continue
        if _inside(token.idx, protected):
            continue
        capital = _starts_sentence(prompt, token.idx)
        start, end = token.idx, token.idx + len(token.text)

        if low in ("my", "mine"):
            add(start, end, _cased(possessive, capital), "first_person")
        elif low == "me":
            add(start, end, _cased(referent, capital), "first_person")
        elif low == "myself":
            if token.dep_ in ("dobj", "pobj", "dative", "attr"):
                add(start, end, _cased(referent, capital), "first_person")
            else:
                # Emphatic ("I myself think"): it carries nothing, so it is removed with
                # the space before it rather than doubled into "the asker the asker".
                gap = len(prompt[:start]) - len(prompt[:start].rstrip())
                add(start - gap, end, "", "first_person")
        else:  # "I"
            add(start, end, _cased(referent, capital), "first_person")
            following = doc[token.i + 1] if token.i + 1 < len(doc) else None
            if following is not None and not token.whitespace_ and following.lower_ in _EXPAND:
                f_start = following.idx
                add(f_start, f_start + len(following.text), _EXPAND[following.lower_], "agreement")
            if token.dep_ in ("nsubj", "nsubjpass"):
                for verb in _agreeing(token):
                    if _inside(verb.idx, protected):
                        continue
                    v_start = verb.idx
                    add(v_start, v_start + len(verb.text), _third_person(verb.text), "agreement")
    return refs


def find_person_refs(
    prompt: str, self_label: str = DEFAULT_SELF_LABEL
) -> tuple[list[PersonRef], str]:
    """Every reference the asker makes to themselves, and which framing the prompt used.

    Framings:
      first_person  - the asker claims to have made the thing being judged; they become
                      "the author", because that claim is what invites flattery
      third_person  - a matched pair's other half: "a colleague wrote this"; also "the
                      author", so the two halves converge
      asker         - any other self-reference: "I think my manager is unfair to me"
                      becomes "Person B thinks Person B's manager is unfair to Person B"

    Never returns a reference inside the work being assessed.
    """
    protected = protected_spans(prompt)
    authorship = claims_authorship(prompt, protected)
    referent, possessive = (REFERENT, POSSESSIVE) if authorship else (self_label, f"{self_label}'s")

    refs: list[PersonRef] = []
    first = _first_person_refs(prompt, protected, referent, possessive)
    if first is None:
        # No parser: fall back to the narrow rule-based version, which only touches an
        # explicit claim of authorship and handles its own few auxiliaries.
        if not authorship:
            return [], ""
        first = [
            PersonRef(
                span=Span(m.start(), m.end()),
                text=m.group(0),
                replacement=_replacement_for(m.group(0), prompt, m.start(), pronoun=True),
                kind="first_person",
            )
            for m in _FIRST.finditer(prompt)
            if not _inside(m.start(), protected)
        ]
    refs.extend(first)

    colleague = (
        [m for m in _COLLEAGUE.finditer(prompt) if not _inside(m.start(), protected)]
        if authorship
        else []
    )
    for match in colleague:
        refs.append(
            PersonRef(
                span=Span(match.start(), match.end()),
                text=match.group(0),
                replacement=_replacement_for(match.group(0), prompt, match.start(), pronoun=False),
                kind="stand_in_author",
            )
        )
    # Pronouns only count once a stand-in author has been named, otherwise "they" in a
    # prompt about somebody else entirely would be swept up with it.
    if colleague:
        for match in _THEY.finditer(prompt):
            if _inside(match.start(), protected):
                continue
            refs.append(
                PersonRef(
                    span=Span(match.start(), match.end()),
                    text=match.group(0),
                    replacement=_replacement_for(
                        match.group(0), prompt, match.start(), pronoun=True
                    ),
                    kind="stand_in_pronoun",
                )
            )

    if not refs:
        return [], ""

    firsts = sum(1 for r in refs if r.kind == "first_person")
    if not authorship:
        framing = "asker"
    else:
        framing = "first_person" if firsts >= len(colleague) else "third_person"

    refs.sort(key=lambda r: (r.span.start, r.span.end))
    # Overlaps would produce segments that double-count characters of the original.
    kept: list[PersonRef] = []
    for ref in refs:
        if kept and ref.span.start < kept[-1].span.end:
            continue
        kept.append(ref)
    return kept, framing


def apply(
    prompt: str,
    refs: list[PersonRef],
    framing: str,
    self_label: str = DEFAULT_SELF_LABEL,
) -> Neutralisation:
    """Turn the framing third-person, leaving the work exactly as it was written."""
    if not refs:
        return Neutralisation(segments=(Segment(SegmentKind.COPY, Span(0, len(prompt)), prompt),))

    segments: list[Segment] = []
    transforms: list[TransformRecord] = []
    cursor = 0
    for ref in refs:
        if ref.span.start > cursor:
            span = Span(cursor, ref.span.start)
            segments.append(Segment(SegmentKind.COPY, span, span.text_in(prompt)))
        segments.append(Segment(SegmentKind.REPLACE, ref.span, ref.replacement, mechanism=NAME))
        transforms.append(
            TransformRecord(
                mechanism=NAME,
                detected=ref.text,
                detected_kind=ref.kind,
                replacement=ref.replacement,
                source=ref.span,
                policy=POLICY_NAME,
                policy_version=POLICY_VERSION,
                reason={
                    "first_person": (
                        "first-person framing tells the model the question is about the "
                        "asker's own work or situation, which it treats more kindly"
                    ),
                    "agreement": "the verb follows its subject into the third person",
                    "stand_in_author": "a stand-in author is the same signal from the other side",
                    "stand_in_pronoun": "a stand-in author is the same signal from the other side",
                }.get(ref.kind, "part of the same change"),
            )
        )
        cursor = ref.span.end
    if cursor < len(prompt):
        span = Span(cursor, len(prompt))
        segments.append(Segment(SegmentKind.COPY, span, span.text_in(prompt)))

    # What the answer's "the author" or "Person B" becomes. Both cases are registered
    # because the model capitalises "the author" at the start of a sentence.
    referent, possessive = (
        (self_label, f"{self_label}'s") if framing == "asker" else (REFERENT, POSSESSIVE)
    )
    subject = "your colleague" if framing == "third_person" else "you"
    owner = "your colleague's" if framing == "third_person" else "your"
    restoration = {
        possessive: owner,
        possessive.capitalize(): owner.capitalize(),
        referent: subject,
        referent.capitalize(): subject.capitalize(),
    }
    return Neutralisation(
        segments=tuple(segments),
        transforms=tuple(transforms),
        restoration=restoration,
        framing=framing,
        asker={"referent": referent, "possessive": possessive, "as": subject, "owner": owner},
    )
