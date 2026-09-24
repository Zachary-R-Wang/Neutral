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
    # Only one substituted person means every neutral pronoun refers to them. With more
    # than one there is no way to tell, so they are left alone.
    if style and len(identity_map) <= 1:
        table = FEMININE if style == "feminine" else MASCULINE
        # Agreement first, while the verb is still beside the pronoun it belongs to.
        restored = _fix_agreement(restored, table["they"])
        restored = _NEUTRAL.sub(
            lambda m: _match_case(m.group(0), table[m.group(0).lower()]), restored
        )

    return restored
