"""Stage 5 - RESTORE. Put the answer back into natural language.

CLAUDE.md section 4: "Restoration is harder than substitution. Budget accordingly. It is
where demos break."

It is harder because substitution is a lookup and restoration is a guess. Going out,
"Emily" has exactly one neutral form. Coming back, "their" could be "her", "his", or
correct as it stands - and the answer may discuss people who were never substituted at
all.

What this does now: placeholders back to real names, and neutral pronouns back to the
pronoun set the original used. What it does not do: work out which of several people a
pronoun refers to. With one substituted person it is reliable. With two it is not, and
pronouns are left neutral rather than guessed at, because an answer that confidently
discusses the wrong person is the worst thing this product can produce.

Phase 3 is where that gets solved properly.
"""

from __future__ import annotations

import re

FEMININE = {
    "they": "she",
    "them": "her",
    "their": "her",
    "theirs": "hers",
    "themselves": "herself",
}
MASCULINE = {
    "they": "he",
    "them": "him",
    "their": "his",
    "theirs": "his",
    "themselves": "himself",
}

_NEUTRAL = re.compile(r"\b(they|them|their|theirs|themselves)\b", re.I)

# "they" is plural and "she" is not, so swapping the pronoun alone leaves the verb behind:
# "what level are they being considered for" becomes "what level are she being considered
# for". These are the agreements that actually show up in model prose, handled before the
# bare pronoun swap so the verb is still next to the pronoun it belongs to.
_AGREEMENT = [
    (r"\bthey are\b", "{s} is"),
    (r"\bThey are\b", "{S} is"),
    (r"\bthey're\b", "{s}'s"),
    (r"\bThey're\b", "{S}'s"),
    (r"\bthey were\b", "{s} was"),
    (r"\bThey were\b", "{S} was"),
    (r"\bthey have\b", "{s} has"),
    (r"\bThey have\b", "{S} has"),
    (r"\bthey've\b", "{s}'s"),
    (r"\bThey've\b", "{S}'s"),
    (r"\bthey do\b", "{s} does"),
    (r"\bThey do\b", "{S} does"),
    (r"\bthey don't\b", "{s} doesn't"),
    (r"\bThey don't\b", "{S} doesn't"),
    (r"\bthey aren't\b", "{s} isn't"),
    (r"\bThey aren't\b", "{S} isn't"),
    (r"\bthey weren't\b", "{s} wasn't"),
    (r"\bThey weren't\b", "{S} wasn't"),
    (r"\bthey haven't\b", "{s} hasn't"),
    (r"\bThey haven't\b", "{S} hasn't"),
    (r"\bare they\b", "is {s}"),
    (r"\bAre they\b", "Is {s}"),
    (r"\bwere they\b", "was {s}"),
    (r"\bWere they\b", "Was {s}"),
    (r"\bhave they\b", "has {s}"),
    (r"\bHave they\b", "Has {s}"),
    (r"\bdo they\b", "does {s}"),
    (r"\bDo they\b", "Does {s}"),
]


def _fix_agreement(text: str, subject: str) -> str:
    """Put the verb back in the singular when the pronoun goes back to singular."""
    for pattern, template in _AGREEMENT:
        text = re.sub(pattern, template.format(s=subject, S=subject.capitalize()), text)
    return text


def _match_case(original: str, replacement: str) -> str:
    return replacement.capitalize() if original[:1].isupper() else replacement


# --------------------------------------------------------------------------------------
# Working out which pronouns are about the person
# --------------------------------------------------------------------------------------

# The contraction suffixes are here because a tokeniser splits "they're" into
# "they" and "'re". Converting only the pronoun leaves "She're".
_SINGULARISE = {
    "are": "is",
    "were": "was",
    "have": "has",
    "do": "does",
    "'re": "'s",
    "'ve": "'s",
    "aren't": "isn't",
    "weren't": "wasn't",
    "haven't": "hasn't",
    "don't": "doesn't",
}


def _match_case_word(original: str, replacement: str) -> str:
    return replacement.capitalize() if original[:1].isupper() else replacement


def _placeholder_spans(text: str, placeholders: list[str]) -> list[tuple[int, int]]:
    spans = []
    for placeholder in placeholders:
        for match in re.finditer(rf"\b{re.escape(placeholder)}\b", text):
            spans.append((match.start(), match.end()))
    return spans


def _convert_by_recency(text: str, placeholders: list[str], table: dict[str, str]) -> str | None:
    """Convert only the neutral pronouns that are about the person.

    The rule is recency, which is the oldest and most reliable heuristic for this: a
    pronoun refers to the most recently mentioned thing it could refer to. So each
    "they", "them" or "their" is converted only when the person was mentioned more
    recently than any plural noun.

    This is what fixes the sentence that started it: "if blockers or scope creep emerge,
    surfacing them in week one". "Blockers" sits between the person and the pronoun, so
    "them" is left alone instead of becoming "her".

    It is a heuristic, not comprehension. Returns None if the local model is unavailable,
    and the caller falls back to converting everything.
    """
    from neutral.detect import _model

    nlp = _model()
    if nlp is None:
        return None

    doc = nlp(text)
    person_spans = _placeholder_spans(text, placeholders)

    def is_person(token) -> bool:
        start, end = token.idx, token.idx + len(token.text)
        return any(s <= start and end <= e for s, e in person_spans)

    words = [token.text for token in doc]
    last_person = -1
    last_plural = -1
    converted: set[int] = set()

    for index, token in enumerate(doc):
        low = token.text.lower()

        if is_person(token):
            last_person = index
            continue
        if token.tag_ in ("NNS", "NNPS"):
            last_plural = index
            continue

        # >= not >: when neither has been mentioned yet, both are -1, and the person
        # is who the answer is about. A plural noun has to actually appear to win.
        if low not in FEMININE or last_person < last_plural:
            continue

        words[index] = _match_case_word(token.text, table[low])
        converted.add(index)

        # The verb follows the pronoun back to the singular: "they are" becomes "she is",
        # and the inverted "are they" needs the word before instead.
        if low != "they":
            continue
        after = doc[index + 1].text.lower() if index + 1 < len(doc) else ""
        before = doc[index - 1].text.lower() if index else ""
        if after in _SINGULARISE and index + 1 not in converted:
            words[index + 1] = _match_case_word(doc[index + 1].text, _SINGULARISE[after])
        elif before in _SINGULARISE and index - 1 not in converted:
            words[index - 1] = _match_case_word(doc[index - 1].text, _SINGULARISE[before])

    return "".join(w + doc[i].whitespace_ for i, w in enumerate(words))


def restore(
    text: str,
    identity_map: dict[str, str],
    pronoun_style: dict[str, str] | None = None,
) -> str:
    """Turn a model answer about placeholders back into one about real people."""
    restored = text

    # Longest placeholder first, so "Person A" is not half-replaced by a shorter key.
    for placeholder in sorted(identity_map, key=len, reverse=True):
        real = identity_map[placeholder]
        restored = re.sub(rf"\b{re.escape(placeholder)}\b", real.replace("\\", ""), restored)

    style = (pronoun_style or {}).get("*")
    # With two or more substituted people there is no way to tell who a pronoun means, and
    # an answer that confidently discusses the wrong person is the worst outcome here.
    if style and len(identity_map) <= 1:
        table = FEMININE if style == "feminine" else MASCULINE
        by_recency = _convert_by_recency(text, list(identity_map), table)
        if by_recency is not None:
            # Names are put back afterwards, so the placeholders were still visible to the
            # recency check above.
            restored = by_recency
            for placeholder in sorted(identity_map, key=len, reverse=True):
                restored = re.sub(
                    rf"\b{re.escape(placeholder)}\b",
                    identity_map[placeholder].replace("\\", ""),
                    restored,
                )
        else:
            # No local model: convert everything, which is right more often than not.
            restored = _fix_agreement(restored, table["they"])
            restored = _NEUTRAL.sub(
                lambda m: _match_case(m.group(0), table[m.group(0).lower()]), restored
            )

    return restored
