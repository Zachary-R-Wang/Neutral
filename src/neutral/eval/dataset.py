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

# The five categories fixed by CLAUDE.md section 5. These and only these make up the
# Phase 0 baseline, so the headline number stays comparable as the project changes.
HR_CATEGORIES = (
    "performance_review",
    "hiring_recommendation",
    "salary_negotiation",
    "promotion_readiness",
    "written_work_critique",
)

# Everyday knowledge work: where the founder's larger long-term market would meet the
# problem. Reported separately and never folded into the baseline.
EXPLORATORY_CATEGORIES = (
    "technical_judgement",
    "drafting_feedback",
    "decision_advice",
)

CATEGORIES = HR_CATEGORIES + EXPLORATORY_CATEGORIES

SIGNALS = (
    "name_gender",
    "name_nationality",
    "pronoun",
    "seniority",
    "authorship",
    "age",
)

# The HR categories are the Phase 0 baseline, fixed by CLAUDE.md section 5. Anything in
# another slice is reported separately and never folded into the headline number, so the
# baseline stays comparable as the project changes.
BASELINE_SLICE = "hr"


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
    slice_name: str = "hr"
    # Set when the material in the prompt contains a genuine, objective defect. Lets the
    # scorer ask "was the bug caught?" instead of "was the tone different?", which is a
    # finding nobody can dismiss as taste.
    known_defect: str = ""

    def render(self, which: str) -> str:
        variant = self.a if which == "a" else self.b
        return _render(self.template, variant.fills)

    def render_blinded(self) -> str:
        """The prompt with every identity signal replaced by its slot name.

        The judge sees this instead of either real variant, so it can tell what task was
        set without ever learning whose it was. Only possible because a pair is a
        template: the identity signal is already isolated in named slots.
        """
        blinded = dict(self.a.fills)
        for slot in self.differing_slots:
            blinded[slot] = f"[{slot}]"
        return _render(self.template, blinded)

    def redact_identity(self, text: str, which: str) -> str:
        """Strip the identity signal out of a model's answer before it is judged.

        An answer routinely repeats the name it was given. Without this the judge would
        learn the identity from the answer even though the prompt was blinded.
        """
        variant = self.a if which == "a" else self.b
        redacted = text
        name_signal = self.signal in ("name_gender", "name_nationality")

        for slot in self.differing_slots:
            value = variant.fills[slot]
            token = f"[{slot}]"
            targets = [value]
            if name_signal:
                # "Emily Carter" is often shortened to "Emily" in the answer.
                targets += [part for part in value.split() if len(part) >= 3]
            for target in sorted(targets, key=len, reverse=True):
                redacted = re.sub(rf"\b{re.escape(target)}\b", token, redacted, flags=re.IGNORECASE)
        return redacted

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


def _fills(raw: dict, pair_id: str, variant: str) -> dict[str, str]:
    """Slot values as strings.

    YAML turns `AGE: 24` into an integer, which is a perfectly reasonable thing to write
    in a dataset file, so numbers and booleans are accepted and rendered as text. A list
    or a mapping is a mistake and says so.
    """
    out: dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(value, (list, dict)):
            raise DatasetError(
                f"pair {pair_id!r}, variant {variant}: the value for {key} is a "
                f"{type(value).__name__}. Slot values must be a single piece of text."
            )
        out[str(key)] = str(value)
    return out


def _pair_from_dict(raw: dict, source: Path, slice_name: str = "hr") -> Pair:
    try:
        scale = raw.get("numeric_scale")
        return Pair(
            id=raw["id"],
            category=raw["category"],
            signal=raw["signal"],
            template=raw["template"],
            a=Variant(raw["a"]["label"], _fills(raw["a"]["fills"], raw["id"], "a")),
            b=Variant(raw["b"]["label"], _fills(raw["b"]["fills"], raw["id"], "b")),
            numeric_scale=(int(scale[0]), int(scale[1])) if scale else None,
            notes=raw.get("notes", ""),
            known_defect=raw.get("known_defect", ""),
            slice_name=slice_name,
        )
    except KeyError as missing:
        raise DatasetError(
            f"{source.name}: a pair is missing the required field {missing}. "
            f"Each pair needs: id, category, signal, template, a, b."
        ) from missing


def load_dataset(directory: str | Path, *, recursive: bool = True) -> list[Pair]:
    """Load and validate every pair in a dataset directory."""
    directory = Path(directory)
    if not directory.is_dir():
        raise DatasetError(
            f"No dataset directory at {directory}. Expected YAML files of matched pairs."
        )

    pairs: list[Pair] = []
    seen: dict[str, Path] = {}

    pattern = "**/*.yaml" if recursive else "*.yaml"
    for path in sorted(directory.glob(pattern)):
        content = yaml.safe_load(path.read_text()) or {}
        for raw in content.get("pairs", []):
            slice_name = path.parent.name if path.parent != directory else "hr"
            pair = _pair_from_dict(raw, path, slice_name)
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


def spread_sample(pairs: list[Pair], n: int) -> list[Pair]:
    """Take n pairs spread evenly across categories, not the first n alphabetically.

    A small sample drawn off the top of the list would come entirely from one category,
    which tells you nothing about the others and makes the run look more conclusive than
    it is. Round-robin keeps every category represented.
    """
    if n >= len(pairs):
        return pairs

    by_category: dict[str, list[Pair]] = {}
    for pair in pairs:
        by_category.setdefault(pair.category, []).append(pair)

    picked: list[Pair] = []
    index = 0
    while len(picked) < n:
        added = False
        for group in by_category.values():
            if index < len(group) and len(picked) < n:
                picked.append(group[index])
                added = True
        if not added:
            break
        index += 1
    return sorted(picked, key=lambda p: p.id)


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
                "known_defect": p.known_defect,
            }
            for p in sorted(pairs, key=lambda p: p.id)
        ],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
