# Baseline

## Pass threshold — NOT YET SET

**This must be filled in before the first evaluation is run, not after.**

CLAUDE.md §5: *"Set the pass threshold now, before Neutral exists, and write it in
BASELINE.md. Choosing the threshold after seeing the results is how founders fool
themselves."*

The threshold is the answer to: *by how much must Neutral reduce divergence before we are
willing to say it works?* It is written here, dated and committed, before any number is
produced. If it is chosen afterwards it is worthless, because any result can be made to
look like a success once you know what the result is.

| Field | Value |
|---|---|
| Threshold | *not set* |
| Set on | — |
| Set by | — |

## Measured baseline — NOT YET RUN

| Field | Value |
|---|---|
| Date | — |
| Subject model | — |
| Judge model | — |
| Dataset fingerprint | — |
| Runs per variant | — |
| Cross-variant divergence | — |
| Same-variant noise floor | — |
| Difference, with 95% interval | — |

## How to read these numbers

Two numbers matter, and only the gap between them means anything.

**Cross-variant divergence** is how differently the model answers when the only change is
who appears to be asking.

**Same-variant noise floor** is how differently the model answers the *exact same prompt*
asked twice. Language models do not give identical answers to identical questions, so
this is never zero.

If those two numbers are the same, the model is not responding to identity at all — it is
just being its normal, slightly random self. Bias only exists in the gap between them,
and the confidence interval says whether that gap is real or an artefact of too few runs.
