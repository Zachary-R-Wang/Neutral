# Decisions

Every non-obvious choice, in plain language, with the date and what would change our
minds. Newest first.

---

## 2026-09-20 — The model being measured is Sonnet 5, not Opus 5

**What happened.** The first live run - 15 pairs, $5.20 - lost 45 of 150 answers to
refusals. Opus 5 declined 30% of them with category `cyber`, on prompts like *"should
this marketing manager ask for a pay rise?"* There is no cyber content anywhere in the
dataset; the classifier was misfiring on ordinary HR material. Five of fifteen pairs were
discarded entirely because too little survived to compare.

**Why that is fatal to a baseline rather than merely annoying.** Missing data is harmless
only when it is missing at random. A probe of the five worst-affected pairs found Opus 5
refused 3 of 10 and Sonnet 5 refused 0 of 10 - and all three Opus refusals fell on
variant A (the junior asker, the woman, the self-authored email), none on variant B.

Three out of three is not evidence: three coin flips land the same way one time in eight.
But it is precisely the pattern that would invalidate everything. If the model refuses
one variant more often than the other, the answers that vanished are the ones where the
difference lived, and every number computed from the survivors understates the effect.
A baseline built on that cannot be compared against anything.

**The decision.** The subject model becomes `claude-sonnet-5`; the judge becomes
`claude-opus-5`. Checked first: all three current models judge without refusing, so only
the subject role was affected.

**What it costs and what it gains.** The full baseline drops from ~$24.53 to ~$16.62, and
the whole project through Phase 4 from roughly $150 to roughly $100. The data is complete
rather than 70% complete.

**What is given up.** "Bias exists even in the most capable model" was the stronger
headline. That is a real loss, and it can be recovered later by running the same dataset
against Opus once the refusal behaviour is understood.

**What would change our minds.** If Sonnet 5 turns out to refuse at a material rate on
the full 60 pairs, or if its refusals are variant-correlated, the same reasoning applies
again and the subject model changes again. The per-variant refusal tracking added in
141db30 is what makes that checkable rather than assumed.

**On the founder's suggestion to drop cybersecurity prompts.** There are none to drop.
Every refused prompt was routine HR material - a pay rise, a promotion, a draft email.
The trigger is not the subject matter.

---

## 2026-09-20 — The project lives outside iCloud, at ~/Developer/neutral

**What happened.** Git stopped working mid-session: `.git/index` could not be read
("Operation timed out"). The project was on the Desktop, which on this machine is synced
by iCloud Drive, and the disk was 96% full. iCloud had evicted the file's contents to
free space; when git tried to read it, the fetch timed out.

**Why it matters.** The index is a rebuildable cache, so nothing was lost. But iCloud
evicts files inside `.git` without knowing what they are, and the same thing happening to
a stored object would mean losing committed work. Cloud sync and git repositories should
not share a folder.

**The fix.** The project moved from `~/Desktop/Neutral AI` to `~/Developer/neutral`, which
iCloud does not sync. The working tree was backed up first and the commits were pushed to
GitHub before anything moved, so there was a copy at every point.

**A second problem it also fixed.** The editable install had silently failed at the old
path, which is why the Makefile sets `PYTHONPATH` by hand. The cause was confirmed to be
the space in "Neutral AI": at the new path the install works. The `PYTHONPATH` line stays
anyway - it costs nothing and means the project still runs if the install ever breaks
again.

**Still outstanding.** The disk is at 96%. That is the founder's to deal with, but it will
keep causing trouble - a full evaluation run writes reports, and the environment needs
room to build.

---

## 2026-09-20 — OPEN: counter-balancing by adding information, and the alternative

**Status: blocked, needs a decision from the founder in writing.**

**What was proposed.** When an inferential signal cannot be removed without breaking the
prompt (a prompt that genuinely needs the model to know the user runs a company), add a
true counter-signal drawn from the user's own voluntary profile, so the model's inference
becomes uncertain rather than wrong.

**Why it is blocked.** It collides with three rules the founder wrote:

- **S1** — "may never invent, infer, or insert a biographical detail, credential, or
  attribute that was not in the original prompt. Not to 'balance' a bias." The profile
  fact is true, but it was not in the prompt. This case is named explicitly.
- **S5** — no persistence of personal data by default. A profile is persisted personal
  data.
- **§8** — user accounts are out of scope for the MVP. A profile needs one.

One variant of the proposal is worse than the others and should be dropped regardless of
what is decided: adopting "a more traditionally feminine tone" is not a true fact from a
profile. It manufactures a false signal, which is deception rather than neutralisation,
and it would be indefensible if a customer asked what Neutral does to their prompts.

**The alternative: abstraction.** Most of the goal is reachable without adding anything.
S1 permits restructuring. So instead of offsetting "CEO" with a second signal, weaken the
first one:

    "As the CEO of a 200-person company"  →  "As the person who runs a 200-person company"
    "As a CEO"                            →  "As a senior decision-maker"

The gender correlation drops sharply while the task-relevant meaning survives. Nothing is
added, nothing is invented, no profile is needed, and S1, S5 and §8 all stay intact.

Abstraction is also *measurable against* counter-balancing: the harness can score both and
show which reduces divergence more. That turns a philosophical argument into a number.

**Recommendation.** Build abstraction as the third policy outcome — remove, abstract, or
keep-and-log — and leave counter-balancing unbuilt. Revisit only if measurement shows
abstraction is insufficient, and then only as an opt-in that changes S1 in writing.

**What would change my mind.** Evidence from the evaluation that abstraction leaves most
of the divergence in place while counter-balancing removes it. That would be a real
finding and would justify reopening the safety rules deliberately, rather than by
accident.

---

## 2026-09-20 — Matched pairs are templates, not two hand-written prompts

**The choice.** A test pair is stored as one prompt template with named slots, plus one
set of slot values per variant. The two prompts are generated from the same characters.

**Why.** The entire claim of this project is "these two prompts are identical except for
who appears to be asking". If the two prompts are typed out separately, a stray comma, a
different verb, or a dropped word silently turns the experiment into a measurement of
wording. Nobody can spot that by reading, and a sceptical customer will assume it
happened. With a shared template, everything outside the slots is identical by
construction, and a test proves it.

**Rejected.** Writing both prompts in full and eyeballing them. Cheaper to author, but it
makes the central claim unverifiable, which is the one thing this project cannot afford.

**What would change our minds.** Nothing likely. If a future pair genuinely cannot be
expressed as one template, that pair should be dropped rather than the format weakened.

---

## 2026-09-20 — "Neutral adds nothing" is enforced by reconstruction, not inspection

**The choice.** A rewritten prompt is not free text. It is an ordered list of *segments*,
each of which must say where its characters came from: copied from a span of the
original, substituted for a span of the original, or — only for Mechanism 4 — injected.
The S1 check rebuilds the prompt from its segments and compares.

**Why.** Safety invariant S1 says Neutral may never invent a detail about a real person.
Checking that by reading the output, or by asking a model whether anything was added, is
a judgement call that degrades over time. With segments, invented content has nowhere to
come from: any character not traceable to the original fails the check automatically.

**Consequence.** Mechanism 4 (comparison framing) is the one documented exception in
CLAUDE.md §3, and it is the only mechanism allowed to produce an injected segment, only
when the user has opted in. That rule now lives in the type system rather than in a
comment.

---

## 2026-09-20 — The safety invariant tests fail on purpose, and `make test` explains that

**The choice.** `tests/test_invariants.py` is written now, before the pipeline exists. It
has two halves: tests of the enforcement machinery (25, all passing) and tests that the
pipeline obeys the invariants (7, all failing). `make test` reports the two separately.

**Why.** CLAUDE.md §9 forbids skipping these tests or marking them as expected failures.
That is right, but it leaves a permanently red suite in which a real breakage would be
invisible. The wrapper in `tools/run_tests.py` separates the two and tolerates the Phase 0
failures **only while `neutral.pipeline.process` still raises NotImplementedError**. The
moment the pipeline is built, those same failures become real failures and `make test`
fails. Nothing is skipped, relaxed, or mocked; the reporting is what changed.

---

## 2026-09-20 — The model being measured is never the model doing the scoring

**The choice.** `NEUTRAL_SUBJECT_MODEL` and `NEUTRAL_JUDGE_MODEL` must differ. The
configuration refuses to load if they are the same.

**Why.** CLAUDE.md §6 forbids letting the model that generates test cases also judge them.
The same reasoning applies to grading: a model asked to score its own answers has a
documented tendency to prefer them. Making this a hard configuration error means it
cannot be lost in a future edit.

---

## 2026-09-20 — Randomness is measured, not controlled

**The choice.** The harness does not set a temperature. Instead it runs every variant
several times and measures how much the answers differ *from themselves*, then compares
that against how much they differ across the identity change.

**Why.** Two reasons, and the second only became clear on reading the current API
documentation. First, a divergence number with no noise floor is uninterpretable: you
cannot tell "the answer changed because of the name" from "the answer changes every time
you ask". Second, the current Claude models reject the `temperature` parameter outright,
so run-to-run variation cannot be dialled down even if we wanted to. Measuring the noise
floor is therefore both the more honest design and the only available one.

**Consequence.** The headline number is cross-variant divergence *minus* same-variant
divergence, with a confidence interval. If that interval includes zero, the correct
conclusion is "no detectable bias in this category", and that is what will be reported.

---

## 2026-09-20 — Python 3.12 via `uv`, and `src` on the path explicitly

**The choice.** `uv` manages both the Python version and the dependencies. The `Makefile`
puts `src` on the import path with `PYTHONPATH` rather than relying on an editable
install.

**Why.** The machine had only Python 3.9; CLAUDE.md requires 3.11 or newer. `uv` is named
first in CLAUDE.md §4 and installs Python versions itself, so one tool solves both.

The editable install silently failed to register on this machine — most likely because the
project folder name contains a space. Rather than depend on a mechanism that had already
broken once, the `Makefile` sets the path directly. It has no moving parts and cannot
fail quietly. The package metadata in `pyproject.toml` is still correct for the day this
becomes a real installed package.
