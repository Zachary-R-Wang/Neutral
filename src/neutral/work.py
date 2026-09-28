"""The work being assessed: the parts of a prompt no mechanism may edit.

A poem, an essay, a joke, a cover letter, a line of code - when someone asks for an
opinion of it, it is the thing being judged, and changing it changes the question.
Before 2026-09-28 only double-quoted text was protected, and the broad test set showed
what that cost: "for i in range(...)" became "for the author in range(...)", a quoted
joke had its pronouns changed, and two quoted scholarship essays were rewritten.

Names are the one exception, and it is Mechanism 1's call, not this module's: a name in
a cover letter tells the model who wrote it, and is put back in the answer anyway.
"""

from __future__ import annotations

import re

from neutral.core import Span

_DOUBLE = re.compile(r'"[^"]*"|“[^”]*”', re.S)
# A single-quoted passage: opens after a non-letter, closes before one, so that "it's"
# and "friends'" are never mistaken for quotation marks. Two words at least.
_SINGLE = re.compile(r"(?<![\w])['‘](?=\S)(.+?\s.+?)(?<=\S)['’](?![\w])", re.S)
_INDENTED = re.compile(r"(?:^[ \t]*(?:    |\t)\S[^\n]*\n?)+", re.M)
_FENCED = re.compile(r"```.*?```|`[^`\n]+`", re.S)
# Where code starts, it runs to the end of the prompt: code is pasted last.
_CODE_START = re.compile(
    r"(?:^|(?<=[.?!:]\s)|(?<=\n))"
    r"(?:def \w+\(|class \w+[:(]|for \w+ in |while .+:|import \w|from \w+ import |"
    r"function \w*\(|const \w+ =|let \w+ =|var \w+ =|#include|public |"
    r"SELECT |INSERT INTO |UPDATE \w+ SET |DELETE FROM |CREATE TABLE )",
    re.M,
)
# "Essay: ...", "Plan: ...": what follows the label, to the end of its paragraph.
_LABELLED = re.compile(
    r"\b(?:essay|excerpt|argument|plan|outline|story|poem|draft|text|code|query|message|"
    r"email|letter|sentence|paragraph|answer|response|abstract|bio|post|tweet|ad|listing|"
    r"chorus|lyrics?|joke|pitch|statement|proposal|thesis|summary|caption|slogan|headline|"
    r"projects?)\s*:[ \t]*(?=\S)",
    re.I,
)


def work_spans(prompt: str) -> list[Span]:
    """Every part of the prompt that is the work itself, sorted."""
    spans = [Span(m.start(), m.end()) for m in _DOUBLE.finditer(prompt)]
    spans += [Span(m.start(), m.end()) for m in _SINGLE.finditer(prompt)]
    spans += [Span(m.start(), m.end()) for m in _INDENTED.finditer(prompt)]
    spans += [Span(m.start(), m.end()) for m in _FENCED.finditer(prompt)]
    code = _CODE_START.search(prompt)
    if code:
        spans.append(Span(code.start(), len(prompt)))
    for m in _LABELLED.finditer(prompt):
        end = prompt.find("\n\n", m.end())
        spans.append(Span(m.end(), len(prompt) if end == -1 else end))
    return sorted(spans, key=lambda s: s.start)


def inside(position: int, spans: list[Span]) -> bool:
    return any(s.start <= position < s.end for s in spans)
