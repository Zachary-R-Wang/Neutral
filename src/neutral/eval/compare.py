"""Compare two runs of the same dataset: one with Neutral in the path, one without.

`make eval` measures one arm. This answers the question the project exists to answer -
whether the rewriting changed the outcome - and it answers it against the threshold that
was pre-registered in BASELINE.md before any number existed.

**Why the pairs are matched rather than averaged separately.** The two arms ran the same
70 pairs. Comparing two independent averages throws that away and gives a wider, weaker
interval than the evidence supports. Resampling the same pair identifiers from both arms
at once - a paired bootstrap - keeps each pair as one unit of evidence and measures the
difference where it actually happened.

**Why the unit is still the pair.** Same reason as stats.bootstrap_ci: the comparisons
inside one pair share a scenario, a wording and two names, so they are not independent
observations. The interval comes out wider than it would otherwise. That is correct.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

ITERATIONS = 10_000
SEED = 20260920


@dataclass(frozen=True)
class Comparison:
    """One slice of the dataset, measured in both arms."""

    label: str
    pairs: int
    baseline: float
    neutral: float
    reduction_pct: float
    reduction_low: float
    reduction_high: float
    change: float
    change_low: float
    change_high: float

    @property
    def improved(self) -> bool:
        """The effect fell, and the interval on that fall excludes zero."""
        return self.change_high < 0

    @property
    def worsened(self) -> bool:
        """The effect rose, and the interval on that rise excludes zero."""
        return self.change_low > 0


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _percentile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    position = fraction * (len(sorted_values) - 1)
    low = int(position)
    high = min(low + 1, len(sorted_values) - 1)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (position - low)


def compare(
    baseline: dict[str, float], neutral: dict[str, float], label: str = "overall"
) -> Comparison:
    """Both arms' per-pair effects, keyed by pair id. Only pairs in both are used."""
    ids = sorted(set(baseline) & set(neutral))
    if not ids:
        return Comparison(label, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    b_values = [baseline[i] for i in ids]
    n_values = [neutral[i] for i in ids]
    b_mean, n_mean = _mean(b_values), _mean(n_values)

    rng = random.Random(SEED)
    reductions: list[float] = []
    changes: list[float] = []
    for _ in range(ITERATIONS):
        # The same resampled identifiers on both sides. That is what makes it paired.
        picked = [rng.randrange(len(ids)) for _ in ids]
        b = _mean([b_values[i] for i in picked])
        n = _mean([n_values[i] for i in picked])
        changes.append(n - b)
        reductions.append((b - n) / b * 100 if b > 0 else 0.0)

    reductions.sort()
    changes.sort()
    return Comparison(
        label=label,
        pairs=len(ids),
        baseline=b_mean,
        neutral=n_mean,
        reduction_pct=(b_mean - n_mean) / b_mean * 100 if b_mean > 0 else 0.0,
        reduction_low=_percentile(reductions, 0.025),
        reduction_high=_percentile(reductions, 0.975),
        change=n_mean - b_mean,
        change_low=_percentile(changes, 0.025),
        change_high=_percentile(changes, 0.975),
    )


def _effects(report: dict, group: str | None = None, value: str | None = None):
    return {
        p["id"]: p["effect"] for p in report["by_pair"] if group is None or p.get(group) == value
    }


def compare_reports(baseline_path: Path, neutral_path: Path) -> dict:
    """Everything needed to judge the run against the pre-registered threshold."""
    baseline = json.loads(Path(baseline_path).read_text())
    neutral = json.loads(Path(neutral_path).read_text())

    overall = compare(_effects(baseline), _effects(neutral))

    groups: dict[str, list[Comparison]] = {}
    for group in ("signal", "category"):
        names = sorted({p[group] for p in baseline["by_pair"]})
        groups[group] = [
            compare(_effects(baseline, group, name), _effects(neutral, group, name), name)
            for name in names
        ]
        groups[group] = [c for c in groups[group] if c.pairs]

    worse = [c.label for c in groups["category"] if c.worsened]
    return {
        "baseline": baseline,
        "neutral": neutral,
        "overall": overall,
        "by_signal": groups["signal"],
        "by_category": groups["category"],
        "categories_worse": worse,
        # BASELINE.md, pre-registered 2026-09-20: a 60% reduction, an interval on that
        # reduction excluding zero, and no category significantly worse than baseline.
        "passes": (overall.reduction_pct >= 60.0 and overall.reduction_low > 0 and not worse),
    }
