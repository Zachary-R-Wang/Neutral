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
    from neutral.work import work_spans

    return work_spans(prompt)


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


# Verbs that read naturally without their "me": "Give 5 ideas", "Write a plan", "Find a
# course". "Tell me what to say" does not, so "tell" keeps a label instead.
_DROPPABLE = {
    "give",
    "show",
    "send",
    "find",
    "get",
    "make",
    "write",
    "draft",
    "create",
    "suggest",
    "recommend",
    "list",
    "build",
    "plan",
    "help",
}


def _asks_the_assistant(me) -> bool:
    """Whether this "me" is only the receiver of a request to the assistant.

    "Give me interview questions", "Tell me what to say", "Can you help me with this?" -
    the "me" says nothing about who the person is; it is how anyone asks for anything.
    Turned into "Give Person A interview questions" it only made the prompt stranger.
    """
    verb = me.head
    if verb.dep_ == "prep":  # "write this for me"
        verb = verb.head
    if me.dep_ == "nsubj" and verb.dep_ in ("ccomp", "xcomp"):
        verb = verb.head  # "help me write", "let me know": the request is the outer verb
    if verb.pos_ not in ("VERB", "AUX"):
        return False
    subjects = [c for c in verb.children if c.dep_ in ("nsubj", "nsubjpass") and c != me]
    if subjects:
        return all(s.lower_ == "you" for s in subjects)
    return verb.tag_ == "VB" and not any(c.dep_ in ("aux", "auxpass") for c in verb.children)


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

    # Whether the person asking is labelled anywhere other than a "give me": then a "give
    # me" would give the label away.
    labelled_elsewhere = any(
        t.lower_ in ("i", "my", "mine", "myself")
        or (t.lower_ == "me" and not _asks_the_assistant(t))
        for t in doc
        if t.tag_ in ("PRP", "PRP$") and not _inside(t.idx, protected)
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
            if _asks_the_assistant(token):
                if not labelled_elsewhere:
                    continue
                # Anywhere else the person asking is "Person A", "Give me" would say who
                # Person A is. Where the verb reads without it, "me" goes; otherwise it
                # takes the label like every other "me".
                verb = token.head
                if token.dep_ == "nsubj" and verb.dep_ in ("ccomp", "xcomp"):
                    verb = verb.head  # "help me write": the request is "help"
                if verb.lemma_ in _DROPPABLE and token.dep_ in ("dative", "dobj", "nsubj"):
                    gap = len(re.match(r"\s*", prompt[end:]).group(0))
                    add(start, end + gap, "", "first_person")
                    continue
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
    prompt: str, self_label: str = DEFAULT_SELF_LABEL, *, as_author: bool = True
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
    # In a request for a verdict the work has been made nobody's ("the code"), so a claim
    # to have written it is not restated as "the author" - that would say it again.
    authorship = as_author and claims_authorship(prompt, protected)
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


# --------------------------------------------------------------------------------------
# "as a philosopher": the person asking, described without an "I"
# --------------------------------------------------------------------------------------
#
# "20 best questions to ask as a philosopher to a model" says who is asking as plainly as
# "I am a philosopher", and there is no "I" for the rules above to find. Found by the
# founder on 2026-09-28, after descriptions of other people had been dealt with.
#
# The role is what shapes the task, so it is kept, but it stops being the asker's:
#   a discipline that only sets the kind of question becomes the kind of question
#       "questions to ask as a philosopher"  -> "philosophical questions to ask"
#   anything else becomes somebody else
#       "tips to negotiate as a woman in tech" -> "tips for a woman in tech to negotiate"
#       "how to give feedback as a new manager" -> "how a new manager should give feedback"
# When the prompt also says "I" or "my", that person already has a label, and the label
# is used: "what Person A should say as a junior engineer when Person A's lead is wrong".
#
# Every word in the result comes from the original: the role is moved, not written, and
# only "for", "should" and the adjective stand in for words that were there ("as", "to",
# the role itself).

DISCIPLINES = {
    "philosopher": "philosophical",
    "psychologist": "psychological",
    "historian": "historical",
    "economist": "economic",
    "sociologist": "sociological",
    "scientist": "scientific",
    "ethicist": "ethical",
    "theologian": "theological",
    "anthropologist": "anthropological",
    "linguist": "linguistic",
    "journalist": "journalistic",
    "lawyer": "legal",
    "doctor": "medical",
    "physician": "medical",
    "mathematician": "mathematical",
    "biologist": "biological",
    "technologist": "technical",
}
_QUESTION_NOUNS = {"question", "topic", "prompt"}
ROLE_KIND = "asker_role"


@dataclass(frozen=True)
class AskerRole:
    phrase: Span  # "as a philosopher", from "as" to the end of the role
    role_span: Span  # "a philosopher"
    role_noun: Span  # "philosopher"
    to: Span  # the "to" of the infinitive
    shape: str  # "noun" ("questions to ask") or "wh" ("how to give")
    head_noun: Span | None  # "questions", for shape "noun"
    head_lemma: str
    drop_to: Span | None  # "to " in "ask ... to a model", which "ask" does not take


def find_asker_roles(prompt: str, protected: list[Span] | None = None) -> list[AskerRole]:
    """Every "as a <role>" that describes the person asking, in a request with no "I"."""
    from neutral.detect import _model
    from neutral.detect_attributes import _is_person

    nlp = _model()
    if nlp is None:
        return []
    protected = protected if protected is not None else protected_spans(prompt)
    doc = nlp(prompt)
    found: list[AskerRole] = []
    for as_ in doc:
        if as_.lower_ != "as" or as_.dep_ != "prep" or _inside(as_.idx, protected):
            continue
        verb = as_.head
        if verb.pos_ == "NOUN" and verb.dep_ == "dobj":
            # "how to handle microaggressions as a Black woman": the parser hangs the role
            # on the object; it belongs to the verb.
            verb = verb.head
        if verb.tag_ != "VB" or any(c.dep_.startswith("nsubj") for c in verb.children):
            continue
        to = [c for c in verb.children if c.dep_ == "aux" and c.tag_ == "TO"]
        roles = [c for c in as_.children if c.dep_ == "pobj" and c.pos_ == "NOUN"]
        if not to or not roles:
            continue
        noun = roles[0]
        det = [c for c in noun.lefts if c.dep_ == "det" and c.lower_ in ("a", "an")]
        if not det or not _is_person(noun):
            continue  # "as a result", "as an example", "as a team"

        end = noun.idx + len(noun.text)
        drop_to = None
        for right in noun.rights:
            if right.dep_ == "prep" and right.lower_ == "to":
                # "ask as a philosopher to a model": "to a model" is the verb's, whatever
                # the parser says, and is not part of the role.
                if verb.lemma_ in ("ask", "pose", "put"):
                    drop_to = Span(right.idx, right.idx + len(right.text) + 1)
                break
            end = max(end, max(t.idx + len(t.text) for t in right.subtree))

        if verb.dep_ in ("relcl", "acl") and verb.head.pos_ == "NOUN" and verb.head.i < verb.i:
            shape, head = "noun", verb.head
        elif any(t.tag_ in ("WRB", "WP") and t.i < to[0].i for t in verb.subtree):
            shape, head = "wh", None
        else:
            continue
        found.append(
            AskerRole(
                phrase=Span(as_.idx, end),
                role_span=Span(det[0].idx, end),
                role_noun=Span(noun.idx, noun.idx + len(noun.text)),
                to=Span(to[0].idx, to[0].idx + len(to[0].text)),
                shape=shape,
                head_noun=Span(head.idx, head.idx + len(head.text)) if head is not None else None,
                head_lemma=head.lemma_.lower() if head is not None else "",
                drop_to=drop_to,
            )
        )
    return found


def _cut(segments, original: str, points: list[int]) -> list[Segment]:
    """Split untouched segments at these offsets, so each piece can be moved on its own."""
    out: list[Segment] = []
    for s in segments:
        if s.kind is not SegmentKind.COPY or s.source is None:
            out.append(s)
            continue
        start = s.source.start
        for p in sorted(p for p in set(points) if s.source.start < p < s.source.end):
            out.append(Segment(SegmentKind.COPY, Span(start, p), original[start:p]))
            start = p
        out.append(
            Segment(SegmentKind.COPY, Span(start, s.source.end), original[start : s.source.end])
        )
    return out


def _within(segment: Segment, span: Span) -> bool:
    return (
        segment.source is not None
        and span.start <= segment.source.start
        and (segment.source.end <= span.end)
    )


def apply_asker_roles(
    original: str, segments, roles: list[AskerRole], label: str | None
) -> tuple[tuple[Segment, ...], list[TransformRecord]]:
    """Move each role off the person asking. `label` is the asker's, if they have one."""
    segments = list(segments)
    transforms: list[TransformRecord] = []
    for role in roles:
        gap_after = original[role.phrase.end : role.phrase.end + 1] == " "
        gap_before = original[role.phrase.start - 1 : role.phrase.start] == " "
        points = [
            role.phrase.start,
            role.phrase.end,
            role.role_span.start,
            role.to.start,
            role.to.end,
        ]
        if gap_after:
            points.append(role.phrase.end + 1)
        if gap_before:
            points.append(role.phrase.start - 1)
        if role.head_noun:
            points.append(role.head_noun.start)
        if role.drop_to:
            points += [role.drop_to.start, role.drop_to.end]
        segments = _cut(segments, original, points)

        # Anything inside the phrase that a mechanism has already changed stays changed.
        role_segments = [s for s in segments if _within(s, role.role_span)]
        rendered_role = "".join(s.text for s in role_segments).strip()
        # "as a 45-year-old" with the age removed leaves "a": nobody is left to move.
        if not re.sub(r"^(?:an?|the)\b", "", rendered_role, flags=re.I).strip():
            rendered_role = ""
        role_word = original[role.role_noun.start : role.role_noun.end].lower()
        adjective = DISCIPLINES.get(role_word)

        # The whole phrase and one space beside it leave their place, in every case but
        # the one where a label already stands for the asker and the role can stay put.
        removed = Span(
            role.phrase.start - (1 if gap_before and not gap_after else 0),
            role.phrase.end + (1 if gap_after else 0),
        )
        before_to: list[Segment] = []
        to_text = None
        head_prefix = None
        if label:
            if role.shape == "noun":
                to_text = f"for {label} to"
            else:
                to_text = f"{label} should"
            removed = None
        elif role.shape == "noun" and adjective and role.head_lemma in _QUESTION_NOUNS:
            head_prefix = f"{adjective} "
        elif role.shape == "noun":
            before_to = [
                Segment(
                    SegmentKind.REPLACE,
                    Span(role.phrase.start, role.phrase.start + 2),
                    "for ",
                    NAME,
                ),
                *role_segments,
                Segment(SegmentKind.REPLACE, Span(removed.end - 1, removed.end), " ", NAME),
            ]
        else:
            before_to = [
                *role_segments,
                Segment(SegmentKind.REPLACE, Span(removed.start, removed.start + 1), " ", NAME),
            ]
            to_text = "should"
        if not rendered_role:
            # Every word of the role was a description the task did not need: there is
            # nobody left to move, so the phrase simply goes.
            before_to, to_text, head_prefix = [], None, None

        out: list[Segment] = []
        for s in segments:
            if removed and _within(s, removed):
                continue
            if role.drop_to and not label and _within(s, role.drop_to):
                continue
            if (
                role.head_noun
                and head_prefix
                and s.source == Span(role.head_noun.start, s.source.end)
                and s.source.start == role.head_noun.start
            ):
                out.append(Segment(SegmentKind.REPLACE, role.role_noun, head_prefix, NAME))
            if (
                s.source is not None
                and s.source.start == role.to.start
                and s.kind is SegmentKind.COPY
            ):
                out.extend(before_to)
                if to_text:
                    out.append(Segment(SegmentKind.REPLACE, role.to, to_text, NAME))
                    continue
            out.append(s)
        new_text = "".join(s.text for s in out)
        if new_text == "".join(s.text for s in segments):
            continue
        segments = out
        transforms.append(
            TransformRecord(
                mechanism=NAME,
                detected=original[role.phrase.start : role.phrase.end],
                detected_kind=ROLE_KIND,
                replacement=(
                    head_prefix.strip()
                    if head_prefix
                    else (to_text or "")
                    if label
                    else f"{rendered_role} (moved)"
                ),
                source=role.phrase,
                policy=POLICY_NAME,
                policy_version=POLICY_VERSION,
                reason=(
                    "a description of the person asking: the role is kept for the task, "
                    "but no longer belongs to whoever is typing"
                ),
            )
        )
    return tuple(segments), transforms
