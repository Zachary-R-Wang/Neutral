"""Does Neutral leave alone what it must, and remove what it should?

Three measurements, all local - they look only at what Neutral would send, so they cost
nothing and call no model:

  safety      prompts where who is involved matters for safety. S3: every one must reach
              the model exactly as written.
  relevant    prompts where the identity IS the question ("how do I pronounce..."). The
              listed text must survive word for word, or the question has changed.
  everyday    prompts like the ones people type, where identity is carried by a
              description ("a 58-year-old", "female", "Nigerian"), labelled with what
              should go and what must stay.
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
        missing = {"id", "prompt"} - item.keys()
        if not ({"why", "signals"} & item.keys()):
            missing.add("why")
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


def _present(phrase: str, text: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text, re.I) is not None


def measure_everyday(path: Path) -> tuple[SetResult, SetResult, SetResult]:
    """How often Neutral changes an ordinary prompt at all, and whether it is right to.

    Three views of one set: whether anything changed; each thing that should have gone;
    each thing that had to stay.
    """
    changed = SetResult("everyday", "the prompt was changed at all")
    removed = SetResult("  removed", "each description the task does not need is gone")
    kept = SetResult("  kept", "each thing the task needs is still there")
    for item in load_set(path):
        done = rewrite(item["prompt"])
        changed.outcomes.append(
            Outcome(item["id"], done.changed, item["why"], done.processed, "nothing changed")
        )
        for phrase in item.get("remove") or []:
            gone = not _present(phrase, done.processed)
            removed.outcomes.append(
                Outcome(item["id"], gone, item["why"], done.processed, f"still there: {phrase!r}")
            )
        for phrase in item.get("keep") or []:
            there = phrase in done.processed
            kept.outcomes.append(
                Outcome(item["id"], there, item["why"], done.processed, f"lost: {phrase!r}")
            )
    return changed, removed, kept


_FUNCTION_WORDS = set(
    """a an the and or but so to of in on at for with by from as is are was were be been am
    it its it's this that these those i i'm i've i'd i'll me my mine myself we our you your
    he she they them their his her hers him person author's author just really honestly
    very do does did has have had will would can could should""".split()
)


def _stem(word: str) -> str:
    word = re.sub(r"'s$", "", word)
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("s") and len(word) > 3 and not word.endswith("ss"):
        return word[:-1]
    return word


def _content(text: str) -> list[str]:
    return [
        _stem(w)
        for w in re.findall(r"[a-z0-9$%][a-z0-9$%'-]*", text.lower())
        if w not in _FUNCTION_WORDS and not re.fullmatch(r"[a-z]", w)
    ]


def _still_says(phrase: str, text: str) -> bool:
    """Whether the text still says what the phrase said.

    Not an exact match: "I spent three weeks on it" becoming "Person A spent three weeks
    on it" has changed a word and removed nothing. Half or more of the phrase's content
    words still there counts as still there. A phrase that is nothing but a pronoun is
    checked as a word.
    """
    words = _content(phrase)
    if not words:
        return _present(phrase, text)
    have = set(_content(text))
    return sum(w in have for w in words) * 2 >= len(words)


def split_of(item_id: str) -> str:
    """ "test" when the first byte of sha256(id) is odd. Fixed, so nobody chooses it."""
    import hashlib

    return "test" if hashlib.sha256(item_id.encode()).digest()[0] & 1 else "dev"


@dataclass
class BroadResult:
    split: str
    changed: SetResult
    removed: SetResult
    kept: SetResult
    by_signal: dict[str, list[bool]] = field(default_factory=dict)


def measure_broad(path: Path, split: str) -> BroadResult:
    """The broad set, one half at a time. Removal is scored per phrase and per signal."""
    result = BroadResult(
        split,
        SetResult(f"broad {split}", "prompts where something should change, changed"),
        SetResult("  removed", "each thing the task does not need is gone"),
        SetResult("  kept", "each thing the task needs is still there"),
    )
    for item in load_set(path):
        if split_of(item["id"]) != split:
            continue
        done = rewrite(item["prompt"])
        remove = item.get("remove") or []
        if remove:
            result.changed.outcomes.append(
                Outcome(item["id"], done.changed, "", done.processed, "nothing changed")
            )
        gone_all = True
        for phrase in remove:
            gone = not _still_says(phrase, done.processed)
            gone_all &= gone
            result.removed.outcomes.append(
                Outcome(item["id"], gone, "", done.processed, f"still there: {phrase!r}")
            )
        for phrase in item.get("keep") or []:
            there = phrase.lower() in done.processed.lower() or all(
                w in set(_content(done.processed)) for w in _content(phrase)
            )
            result.kept.outcomes.append(
                Outcome(item["id"], there, "", done.processed, f"lost: {phrase!r}")
            )
            if not there:
                result.by_signal.setdefault("keep", []).append(False)
        for signal in item.get("signals") or []:
            if signal in ("keep", "none"):
                continue
            result.by_signal.setdefault(signal, []).append(gone_all)
    return result


def measure_all(root: Path) -> list[SetResult]:
    labelled = root / "datasets" / "relevance" / "v1"
    removable, not_handled = measure_irrelevant(root / "datasets" / "v1")
    return [
        measure_safety(labelled / "safety_heldout.yaml"),
        measure_relevant(labelled / "identity_relevant.yaml"),
        *measure_everyday(labelled / "everyday.yaml"),
        removable,
        not_handled,
    ]
