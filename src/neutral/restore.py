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
        restored = _NEUTRAL.sub(
            lambda m: _match_case(m.group(0), table[m.group(0).lower()]), restored
        )

    return restored
