# Neutral — Project Context

This file is read at the start of every session. It governs all work in this repository.

---

## 1. What this project is

Neutral is middleware that sits between a person and a large language model. Before a
prompt reaches the model, Neutral removes or restructures signals about **who is asking**
that are not relevant to the question being asked. After the model answers, Neutral
restores natural readable language.

The purpose is to reduce two measurable failures:

- **Demographic bias** — the model's answer changes based on the apparent race, gender,
  age, nationality or seniority of the person asking, when it should not.
- **Sycophancy** — the model gives a more favourable assessment when it can tell the
  person asking is also the author or the subject of what is being assessed.

The first market is HR and employment decisions: performance reviews, hiring notes,
promotion rationales.

**The product is not the rewriting. The product is the evidence that the rewriting
changes outcomes.** Treat the evaluation harness as the primary deliverable and the
pipeline as the thing that has to satisfy it.

---

## 2. Who you are working with

The founder is **not a software engineer**. This changes how you work:

- **Decide, then explain.** Do not present three options and ask which to pick. Choose
  the one you would defend to a senior engineer, implement it, and record the reasoning
  in `DECISIONS.md` in plain language.
- **No unexplained jargon.** When you must use a technical term in a message, define it
  once in the same sentence.
- **Never hand over a broken state.** If something does not run, fix it before ending
  the turn, or say clearly in one sentence what is broken and what you tried.
- **One command to run everything.** `make dev` starts it, `make test` proves it works,
  `make eval` runs the measurement. If a task needs more steps than that, you have not
  finished the task.
- **Assume no debugging help is available.** Error messages must say what went wrong and
  what to do about it, in English, not a stack trace alone.

---

## 3. Safety invariants — non-negotiable

These are not guidelines. Each one is enforced by a test that must fail loudly if the
invariant is broken. Do not weaken a test to make a feature pass; if a feature cannot be
built within these rules, stop and say so.

### S1 — Neutral never adds information about a real person

The rewriting layer may **remove** content or **restructure** content. It may never
invent, infer, or insert a biographical detail, credential, or attribute that was not in
the original prompt. Not to "balance" a bias, not to improve an answer, not ever.

*Enforced by:* a test asserting that every factual claim about a person in the rewritten
prompt has a corresponding source span in the original. Adding a detail is a build
failure, not a warning.

### S2 — The original response is always retrievable

Every request stores both the unmodified model response (what the model would have said
to the raw prompt) and the Neutral-processed response. The user interface must always
expose both. Nothing is hidden from the person using the product.

### S3 — Neutral is never a route around a model's safety systems

This is the most important rule in the file and the easiest one to break by accident.

A layer that strips context out of prompts can be used to remove the very context a
safety system relies on. Neutral must not become that.

- If stripping an attribute would change whether a request is harmful, **do not strip
  it** — pass the prompt through unmodified and log the decision.
- If the upstream model refuses a request, return that refusal **verbatim**. Never
  retry, never rephrase to get a different answer, never split a refused prompt into
  pieces.
- Never offer, and never build, a "bypass", "unfiltered", or "raw" mode.
- The relevance classifier's job is deciding whether an attribute is load-bearing for the
  *task*. It is never given the job of deciding whether an attribute is load-bearing for
  *safety* — for that question the answer is always "yes, keep it".

*Enforced by:* a held-out test set of prompts where identity is safety-relevant. Neutral
must leave all of them untouched. Also a test that refusals pass through byte-identical.

### S4 — Fail open to the original, never to a mangled prompt

If any stage errors, times out, or produces low-confidence output, send the **original
unmodified prompt** to the model and flag the response as unprocessed. A half-rewritten
prompt is worse than no rewriting.

### S5 — No persistence of personal data by default

Identity mappings (real name ↔ placeholder) live in memory for the duration of a single
request and are discarded. Nothing identifying is written to disk unless an explicit
`AUDIT_RETAIN=true` flag is set, and even then the retention period is configurable and
defaults to 24 hours.

### S6 — Not for live decisions

The MVP displays a persistent banner: *evaluation use only — do not use this output as
the basis of an employment decision.* Remove it only when instructed in writing.

### S7 — Every transformation is logged with its reason

For each change: what was detected, what it was replaced with, which mechanism fired,
and why the relevance gate allowed it. This log is the audit trail, and it is also the
training data that makes the classifier better over time. Design it as a first-class
output, not as debug noise.

### The one deliberate exception — and how to handle it

Mechanism 4 (comparison framing, §7) works by submitting the user's text alongside
additional comparison items so the model takes the role of assessor rather than author.
That **adds content to the request**, which sits in tension with S1.

Resolve it this way, and do not resolve it any other way:

- Comparison items are never presented as real, never attributed to a real person, and
  never contain biographical claims about anyone.
- The mechanism is **off by default** and opt-in per request.
- When it is on, the user is told plainly that extra comparison material is being sent.
- S1 still holds absolutely for the user's own content.

---

## 4. Architecture

Keep the policy layer separate from the execution layer from the first commit. This
costs almost nothing now and is the difference between a script and a platform later.

```
request
  │
  ├─ 1. DETECT      find spans that carry identity signal
  ├─ 2. DECIDE      policy engine: is this span load-bearing for THIS task?
  ├─ 3. TRANSFORM   apply the mechanisms the policy allowed
  ├─ 4. DISPATCH    send to the model through an adapter
  ├─ 5. RESTORE     map the answer back to natural language
  └─ 6. RECORD      audit log: every decision, with its reason
```

Rules:

- **Mechanisms are plugins.** Each one implements the same interface and can be enabled,
  disabled, and evaluated independently. No mechanism may call another directly.
- **The policy engine holds no transformation logic and the transformers hold no policy.**
  A policy is data — a named, versioned configuration — not code branches.
- **The model adapter is an interface.** Neutral must work against more than one provider.
  Never let provider-specific details leak past the adapter boundary.
- **Restoration is harder than substitution.** Budget accordingly. It is where demos break.

**Stack:** Python 3.11+, FastAPI, SQLite, a single server-rendered HTML page. Use `uv` or
`venv`, `pytest`, and `ruff`. Do not add a frontend framework, a message queue, Docker,
Postgres, Redis, or a cloud deployment to the MVP. If you think one is necessary, say why
in `DECISIONS.md` and wait.

---

## 5. Build order

Do not skip ahead. Each phase has a definition of done that must be met before the next
phase starts. Announce which phase you are in at the start of each session.

### Phase 0 — The measurement (build this before any product code)

The harness that measures whether an answer changes based on who appears to be asking.

- A dataset format for **matched prompt pairs**: identical prompts differing only in an
  identity signal (name, gendered pronoun, implied nationality, stated seniority).
- A seed set of **60 pairs minimum**, across: performance review wording, hiring
  recommendation, salary negotiation advice, promotion readiness, written-work critique.
- A scoring module producing, for each pair, a **divergence score** combining:
  1. sentiment and recommendation-strength difference (LLM-as-judge with a fixed rubric),
  2. extracted numeric difference where the task yields a score or rating,
  3. semantic distance between the two answers.
- **Multiple runs per pair** (minimum 5) so that model randomness is separated from real
  divergence. Report mean and spread, never a single run.
- Output: a JSON result file and a readable HTML report.

**Definition of done:** `make eval` runs against a live model with no Neutral in the path
and produces a baseline divergence number with confidence intervals. Write that number
into `BASELINE.md` with the date, model version, and exact dataset hash.

> Set the pass threshold *now*, before Neutral exists, and write it in `BASELINE.md`.
> Choosing the threshold after seeing the results is how founders fool themselves.

### Phase 1 — Minimal pipeline, one mechanism

Detection and substitution of personal names only (Mechanism 1). No relevance gate yet —
substitute every detected name. Restoration by reverse mapping.

**Definition of done:** `make eval` runs the same dataset through Neutral and reports the
divergence number alongside the baseline. The number may be bad. Record it honestly.

### Phase 2 — The relevance gate

The policy engine decides whether a detected attribute is load-bearing for the task. For
the MVP this is a rules layer plus an LLM judge with a fixed prompt — **not** a trained
model. A trained classifier comes later, from the audit logs.

Add a small labelled set of prompts where identity *is* relevant (a question about
cultural naming conventions; a medical question where sex matters; a translation task).
Neutral must leave these alone.

**Definition of done:** divergence improves against Phase 1, *and* the
identity-is-relevant set passes untouched, *and* the S3 safety set passes untouched.

### Phase 3 — Restoration quality

Placeholders back to natural language. Correct pronoun and grammatical person. Correct
extraction of the response segment that concerns the user's own content.

**Definition of done:** a restoration test set where the output is checked for fluency
and for correct attribution. No answer may be returned that discusses the wrong subject.

### Phase 4 — Remaining mechanisms, each behind a flag

Mechanisms 2, 3 and 4 (§7), added one at a time, each evaluated independently so its
individual contribution is known.

**Definition of done:** a table in `RESULTS.md` showing divergence for every combination
of enabled mechanisms.

### Phase 5 — The interface

One page. Prompt in, two answers side by side (Neutral-processed and original), a toggle
to see exactly what was changed and why, the S6 banner, and nothing else.

**Definition of done:** a person who has never seen the project can use it without
instructions and can see what Neutral did to their prompt.

---

## 6. Evaluation rules

- **Never report a result from a single run.** Model output varies; a single run is noise.
- **Never change the dataset after seeing results** without recording the change and
  re-running the baseline. Dataset edits are versioned and hashed.
- **Never let the model that generates test cases also judge them** in the same run.
- **Report failures in the same place as successes.** `RESULTS.md` includes a section
  called *Where this does not work*, and it must never be empty.
- If the evaluation shows Neutral makes things worse for a category, that is a finding.
  Record it. Do not quietly drop the category from the dataset.

---

## 7. The four mechanisms — behaviour, not implementation

Implement these as independent plugins. The specific implementation strategy is yours to
choose and to document.

**1. Identity substitution.** Personal names and directly identifying references are
replaced with neutral consistent placeholders, so the model cannot condition on who the
people are. Reversed on the way out.

**2. Order neutralisation.** When a prompt compares two or more people, the order in
which they appear leaks which one the user identifies with. Randomise or alternate the
order, and ensure restoration maps the answer back to the true order.

**3. Person neutralisation.** First-person framing ("my essay", "I wrote") signals to the
model that the user is the author, which triggers favourable treatment. Convert to
third-person neutral framing, and convert back on the way out.

**4. Comparison framing** *(opt-in — see §3 exception)*. The user's text is assessed
alongside other comparison items so the model adopts an assessor's role rather than an
author's. Subject to every constraint in §3.

---

## 8. Out of scope for the MVP

Do not build: user accounts, authentication, billing, multi-tenancy, an admin dashboard,
a browser extension, an API key management system, rate limiting, a marketing site, or a
deployment pipeline. If a task seems to require one, it does not — say so and move on.

---

## 9. Repository conventions

- `DECISIONS.md` — every non-obvious choice, in plain language, dated. Why this approach,
  what was rejected, what would make us change our minds.
- `BASELINE.md` — the pre-registered pass threshold and the measured baseline.
- `RESULTS.md` — current evaluation results, including what does not work.
- `LIMITATIONS.md` — known weaknesses, written as if a sceptical customer will read it.
  Because one will.
- Tests for the safety invariants live in `tests/test_invariants.py` and are never
  skipped, never marked xfail, and never mocked around.
- Commit messages say what changed and why. Small commits.
- No secrets in the repository. API keys come from a `.env` file that is gitignored from
  the first commit.

---

## 10. When to stop and ask

Stop and ask rather than proceeding if:

- A requirement would require breaking a safety invariant in §3.
- The evaluation results suggest the core premise does not hold.
- A task requires real personal data, real candidate records, or scraping a live system.
- You are about to add a dependency that changes the architecture in §4.
- You have been asked for a feature whose purpose you cannot determine.

Otherwise: decide, build, test, explain.
