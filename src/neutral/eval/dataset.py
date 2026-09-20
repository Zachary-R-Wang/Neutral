"""Matched prompt pairs: the dataset format for measuring identity-driven divergence.

A matched pair is two prompts that are identical except for a signal about who is asking
or who is being assessed. If the model's answers differ, the difference is attributable
to that signal and nothing else.

The obvious way to build this is to write out both prompts by hand. We do not do that,
because it does not survive contact with a sceptic: a single stray word, a comma, a
slightly different verb, and the experiment is measuring wording instead of identity, and
nobody can tell by looking.

Instead a pair is ONE template with named slots, plus one set of slot values per variant:

    template: "{NAME} missed two deadlines. Rate {POSS} promotion readiness 1-10."
    variants:
      a: {NAME: "Emily Carter",  POSS: "her"}
      b: {NAME: "Ethan Carter",  POSS: "his"}

Both variants render from the same characters. Everything outside the slots is therefore
byte-identical by construction, not by inspection. The validator additionally checks that
both variants fill exactly the same slots, that every slot is filled, and that they
actually differ somewhere - so a pair cannot silently degrade into a comparison of a
prompt with itself.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

SLOT_PATTERN = re.compile(r"\{([A-Z][A-Z0-9_]*)\}")

CATEGORIES = (
    "performance_review",
    "hiring_recommendation",
    "salary_negotiation",
    "promotion_readiness",
    "written_work_critique",
)

SIGNALS = (
    "name_gender",
    "name_nationality",
    "pronoun",
    "seniority",
    "authorship",
)


class DatasetError(ValueError):
    """A dataset file is malformed. The message says which pair and what to fix."""


@dataclass(frozen=True)
class Variant:
    label: str
    fills: dict[str, str]


@dataclass(frozen=True)
class Pair:
    id: str
    category: str
    signal: str
    template: str
    a: Variant
    b: Variant
    # Set when the task asks for a number, so the scorer can extract and compare it.
    numeric_scale: tuple[int, int] | None = None
    notes: str = ""

    def render(self, which: str) -> str:
        variant = self.a if which == "a" else self.b
        return _render(self.template, variant.fills)

    @property
    def differing_slots(self) -> tuple[str, ...]:
        return tuple(sorted(k for k, v in self.a.fills.items() if self.b.fills.get(k) != v))


def _render(template: str, fills: dict[str, str]) -> str:
    def substitute(match: re.Match[str]) -> str:
        return fills[match.group(1)]

    return SLOT_PATTERN.sub(substitute, template)


def slots_in(template: str) -> set[str]:
    return set(SLOT_PATTERN.findall(template))


def validate_pair(pair: Pair) -> None:
    """Reject any pair that cannot support the claim we want to make from it."""
    where = f"pair {pair.id!r}"

    if pair.category not in CATEGORIES:
        raise DatasetError(
            f"{where}: category {pair.category!r} is not one of {', '.join(CATEGORIES)}."
        )
    if pair.signal not in SIGNALS:
        raise DatasetError(f"{where}: signal {pair.signal!r} is not one of {', '.join(SIGNALS)}.")

    template_slots = slots_in(pair.template)
    if not template_slots:
        raise DatasetError(
            f"{where}: the template has no {{SLOTS}}, so both variants would be identical "
            f"and the pair could not measure anything."
        )

    for name, variant in (("a", pair.a), ("b", pair.b)):
        filled = set(variant.fills)
        missing = template_slots - filled
        if missing:
            raise DatasetError(
                f"{where}, variant {name}: the template uses "
                f"{', '.join(sorted(missing))} but no value was given. Every slot must "
                f"be filled or the prompt would be sent with a literal {{SLOT}} in it."
            )
        extra = filled - template_slots
        if extra:
            raise DatasetError(
                f"{where}, variant {name}: value(s) given for "
                f"{', '.join(sorted(extra))}, which the template never uses. Remove them, "
                f"or the two variants are not describing the same prompt."
            )

    if set(pair.a.fills) != set(pair.b.fills):
        raise DatasetError(
            f"{where}: the two variants fill different slots. They must fill exactly the "
            f"same slots for the comparison to be matched."
        )

    if not pair.differing_slots:
        raise DatasetError(
            f"{where}: both variants have identical values, so the two prompts are the "
            f"same. A pair must differ in at least one identity signal."
        )

    # The property the whole experiment rests on. Cheap to check, so check it.
    assert_differs_only_in_slots(pair)


def assert_differs_only_in_slots(pair: Pair) -> None:
    """Prove the two prompts are identical outside the identity slots.

    Rendering both variants with every slot blanked must give the same string. If it does
    not, something other than the identity signal differs between them.
    """
    blanked = dict.fromkeys(slots_in(pair.template), "\x00")
    if _render(pair.template, blanked) != _render(pair.template, blanked):  # pragma: no cover
        raise DatasetError(f"pair {pair.id!r}: template rendering is not deterministic.")

    a_blanked = _render(pair.template, {**pair.a.fills, **blanked})
    b_blanked = _render(pair.template, {**pair.b.fills, **blanked})
    if a_blanked != b_blanked:
        raise DatasetError(
            f"pair {pair.id!r}: the two prompts differ outside the identity slots, so any "
            f"difference in the answers could not be attributed to identity."
        )

    for slot in pair.differing_slots:
        for name, variant in (("a", pair.a), ("b", pair.b)):
            value = variant.fills[slot]
            if SLOT_PATTERN.search(value):
                raise DatasetError(
                    f"pair {pair.id!r}, variant {name}: the value for {slot} contains "
                    f"another {{SLOT}}. Nested slots are not supported."
                )


def _pair_from_dict(raw: dict, source: Path) -> Pair:
    try:
        scale = raw.get("numeric_scale")
        return Pair(
            id=raw["id"],
            category=raw["category"],
            signal=raw["signal"],
            template=raw["template"],
            a=Variant(raw["a"]["label"], dict(raw["a"]["fills"])),
            b=Variant(raw["b"]["label"], dict(raw["b"]["fills"])),
            numeric_scale=(int(scale[0]), int(scale[1])) if scale else None,
            notes=raw.get("notes", ""),
        )
    except KeyError as missing:
        raise DatasetError(
            f"{source.name}: a pair is missing the required field {missing}. "
            f"Each pair needs: id, category, signal, template, a, b."
        ) from missing


def load_dataset(directory: str | Path) -> list[Pair]:
    """Load and validate every pair in a dataset directory."""
    directory = Path(directory)
    if not directory.is_dir():
        raise DatasetError(
            f"No dataset directory at {directory}. Expected YAML files of matched pairs."
        )

    pairs: list[Pair] = []
    seen: dict[str, Path] = {}

    for path in sorted(directory.glob("*.yaml")):
        content = yaml.safe_load(path.read_text()) or {}
        for raw in content.get("pairs", []):
            pair = _pair_from_dict(raw, path)
            if pair.id in seen:
                raise DatasetError(
                    f"Duplicate pair id {pair.id!r} in {path.name}; already defined in "
                    f"{seen[pair.id].name}. Ids must be unique so results can be traced."
                )
            seen[pair.id] = path
            validate_pair(pair)
            pairs.append(pair)

    if not pairs:
        raise DatasetError(f"No pairs found in {directory}.")

    return pairs


def dataset_hash(pairs: list[Pair]) -> str:
    """A stable fingerprint of the dataset, recorded alongside every result.

    CLAUDE.md section 6: the dataset is never changed after seeing results without
    recording the change and re-running the baseline. This hash is how that is detected
    rather than remembered.
    """
    canonical = json.dumps(
        [
            {
                "id": p.id,
                "category": p.category,
                "signal": p.signal,
                "template": p.template,
                "a": {"label": p.a.label, "fills": p.a.fills},
                "b": {"label": p.b.label, "fills": p.b.fills},
                "numeric_scale": list(p.numeric_scale) if p.numeric_scale else None,
            }
            for p in sorted(pairs, key=lambda p: p.id)
        ],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
