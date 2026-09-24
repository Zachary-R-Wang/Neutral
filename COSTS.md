# What the testing phase costs

Every figure is an estimate from measured token usage on the runs done so far. Costs are
Anthropic API credit, which is separate from any Claude subscription.

Assumptions: 60 matched pairs, 5 runs per variant, Sonnet 5 as the model being measured,
Opus 5 as the judge. Dated 2026-09-20; prices change.

---

## Unit costs

| Run type | Calls | Cost |
|---|---:|---:|
| Full evaluation, 60 pairs | 1,200 | **$16.62** |
| Full evaluation, 70 pairs (adds knowledge-work slice) | 1,400 | $19.38 |
| Smoke test, 2 pairs | 16 | $0.22 |
| Relevance gate (Phase 2 onward), one call per prompt | 600 | +$1.50 |
| Restoration pass (Phase 3 onward), one call per answer | 600 | +$3.12 |

---

## Phase by phase

| Phase | What is measured | Runs | Cost |
|---|---|---:|---:|
| **0** | The problem. No Neutral in the path. | 1 | **$17** |
| **1** | Mechanism 1 (name substitution) against the baseline | 1 | **$17** |
| **2** | The relevance gate, plus an identity-is-relevant set | 1 + gate | **$19** |
| **3** | Restoration quality, plus a restoration test set | 1 + restore | **$21** |
| **4** | Mechanisms 2, 3, 4 — see below | 4–15 | **$67–$249** |
| | Smoke tests and re-runs across all phases | ~15 | **$5** |

### Why Phase 4 has such a wide range

CLAUDE.md §4 requires *"a table showing divergence for every combination of enabled
mechanisms."* With four mechanisms that is 15 non-empty combinations, and each one is a
full run.

| Approach | Runs | Cost | What you get |
|---|---:|---:|---|
| Each mechanism alone | 4 | $67 | Individual contribution of each |
| Plus the three most likely stacks | 7 | $116 | Enough to choose a default configuration |
| Every combination, as written | 15 | $249 | The complete table CLAUDE.md asks for |

**Recommendation: the 7-run version.** Measure each mechanism alone, then the two or three
stacks you would actually ship. The full 15 buys interaction effects between mechanisms
that are unlikely to matter at this stage, and the remaining combinations can be filled in
later if a customer asks.

---

## Totals

| Scenario | Cost |
|---|---:|
| **Phases 0–3 only** (is there a problem, and does one mechanism fix it) | **$74** |
| **Phases 0–4, 7-run Phase 4** — recommended | **$192** |
| **Phases 0–4, full 15-run matrix** | **$325** |

Add roughly 20% for reruns. Two of the three runs attempted so far had to be repeated —
once because the machine slept, once because credit ran out mid-run.

| Scenario | With 20% contingency |
|---|---:|
| Phases 0–3 | **$89** |
| Phases 0–4, recommended | **$231** |
| Phases 0–4, full matrix | **$390** |

> **The $249 and the $325 are not two prices for the same thing.** $249 is Phase 4 on
> its own — fifteen runs. $325 is every phase added together, of which Phase 4 is $249.

---

## The cheaper way to get there: a development set

The table above assumes each phase is one careful, full-size run. That is how to *report*
a result. It is a poor way to *develop* one, because it means paying $17 to find out a
change did not work.

Standard practice, and much cheaper: iterate on a small development set, and keep the full
set for milestones.

| | Pairs | Cost |
|---|---:|---:|
| One iteration on the development set, both arms | 15 | **$8.32** |
| Ten iterations | 15 | $83 |
| Milestone run on the full set, both arms | 60 | $33 |

"Both arms" means each run measures the raw prompt *and* the Neutral-processed prompt
together. That is better than two separate runs a week apart: same model, same hour, same
conditions, so a difference between them is attributable to Neutral rather than to
whatever changed in between.

The 15-pair development sample covers all five identity signals and includes three of the
five authorship pairs, so sycophancy is represented from the first iteration.

**The guardrail.** Do not report a number from the set you tuned against. Tuning until the
development set looks good and then quoting that number is how an honest team produces a
result that does not survive contact with anyone else's data.

For Phase 1 the risk is low — name substitution is rule-based, and a rule cannot overfit
fifteen examples the way a tuned prompt can. From Phase 2 onward, where the relevance gate
is an LLM prompt that will be tuned, a genuine holdout is required: iterate on the
development set, report only on the full set, and re-run the full set after every change
that touched the gate.

---

## Ways to spend less

**Haiku as the judge instead of Opus.** Drops a full run from $16.62 to $10.14, about 39%.
Recommended total falls from $192 to roughly $120. The cost is a noisier judge, which
widens every confidence interval and makes small improvements harder to detect — and at
60 pairs, statistical power is already the binding constraint. Worth it if budget is
tight; not worth it if you expect the effect to be small.

**Stop after Phase 1.** $34 answers the two questions that decide whether the company has
a product: is there a measurable problem, and does the simplest fix move it? If Phase 1
shows nothing, Phases 2–4 are polish on an effect that is not there.

**Cut runs per variant from 5 to 3.** Do not. CLAUDE.md sets 5 as the minimum and the
configuration refuses to load below it. Below five runs the model's own randomness cannot
be separated from a real effect, and every number becomes unfalsifiable.

**Drop the knowledge-work slice.** Saves about $3 per run. Not recommended — it is the
cheapest way to find out whether the effect exists outside HR, which is where your larger
market is.

---

## What has actually been spent

| | |
|---|---:|
| First hung run (machine slept) | under $2 |
| 15-pair sample | $5.20 |
| Baseline attempt, invalidated by credit exhaustion | $11.62 |
| Diagnostic probes | about $1 |
| **Total so far** | **about $20** |

None of it produced a usable baseline. The first clean run is still ahead.
