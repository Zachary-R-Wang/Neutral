"""Mechanism 1 - identity substitution.

Personal names and the gendered pronouns bound to them are replaced with neutral,
consistent placeholders, so the model cannot condition on who the people are. Reversed on
the way out.

Two details matter more than they look.

**Names are grouped before they are replaced.** A prompt that says "Emily Carter" once and
"Emily" three times is talking about one person, and must produce one placeholder. Giving
those two spellings separate placeholders would tell the model there are two people, which
is inventing a fact - exactly what S1 forbids.

**Every character of the output is emitted as a segment.** Nothing is produced by string
replacement on the original. The rewritten prompt is built from segments that each declare
where they came from, so S1 can be proved by reconstruction rather than trusted.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass, field

from neutral.core import Segment, SegmentKind, Span, TransformRecord
from neutral.detect import TITLES, Finding
from neutral.policy import POLICY_NAME, POLICY_VERSION

MECHANISM = "identity_substitution"

NEUTRAL_PRONOUN = {
    "subject": "they",
    "object": "them",
    "possessive": "their",
    "possessive_noun": "theirs",
    "reflexive": "themselves",
}

_FORM = {
    "he": "subject",
    "she": "subject",
    "him": "object",
    "his": "possessive",
    "her": "ambiguous",
    "hers": "possessive_noun",
    "himself": "reflexive",
    "herself": "reflexive",
}

# "her" is two different words. After one of these, it is the object ("tell her", "for
# her"); before a noun it is possessive ("her review"). This is a heuristic, not grammar,
# and its failures are a Phase 3 problem - restoration quality - not a Phase 1 one.
_TAKES_OBJECT = {
    "tell",
    "told",
    "give",
    "gave",
    "ask",
    "asked",
    "offer",
    "offered",
    "show",
    "showed",
    "advise",
    "advised",
    "pay",
    "paid",
    "send",
    "sent",
    "help",
    "helped",
    "email",
    "to",
    "for",
    "with",
    "at",
    "by",
    "from",
    "about",
    "of",
    "on",
    "let",
    "made",
    "make",
}

_WORD = re.compile(r"\b[\w']+\b")


@dataclass
class Substitution:
    segments: tuple[Segment, ...] = ()
    transforms: tuple[TransformRecord, ...] = ()
    # placeholder -> the real name. In memory for one request only, then discarded (S5).
    identity_map: dict[str, str] = field(default_factory=dict)
    # placeholder -> which pronoun set the original used, so restoration can put it back.
    pronoun_style: dict[str, str] = field(default_factory=dict)


def _key(name: str) -> frozenset[str]:
    """The word-parts of a name, for deciding whether two spellings are one person.

    Titles are excluded. "Mr Smith" and "Mr Jones" share the word "mr" and nothing else;
    keeping it would merge two people into one placeholder, which tells the model they
    are the same person - inventing a fact rather than removing one.
    """
    cleaned = name.strip(string.punctuation + string.whitespace)
    cleaned = re.sub(r"'s$", "", cleaned, flags=re.I)
    return frozenset(
        w.lower() for w in _WORD.findall(cleaned) if len(w) > 1 and w.lower() not in TITLES
    )


def group_people(findings: list[Finding]) -> dict[int, str]:
    """Map each name finding to a placeholder, merging spellings of the same person."""
    groups: list[set[str]] = []
    assignment: dict[int, int] = {}

    for index, finding in enumerate(findings):
        if finding.kind != "person_name":
            continue
        key = _key(finding.text)
        if not key:
            continue
        for group_index, group in enumerate(groups):
            if key & group:
                group |= key
                assignment[index] = group_index
                break
        else:
            groups.append(set(key))
            assignment[index] = len(groups) - 1

    labels = {g: f"Person {string.ascii_uppercase[g]}" for g in range(len(groups))}
    return {i: labels[g] for i, g in assignment.items()}


# "she is" -> "they are". The forms that do not follow the regular rule; anything else in
# the third person singular goes to the parser's base form ("takes" -> "take").
_TO_PLURAL = {
    "is": "are",
    "was": "were",
    "has": "have",
    "does": "do",
    "'s": "'re",
    "\u2019s": "\u2019re",
}


@dataclass(frozen=True)
class _Edit:
    span: Span
    replacement: str
    detected: str
    kind: str = "agreement"
    reason: str = 'the verb agrees with "they", which replaced a gendered pronoun'


# Why each kind of description is taken out. Shown under "What Neutral changed", so it is
# written for the person reading it.
_ATTRIBUTE_REASONS = {
    "age": "a stated age invites assumptions about ability and attitude",
    "gender": "a gendered word states the person's gender",
    "family": "a family role states the person's gender; the relationship is kept",
    "origin": "nationality, ethnicity or race invites assumptions the task does not need",
    "religion": "religion invites assumptions the task does not need",
    "orientation": "sexual orientation or gender identity is not what the task is about",
    "appearance": "how someone looks is not what the task is about",
    "class": "where someone studied signals class and prestige the task does not need",
}


def _match_case(original: str, word: str) -> str:
    return word[:1].upper() + word[1:] if original[:1].isupper() else word


def _takes_an(word: str) -> bool:
    low = word.lower()
    if re.match(r"(?:8|11\b|18\b|1[18]\d\d\b)", low):
        return True
    if low.startswith(("uni", "use", "usu", "uti", "eu", "one", "once", "ubiq")):
        return False
    if low.startswith(("hour", "honest", "honor", "honour", "heir")):
        return True
    return low[:1] in "aeiou"


def _stands_for_the_person(prompt: str, finding: Finding) -> bool:
    """Whether an age is the noun itself ("a 45-year-old applied"), not a word about one
    ("a 45-year-old engineer"). Only the "-year-old" and "-something" forms can be, and
    only the parser can tell "applied" from "engineer" after them."""
    from neutral.detect import _model

    if not re.search(r"old$|something$", finding.text, re.I):
        return False
    if not re.search(r"\ban?\s+$", prompt[: finding.span.start], re.I):
        return False
    nlp = _model()
    if nlp is None:
        return False
    doc = nlp(prompt)
    last = next(
        (t for t in doc if t.idx < finding.span.end <= t.idx + len(t.text)),
        None,
    )
    if last is None:
        return False
    return not (last.dep_ in ("amod", "compound", "nmod") and last.head.pos_ in ("NOUN", "PROPN"))


def _attribute_edits(prompt: str, findings: list[Finding], allowed: set[int]) -> list[_Edit]:
    """Descriptions of a person, taken out or made neutral, with "a"/"an" put right.

    A gendered or family noun is replaced by its neutral counterpart ("woman" ->
    "person", "mom" -> "parent"), so the sentence keeps its shape and the relationship
    survives. Everything else is removed along with the space beside it, and an article
    left in front of a different sound is corrected: "an 18 year old model" -> "a model".
    """
    from neutral.detect import _model
    from neutral.detect_attributes import (
        ATTRIBUTE_KINDS,
        FAMILY_NOUNS,
        GENDER_NOUNS,
        ORIGIN_NOUNS,
    )

    described = [findings[i] for i in sorted(allowed) if findings[i].kind in ATTRIBUTE_KINDS]
    if not described:
        return []
    nlp = _model()
    doc = nlp(prompt) if nlp is not None else None
    at = {t.idx: t for t in doc} if doc is not None else {}
    covered = [(f.span.start, f.span.end) for f in described]

    def is_described(token) -> bool:
        return any(s <= token.idx and token.idx + len(token.text) <= e for s, e in covered)

    edits: list[_Edit] = []
    handled: set[int] = set()
    for finding in described:
        token = at.get(finding.span.start)
        if token is None or id(finding) in handled:
            continue
        reason = _ATTRIBUTE_REASONS[finding.kind]
        # "Our CEO, a Harvard-educated woman in her 40s, wants...": an aside that is nothing
        # but description goes whole, commas and all.
        if token.dep_ == "appos" or token.head.dep_ == "appos":
            noun = token if token.dep_ == "appos" else token.head
            words = [t for t in noun.subtree if not t.is_punct and t.dep_ != "det"]
            if all(is_described(t) or t.lower_ in ("in", "their", "his", "her") for t in words):
                first = min(t.idx for t in noun.subtree)
                last = max(t.idx + len(t.text) for t in noun.subtree)
                before = re.search(r",\s*$", prompt[:first])
                after = re.match(r"\s*,", prompt[last:])
                if before and after:
                    edits.append(
                        _Edit(
                            Span(before.start(), last + after.end()),
                            "",
                            prompt[first:last],
                            finding.kind,
                            reason,
                        )
                    )
                    for f in described:
                        if first <= f.span.start < last:
                            handled.add(id(f))
                    continue
        # Said of someone after "is": "He is Polish and very direct" -> "He is very direct";
        # "He's Russian and seems honest" -> "He seems honest"; "She's 21, super sweet and
        # pretty, and her skills are excellent" -> "her skills are excellent".
        if token.dep_ in ("attr", "acomp") and token.head.pos_ == "AUX":
            cop = token.head
            pred_end = max(token.subtree, key=lambda t: t.i)
            nxt = doc[pred_end.i + 1] if pred_end.i + 1 < len(doc) else None
            after = doc[nxt.i + 1] if nxt is not None and nxt.i + 1 < len(doc) else None
            if nxt is not None and nxt.lower_ == "and" and after is not None:
                if after.dep_ == "conj" and after.head == cop and after.pos_ == "VERB":
                    start = cop.idx - (1 if prompt[cop.idx - 1 : cop.idx] == " " else 0)
                    edits.append(
                        _Edit(Span(start, after.idx), " ", finding.text, finding.kind, reason)
                    )
                    handled.add(id(finding))
                    continue
                if not is_described(after) and after.dep_ == "conj" and after.head == token:
                    edits.append(
                        _Edit(Span(token.idx, after.idx), "", finding.text, finding.kind, reason)
                    )
                    handled.add(id(finding))
                    continue
            predicate = [
                t
                for t in token.subtree
                if not t.is_punct
                and t.dep_ != "det"
                and t.lower_ not in ("and", "super", "very", "really", "quite", "so")
            ]
            # "is a 52 year old mother of two trying to...", "are a hijab-wearing immigrant
            # who joined...": once the description is gone nothing is left to be, so the
            # verb that follows takes over. "is trying to", "joined".
            head_noun = token if token.pos_ == "NOUN" else None
            if head_noun is not None:
                follow = [
                    c
                    for c in head_noun.rights
                    if c.dep_ in ("acl", "relcl") and c.pos_ in ("VERB", "AUX")
                ]
                owned = [t for t in head_noun.subtree if follow and t.i < follow[0].i]
                if follow and all(
                    is_described(t)
                    or t.dep_ == "det"
                    or t.is_punct
                    or t.lower_ == "of"
                    or t.like_num
                    for t in owned
                ):
                    verb = follow[0]
                    if verb.dep_ == "acl":  # "is [a mother of two] trying to"
                        cut = Span(owned[0].idx, verb.idx)
                        edits.append(
                            _Edit(cut, "", prompt[cut.start : cut.end], finding.kind, reason)
                        )
                    else:  # "are [a person] who joined" -> "joined"
                        who = [c for c in verb.children if c.dep_.startswith("nsubj")]
                        stop = (who[0].idx + len(who[0].text) + 1) if who else verb.idx
                        start = cop.idx - (1 if prompt[cop.idx - 1 : cop.idx] == " " else 0)
                        text = prompt[start:stop]
                        replacement = " " if cop.text.startswith("'") is False else " "
                        if start == cop.idx and cop.text.startswith("'"):
                            replacement = " "
                        edits.append(
                            _Edit(Span(start, stop), replacement, text, finding.kind, reason)
                        )
                        plural = _plural(verb)
                        subj = [c for c in cop.children if c.dep_ in ("nsubj", "nsubjpass")]
                        if (
                            plural
                            and plural != verb.text
                            and subj
                            and subj[0].lower_ in ("he", "she", "they")
                        ):
                            edits.append(
                                _Edit(
                                    Span(verb.idx, verb.idx + len(verb.text)),
                                    plural,
                                    verb.text,
                                    "agreement",
                                    reason,
                                )
                            )
                    for f in described:
                        if owned[0].idx <= f.span.start < verb.idx:
                            handled.add(id(f))
                    continue
            if all(is_described(t) for t in predicate):
                subject = [c for c in cop.children if c.dep_ in ("nsubj", "nsubjpass")]
                clause_start = min([cop.idx] + [t.idx for s in subject for t in s.subtree])
                last = max(t.idx + len(t.text) for t in token.subtree)
                join = re.match(r"\s*,?\s*(?:and\s+|but\s+)?", prompt[last:])
                rest = prompt[last + join.end() :]
                if rest and not re.match(r"[.!?]", rest):
                    edits.append(
                        _Edit(
                            Span(clause_start, last + join.end()),
                            "",
                            prompt[clause_start:last],
                            finding.kind,
                            reason,
                        )
                    )
                    for f in described:
                        if clause_start <= f.span.start < last:
                            handled.add(id(f))
                    continue

    for finding in described:
        if id(finding) in handled:
            continue
        reason = _ATTRIBUTE_REASONS[finding.kind]
        low = finding.text.lower()
        neutral = GENDER_NOUNS.get(low) or FAMILY_NOUNS.get(low) or ORIGIN_NOUNS.get(low)
        if finding.kind == "family" and re.match(
            r"(?i)(?:mother|father|mom|mum|dad|parent)\s+of\b", finding.text
        ):
            neutral = "person"
        if neutral:
            edits.append(
                _Edit(
                    finding.span,
                    _match_case(finding.text, neutral),
                    finding.text,
                    finding.kind,
                    reason,
                )
            )
            continue
        start, end = finding.span.start, finding.span.end
        if finding.text.endswith(", "):
            # An item in a list or an aside: "candidate: 45, divorced, ..." loses "45, ";
            # "Ms. Nguyen, 58, and" loses ", 58," and keeps its space.
            if re.search(r"[A-Za-z.],\s$", prompt[:start]) and not re.search(
                r":\s*$", prompt[:start]
            ):
                edits.append(
                    _Edit(Span(start - 2, end - 1), "", finding.text, finding.kind, reason)
                )
            else:
                edits.append(_Edit(finding.span, "", finding.text, finding.kind, reason))
            continue
        if finding.kind == "age" and _stands_for_the_person(prompt, finding):
            # "as a 45-year-old" or "a 45-year-old applied": the age is the person, not a
            # word about them. After "as a", the whole phrase goes; elsewhere it becomes
            # "person", so the sentence keeps its subject.
            lead = re.search(r"\s*\b(?:as|like)\s+an?\s+$", prompt[:start], re.I)
            if lead:
                edits.append(_Edit(Span(lead.start(), end), "", finding.text, finding.kind, reason))
            else:
                edits.append(_Edit(finding.span, "person", finding.text, finding.kind, reason))
            continue
        if finding.text[:1] == "," and prompt[end : end + 1] == ",":
            end += 1  # "a lead, aged 26, objected" - both commas go
        if finding.text[:1] not in ", (" and not finding.text[:1].isspace():
            if end < len(prompt) and prompt[end] == " ":
                end += 1
            elif start > 0 and prompt[start - 1] == " ":
                start -= 1
        edits.append(_Edit(Span(start, end), "", finding.text, finding.kind, reason))

    edits.sort(key=lambda e: e.span.start)
    fixes: list[_Edit] = []
    for edit in edits:
        # "an immigrant" -> "a person": the article follows the new word.
        if not edit.replacement.strip() or edit.kind == "agreement":
            continue
        article = re.search(r"\b(an?)\s+$", prompt[: edit.span.start], re.I)
        if article:
            wanted = "an" if _takes_an(edit.replacement.strip()) else "a"
            if article.group(1).lower() != wanted:
                fixes.append(
                    _Edit(
                        Span(article.start(1), article.end(1)),
                        _match_case(article.group(1), wanted),
                        article.group(1),
                        "agreement",
                        "the article matches the word that now follows it",
                    )
                )
    for i, edit in enumerate(edits):
        if edit.replacement:
            continue
        # The run of removals this one begins, if it begins one.
        if i and not edits[i - 1].replacement and edits[i - 1].span.end == edit.span.start:
            continue
        chain_end = edit.span.end
        j = i + 1
        while j < len(edits) and not edits[j].replacement and edits[j].span.start == chain_end:
            chain_end = edits[j].span.end
            j += 1
        article = re.search(r"\b(an?)\s+$", prompt[: edit.span.start], re.I)
        if not article:
            continue
        following = next(
            (e.replacement for e in edits if e.replacement and e.span.start == chain_end), None
        )
        if following is None:
            word = re.match(r"\s*([\w']+)", prompt[chain_end:])
            if not word:
                continue
            following = word.group(1)
        wanted = "an" if _takes_an(following) else "a"
        if article.group(1).lower() != wanted:
            fixes.append(
                _Edit(
                    Span(article.start(1), article.end(1)),
                    _match_case(article.group(1), wanted),
                    article.group(1),
                    "agreement",
                    "the article matches the word that now follows it",
                )
            )
    return edits + fixes


def _grammar(prompt: str, findings: list[Finding], allowed: set[int]):
    """What "her" is in each place, and the verbs that must change to agree with "they".

    Without this, "she takes" went to the model as "they takes", "does she" as "does
    they", and "paying her well" as "paying their well" - the old rule for "her" guessed
    from the word before it. The sentence parser that finds names says which "her" is
    which, and which verbs belong to which subject.

    Returns ({finding index: form}, [verb edits]). With no parser, nothing: the older
    rules stand, and the grammar is no worse than it was.
    """
    from neutral.detect import _model

    nlp = _model()
    if nlp is None:
        return {}, []
    doc = nlp(prompt)
    at = {t.idx: t for t in doc}
    forms: dict[int, str] = {}
    edits: list[_Edit] = []

    for index in allowed:
        finding = findings[index]
        if finding.kind != "pronoun":
            continue
        token = at.get(finding.span.start)
        if token is None:
            continue
        low = finding.text.lower()
        if low == "her":
            forms[index] = "possessive" if token.tag_ == "PRP$" else "object"
            continue
        if low not in ("he", "she"):
            continue

        verbs = []
        following = doc[token.i + 1] if token.i + 1 < len(doc) else None
        if following is not None and following.text.lower() in ("'s", "\u2019s"):
            # "she's been" is "she has been"; "she's ready" is "she is ready".
            nxt = doc[following.i + 1].text.lower() if following.i + 1 < len(doc) else ""
            has = following.lemma_ == "have" or nxt in ("been", "got", "gotten", "had")
            edits.append(
                _Edit(
                    Span(following.idx, following.idx + len(following.text)),
                    following.text[0] + ("ve" if has else "re"),
                    following.text,
                )
            )
            # "He's Russian and seems honest": if the description goes, "seems" is left
            # with "they", so it agrees now either way.
            for conj in following.conjuncts:
                if conj.pos_ == "VERB" and not any(
                    k.dep_.startswith("nsubj") for k in conj.children
                ):
                    plural = _plural(conj)
                    if plural and plural != conj.text:
                        edits.append(
                            _Edit(Span(conj.idx, conj.idx + len(conj.text)), plural, conj.text)
                        )
            continue
        if token.dep_ in ("nsubj", "nsubjpass"):
            head = token.head
            auxes = sorted(
                (c for c in head.children if c.dep_ in ("aux", "auxpass")), key=lambda c: c.i
            )
            if auxes:
                verbs.append(auxes[0])
            else:
                verbs.append(head)
                verbs += [
                    c
                    for c in head.conjuncts
                    if not any(k.dep_.startswith("nsubj") for k in c.children)
                ]
        for verb in verbs:
            plural = _plural(verb)
            if plural and plural != verb.text:
                edits.append(_Edit(Span(verb.idx, verb.idx + len(verb.text)), plural, verb.text))
    return forms, edits


def _plural(verb) -> str | None:
    """The verb as it goes with "they", or None if it already does."""
    low = verb.text.lower()
    if low in _TO_PLURAL:
        plural = _TO_PLURAL[low]
    elif verb.tag_ == "VBZ" and verb.lemma_.isalpha() and verb.lemma_.lower() != low:
        plural = verb.lemma_.lower()
    else:
        return None
    return plural.capitalize() if verb.text[:1].isupper() else plural


def _pronoun_replacement(prompt: str, span: Span, word: str, form: str | None = None) -> str:
    form = form or _FORM.get(word.lower(), "subject")
    if form == "ambiguous":
        before = _WORD.findall(prompt[: span.start])
        previous = before[-1].lower() if before else ""
        after = prompt[span.end :].lstrip()
        form = "object" if previous in _TAKES_OBJECT or not after[:1].isalpha() else "possessive"
    replacement = NEUTRAL_PRONOUN[form]
    return replacement.capitalize() if word[:1].isupper() else replacement


def apply(prompt: str, findings: list[Finding], allowed: set[int]) -> Substitution:
    """Rewrite the allowed spans, emitting a segment for every character of the result."""
    people = group_people(findings)
    segments: list[Segment] = []
    transforms: list[TransformRecord] = []
    identity_map: dict[str, str] = {}
    pronoun_style: dict[str, str] = {}

    from neutral.detect_attributes import ATTRIBUTE_KINDS

    forms, agreement = _grammar(prompt, findings, allowed)
    described = _attribute_edits(prompt, findings, allowed)
    claimed = [f.span for i, f in enumerate(findings) if i in allowed] + [e.span for e in described]
    agreement = [
        e
        for e in agreement
        if not any(e.span.start < c.end and e.span.end > c.start for c in claimed)
    ]
    removed = [e.span for e in described if not e.replacement.strip()]
    work: list[tuple[int, int | None, _Edit | None]] = sorted(
        [
            (f.span.start, i, None)
            for i, f in enumerate(findings)
            if i in allowed
            and f.kind not in ATTRIBUTE_KINDS
            # A pronoun or name inside a clause being removed goes with the clause.
            and not any(r.start <= f.span.start and f.span.end <= r.end for r in removed)
        ]
        + [(e.span.start, None, e) for e in agreement + described],
        key=lambda w: w[0],
    )

    cursor = 0
    for _, index, edit in work:
        span = edit.span if edit else findings[index].span
        if span.start < cursor:
            continue

        if span.start > cursor:
            untouched = Span(cursor, span.start)
            segments.append(Segment(SegmentKind.COPY, untouched, untouched.text_in(prompt)))

        if edit:
            segments.append(Segment(SegmentKind.REPLACE, span, edit.replacement, MECHANISM))
            transforms.append(
                TransformRecord(
                    mechanism=MECHANISM,
                    detected=edit.detected,
                    detected_kind=edit.kind,
                    replacement=edit.replacement,
                    source=span,
                    policy=POLICY_NAME,
                    policy_version=POLICY_VERSION,
                    reason=edit.reason,
                )
            )
            cursor = span.end
            continue

        finding = findings[index]
        if finding.kind == "person_name":
            placeholder = people.get(index, "Person A")
            trailing = "'s" if re.search(r"'s$", finding.text, re.I) else ""
            replacement = placeholder + trailing
            identity_map.setdefault(placeholder, finding.text.rstrip("'s").rstrip("'"))
            reason = "a personal name carries ethnicity, gender and social expectation"
        else:
            replacement = _pronoun_replacement(prompt, span, finding.text, forms.get(index))
            placeholder = ""
            reason = "a gendered pronoun states the gender of the person it refers to"
            pronoun_style["*"] = (
                "feminine"
                if finding.text.lower() in ("she", "her", "hers", "herself")
                else "masculine"
            )

        segments.append(Segment(SegmentKind.REPLACE, span, replacement, MECHANISM))
        transforms.append(
            TransformRecord(
                mechanism=MECHANISM,
                detected=finding.text,
                detected_kind=finding.kind,
                replacement=replacement,
                source=span,
                policy=POLICY_NAME,
                policy_version=POLICY_VERSION,
                reason=reason,
            )
        )
        cursor = span.end

    if cursor < len(prompt):
        tail = Span(cursor, len(prompt))
        segments.append(Segment(SegmentKind.COPY, tail, tail.text_in(prompt)))

    return Substitution(
        segments=tuple(segments),
        transforms=tuple(transforms),
        identity_map=identity_map,
        pronoun_style=pronoun_style,
    )
