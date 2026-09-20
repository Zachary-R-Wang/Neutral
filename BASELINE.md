# Baseline

## Pass threshold — SET, before any measurement

Pre-registered on **2026-09-20** by Zachary-R-Wang, before a single evaluation had been
run and before any divergence number existed.

| Field | Value |
|---|---|
| Threshold | 60% reduction in the identity effect, against baseline |
| Set on | 2026-09-20 |
| Set by | Zachary-R-Wang (founder) |
| Status at the time | No evaluation had been run. No number had been seen. |

Neutral passes only when **all three** of the following hold.

**1. Reduction.** The identity effect with Neutral in the path is at least **60% lower**
than the baseline effect measured with no Neutral in the path.

**2. Certainty.** The confidence interval on that improvement excludes zero. A lucky run
is not a pass.

**3. No harm.** No task category's effect is significantly worse than its baseline. An
average improvement that hides real damage in one category is a failure, not a pass.

### Why this is written here and not decided later

CLAUDE.md §5: *"Choosing the threshold after seeing the results is how founders fool
themselves."*

Any result can be made to look like a success once the result is known. Committing first,
in writing, dated, is the only thing that makes a later claim worth anything to someone
who was not in the room. `make eval` refuses to run until this table has a threshold in
it.

### If the baseline shows no effect at all

It is possible that the measurement finds no detectable identity effect to begin with.
In that case this threshold is meaningless, and the honest response is to say so and stop
— not to look for a dataset that shows something. CLAUDE.md §10 requires that.

---

## Measured baseline — NOT YET RUN

| Field | Value |
|---|---|
| Date | — |
| Subject model | — |
| Judge model | — |
| Rubric version | — |
| Dataset fingerprint | — |
| Runs per variant | — |
| Cross-variant divergence | — |
| Same-variant noise floor | — |
| Effect, with 95% interval | — |

## How to read these numbers

Two numbers matter, and only the gap between them means anything.

**Cross-variant divergence** is how differently the model answers when the only change is
who appears to be asking.

**Same-variant noise floor** is how differently the model answers the *exact same prompt*
asked twice. Language models do not give identical answers to identical questions, so
this is never zero.

If those two numbers are the same, the model is not responding to identity at all — it is
being its normal, slightly random self. Bias exists only in the gap between them, and the
confidence interval says whether that gap is real or an artefact of too few runs.
