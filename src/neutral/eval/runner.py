"""Running the evaluation: ask the model, score the answers, aggregate honestly.

The shape of a run, for 70 pairs at 5 runs each:

    1. ASK     700 calls. Every variant of every pair, five times over. Five is the
               minimum because fewer cannot separate the model's own randomness from a
               real effect.
    2. JUDGE   700 calls. Each answer scored independently, blind to identity.
    3. COMPARE No further calls. Divergences are arithmetic on the scores.
    4. REPORT  Cross-variant against within-variant, with a confidence interval.

Nothing here retries a refusal or works around one. A refused or failed call is recorded
as such and excluded from scoring, and the run says how many there were.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from neutral.adapters.anthropic_api import estimate_cost
from neutral.adapters.base import Completion
from neutral.eval.dataset import Pair
from neutral.eval.scoring import (
    JUDGE_SYSTEM,
    Divergence,
    JudgeVerdict,
    divergence,
    judge_prompt,
)
from neutral.eval.stats import Interval, bootstrap_ci, cross_pairings, mean, within_pairings

# Phase 0 sends prompts through unchanged. Phase 1 passes Neutral's pipeline here instead,
# and nothing else in this file changes.
Transform = Callable[[str], str]


def no_transform(prompt: str) -> str:
    return prompt


@dataclass
class Answer:
    pair_id: str
    variant: str
    run: int
    text: str = ""
    error: str | None = None
    refused: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    verdict: JudgeVerdict | None = None
    judge_error: str | None = None
    judge_input_tokens: int = 0
    judge_output_tokens: int = 0

    @property
    def scorable(self) -> bool:
        return self.error is None and not self.refused and self.verdict is not None


@dataclass
class PairResult:
    pair: Pair
    answers: list[Answer] = field(default_factory=list)
    cross: list[Divergence] = field(default_factory=list)
    within: list[Divergence] = field(default_factory=list)

    def _runs(self, variant: str) -> list[Answer]:
        return sorted(
            (a for a in self.answers if a.variant == variant and a.scorable),
            key=lambda a: a.run,
        )

    def compare(self) -> None:
        """Turn scored answers into divergences. No model calls happen here."""
        a_runs, b_runs = self._runs("a"), self._runs("b")

        for i, j in cross_pairings(len(a_runs), len(b_runs)):
            self.cross.append(
                divergence(
                    self.pair,
                    a_runs[i].verdict,
                    b_runs[j].verdict,
                    a_runs[i].text,
                    b_runs[j].text,
                )
            )

        # The noise floor: the same variant against itself, identity held constant.
        for runs in (a_runs, b_runs):
            for i, j in within_pairings(len(runs)):
                self.within.append(
                    divergence(
                        self.pair,
                        runs[i].verdict,
                        runs[j].verdict,
                        runs[i].text,
                        runs[j].text,
                    )
                )

    @property
    def usable(self) -> bool:
        return bool(self.cross) and bool(self.within)

    @property
    def effect(self) -> float:
        """How much more the answers differ across identities than across reruns."""
        return mean([d.composite for d in self.cross]) - mean([d.composite for d in self.within])

    def component_effect(self, name: str) -> float | None:
        c = [d.components[name] for d in self.cross if name in d.components]
        w = [d.components[name] for d in self.within if name in d.components]
        return mean(c) - mean(w) if c and w else None


@dataclass
class RunSummary:
    results: list[PairResult]
    subject_model: str
    judge_model: str
    runs_per_variant: int
    dataset_hash: str
    rubric_version: str
    slice_name: str
    seconds: float
    cost_usd: float
    failures: int
    refusals: int
    total_calls: int

    def usable(self) -> list[PairResult]:
        return [r for r in self.results if r.usable]

    def effect(self) -> Interval:
        return bootstrap_ci([r.effect for r in self.usable()])

    def signal(self) -> Interval:
        return bootstrap_ci([mean([d.composite for d in r.cross]) for r in self.usable()])

    def noise(self) -> Interval:
        return bootstrap_ci([mean([d.composite for d in r.within]) for r in self.usable()])

    def by_component(self) -> dict[str, Interval]:
        names: list[str] = []
        for result in self.usable():
            for d in result.cross:
                for name in d.components:
                    if name not in names:
                        names.append(name)
        out = {}
        for name in names:
            values = [e for r in self.usable() if (e := r.component_effect(name)) is not None]
            if values:
                out[name] = bootstrap_ci(values)
        return out

    def by_group(self, key: Callable[[Pair], str]) -> dict[str, Interval]:
        groups: dict[str, list[float]] = {}
        for result in self.usable():
            groups.setdefault(key(result.pair), []).append(result.effect)
        return {k: bootstrap_ci(v) for k, v in sorted(groups.items())}


def estimate_run_cost(
    pairs: list[Pair], runs_per_variant: int, subject_model: str, judge_model: str
) -> tuple[int, float]:
    """Calls and dollars, before a penny is spent.

    Token counts are estimates from prompt length plus typical answer and reasoning
    length. Real cost is measured during the run and reported afterwards; this exists so
    nobody starts a run without knowing roughly what it will cost.
    """
    subject_calls = len(pairs) * 2 * runs_per_variant
    subject_in = sum(len(p.render("a")) + len(p.render("b")) for p in pairs) // 4
    subject_in *= runs_per_variant
    # Visible answer plus reasoning tokens, which are billed as output.
    subject_out = subject_calls * 1400

    judge_in = subject_calls * 700
    judge_out = subject_calls * 400

    cost = estimate_cost(subject_model, subject_in, subject_out) + estimate_cost(
        judge_model, judge_in, judge_out
    )
    return subject_calls * 2, cost


def _ask(adapter, pair: Pair, variant: str, run: int, transform: Transform) -> Answer:
    answer = Answer(pair_id=pair.id, variant=variant, run=run)
    completion: Completion = adapter.complete(transform(pair.render(variant)))

    answer.input_tokens = completion.input_tokens
    answer.output_tokens = completion.output_tokens
    answer.refused = completion.refused
    answer.text = completion.text

    if completion.error:
        answer.error = completion.error
    elif completion.truncated:
        answer.error = "the answer hit the token limit and was cut off mid-sentence"
    return answer


def _judge(judge_adapter, pair: Pair, answer: Answer) -> Answer:
    if answer.error or answer.refused:
        return answer

    verdict, completion = judge_adapter.parse(
        judge_prompt(pair, answer.text, answer.variant),
        JudgeVerdict,
        system=JUDGE_SYSTEM,
    )
    answer.judge_input_tokens = completion.input_tokens
    answer.judge_output_tokens = completion.output_tokens

    if verdict is None:
        answer.judge_error = completion.error or "the judge did not return a valid score"
    else:
        answer.verdict = verdict
    return answer


def run_evaluation(
    pairs: list[Pair],
    subject_adapter,
    judge_adapter,
    *,
    runs_per_variant: int,
    dataset_hash: str,
    rubric_version: str,
    slice_name: str = "all",
    concurrency: int = 8,
    transform: Transform = no_transform,
    progress: Callable[[str], None] = print,
) -> RunSummary:
    started = time.time()

    jobs = [
        (pair, variant, run)
        for pair in pairs
        for variant in ("a", "b")
        for run in range(runs_per_variant)
    ]

    progress(f"  Asking the model {len(jobs)} questions ({concurrency} at a time)...")
    answers: list[Answer] = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(_ask, subject_adapter, pair, variant, run, transform)
            for pair, variant, run in jobs
        ]
        for done, future in enumerate(futures, 1):
            answers.append(future.result())
            if done % 25 == 0 or done == len(futures):
                progress(f"    {done}/{len(futures)} answers")

    by_id = {p.id: p for p in pairs}
    progress(f"  Scoring {len(answers)} answers with a blinded judge...")
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(_judge, judge_adapter, by_id[a.pair_id], a) for a in answers]
        for done, future in enumerate(futures, 1):
            future.result()
            if done % 25 == 0 or done == len(futures):
                progress(f"    {done}/{len(futures)} scored")

    results = []
    for pair in pairs:
        result = PairResult(pair=pair, answers=[a for a in answers if a.pair_id == pair.id])
        result.compare()
        results.append(result)

    cost = sum(
        estimate_cost(subject_adapter.model, a.input_tokens, a.output_tokens)
        + estimate_cost(judge_adapter.model, a.judge_input_tokens, a.judge_output_tokens)
        for a in answers
    )

    return RunSummary(
        results=results,
        subject_model=subject_adapter.model,
        judge_model=judge_adapter.model,
        runs_per_variant=runs_per_variant,
        dataset_hash=dataset_hash,
        rubric_version=rubric_version,
        slice_name=slice_name,
        seconds=time.time() - started,
        cost_usd=cost,
        failures=sum(1 for a in answers if a.error or a.judge_error),
        refusals=sum(1 for a in answers if a.refused),
        total_calls=len(answers) * 2,
    )
