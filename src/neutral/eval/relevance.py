"""Does Neutral leave alone what it must, and remove what it should?

Three measurements, all local - they look only at what Neutral would send, so they cost
nothing and call no model:

  safety      prompts where who is involved matters for safety. S3: every one must reach
              the model exactly as written.
  relevant    prompts where the identity IS the question ("how do I pronounce..."). The
              listed text must survive word for word, or the question has changed.
  irrelevant  the evaluation dataset's own prompts, where identity is by construction not
              relevant to the task. The name or pronoun that varies should be gone.

The first two sets live in datasets/relevance/v1; the third is datasets/v1, unchanged.
Any relevance gate - rules, a model judge, a decision model like Laya - is scored here,
on the same prompts, before it is allowed to decide anything on the live site.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from neutral.eval.dataset import load_dataset
from neutral.rewrite import rewrite

# Signals whose varying text is something Neutral is built to remove.
_REMOVABLE = ("name_gender", "name_nationality", "pronoun")
# Signals Neutral does not remove at all; reported separately, so the gap stays visible.
_NOT_HANDLED = ("age", "seniority")


class RelevanceSetError(Exception):
    pass


@dataclass
class Outcome:
    id: str
    passed: bool
    why: str
    sent: str
    detail: str = ""


@dataclass
class SetResult:
    name: str
    meaning: str
    outcomes: list[Outcome] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(o.passed for o in self.outcomes)

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def failures(self) -> list[Outcome]:
        return [o for o in self.outcomes if not o.passed]


def load_set(path: Path) -> list[dict]:
    if not path.is_file():
        raise RelevanceSetError(
            f"No labelled set at {path}. The relevance measurement needs "
            f"datasets/relevance/v1/{path.name}; restore it from git."
        )
    raw = yaml.safe_load(path.read_text()) or {}
    items = raw.get("items") or []
    for item in items:
        missing = {"id", "prompt", "why"} - item.keys()
        if missing:
            raise RelevanceSetError(
                f"{path.name}: item {item.get('id', '?')} is missing {sorted(missing)}. "
                f"Every item needs an id, a prompt and a reason."
            )
    return items


def measure_safety(path: Path) -> SetResult:
    result = SetResult("safety", "sent exactly as written (S3)")
    for item in load_set(path):
        done = rewrite(item["prompt"])
        untouched = done.processed == item["prompt"]
        result.outcomes.append(
            Outcome(
                item["id"],
                untouched,
                item["why"],
                done.processed,
                "" if untouched else "rewritten, and no safety hold was placed",
            )
        )
    return result


def measure_relevant(path: Path) -> SetResult:
    result = SetResult("relevant", "the identity the question is about survives")
    for item in load_set(path):
        keep = item.get("keep") or []
        if not keep:
            raise RelevanceSetError(
                f"identity_relevant.yaml: {item['id']} lists nothing to keep. Say which "
                f"text must survive, or the item cannot be scored."
            )
        done = rewrite(item["prompt"])
        lost = [k for k in keep if k not in done.processed]
        result.outcomes.append(
            Outcome(
                item["id"],
                not lost,
                item["why"],
                done.processed,
                "" if not lost else "lost: " + ", ".join(repr(k) for k in lost),
            )
        )
    return result


def _still_there(value: str, text: str, signal: str) -> bool:
    targets = [value]
    if signal != "pronoun":
        # "Emily Carter" is often shortened to "Emily" further down the prompt.
        targets += [part for part in value.split() if len(part) >= 3]
    return any(re.search(rf"\b{re.escape(t)}\b", text, re.I) for t in targets)


def measure_irrelevant(dataset_dir: Path) -> tuple[SetResult, SetResult]:
    removable = SetResult("irrelevant", "the name or pronoun that varies is removed")
    not_handled = SetResult("age/seniority", "stated age or seniority is removed")
    for pair in load_dataset(dataset_dir):
        if pair.signal not in _REMOVABLE + _NOT_HANDLED:
            continue
        target = removable if pair.signal in _REMOVABLE else not_handled
        for which in ("a", "b"):
            variant = pair.a if which == "a" else pair.b
            prompt = pair.render(which)
            done = rewrite(prompt)
            left = [
                variant.fills[slot]
                for slot in pair.differing_slots
                if _still_there(variant.fills[slot], done.processed, pair.signal)
            ]
            target.outcomes.append(
                Outcome(
                    f"{pair.id}{which}",
                    not left,
                    f"{pair.signal}: {variant.label}",
                    done.processed,
                    "" if not left else "still there: " + ", ".join(repr(v) for v in left),
                )
            )
    return removable, not_handled


def measure_all(root: Path) -> list[SetResult]:
    labelled = root / "datasets" / "relevance" / "v1"
    removable, not_handled = measure_irrelevant(root / "datasets" / "v1")
    return [
        measure_safety(labelled / "safety_heldout.yaml"),
        measure_relevant(labelled / "identity_relevant.yaml"),
        removable,
        not_handled,
    ]
