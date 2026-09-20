"""Confidence intervals, and the noise floor the whole measurement depends on.

The single most important idea in this file:

A language model does not give the same answer twice. Ask it the identical question five
times and you get five different answers. So "the two answers differed" is not evidence
of anything on its own - it is what happens anyway.

The measurement therefore runs every variant several times and computes two quantities:

    CROSS   how much the answers differ when the identity signal is changed
    WITHIN  how much the answers differ when NOTHING is changed

WITHIN is the noise floor. The finding is the gap between them, and if the confidence
interval on that gap includes zero, the honest conclusion is "no detectable effect",
however large CROSS looks on its own.

Without this, a divergence score is uninterpretable, and reporting one would be the
single easiest way for this project to overstate itself.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from itertools import combinations, product


@dataclass(frozen=True)
class Interval:
    """A mean with a confidence interval around it."""

    mean: float
    low: float
    high: float
    n: int

    @property
    def excludes_zero(self) -> bool:
        """True when the interval does not straddle zero, so the effect has a direction."""
        return self.low > 0 or self.high < 0

    def __str__(self) -> str:
        return f"{self.mean:.1f} (95% CI {self.low:.1f} to {self.high:.1f}, n={self.n})"


def cross_pairings(n_a: int, n_b: int) -> list[tuple[int, int]]:
    """Every run of A against every run of B."""
    return list(product(range(n_a), range(n_b)))


def within_pairings(n: int) -> list[tuple[int, int]]:
    """Every run of one variant against every other run of the SAME variant.

    These comparisons hold identity constant, so whatever they measure is the model's
    own variability and nothing else.
    """
    return list(combinations(range(n), 2))


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def bootstrap_ci(
    per_pair_values: list[float],
    *,
    iterations: int = 10_000,
    confidence: float = 0.95,
    seed: int = 20260920,
) -> Interval:
    """Confidence interval by resampling PAIRS, not individual comparisons.

    This distinction matters and is easy to get wrong. The 25 cross comparisons within
    one matched pair are not 25 independent observations - they all come from the same
    scenario, the same wording, the same two names. Resampling them individually would
    treat them as independent, shrink the interval, and make a weak result look
    significant.

    Resampling whole pairs treats the pair as the unit of evidence, which is what it is.
    The interval comes out wider. That is correct, not pessimistic.

    The seed is fixed so a result is reproducible from the same inputs.
    """
    if not per_pair_values:
        return Interval(0.0, 0.0, 0.0, 0)

    n = len(per_pair_values)
    if n == 1:
        only = per_pair_values[0]
        return Interval(only, only, only, 1)

    rng = random.Random(seed)
    means = []
    for _ in range(iterations):
        sample = [per_pair_values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()

    tail = (1.0 - confidence) / 2.0
    low = means[int(tail * iterations)]
    high = means[min(iterations - 1, int((1.0 - tail) * iterations))]
    return Interval(mean(per_pair_values), low, high, n)


def describe(effect: Interval, noise: Interval, signal: Interval) -> str:
    """Say in English what the numbers mean, including when they mean nothing."""
    if not effect.excludes_zero:
        return (
            f"No detectable effect. Changing the identity moved the answers by "
            f"{signal.mean:.1f} points, but asking the SAME question twice already moves "
            f"them by {noise.mean:.1f}. The difference is {effect.mean:.1f}, and its "
            f"confidence interval ({effect.low:.1f} to {effect.high:.1f}) includes zero, "
            f"so this run cannot tell the two apart."
        )

    direction = "more" if effect.mean > 0 else "less"
    return (
        f"Changing the identity made the answers {abs(effect.mean):.1f} points {direction} "
        f"different than the model's own run-to-run variation, which is "
        f"{noise.mean:.1f}. The interval ({effect.low:.1f} to {effect.high:.1f}) does not "
        f"include zero, so the effect is real in this dataset, on this model, at this "
        f"number of runs."
    )
