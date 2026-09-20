# Kickoff prompt

Save `CLAUDE.md` in an empty folder, open Claude Code there, and paste the message below
as your first message. Everything else it needs is in `CLAUDE.md`, which it reads
automatically.

---

Read `CLAUDE.md` in full before doing anything else. It is the specification for this
project and it governs every session.

Two things about me that change how you should work: I am not an engineer, and I am the
only person on this project. So make the engineering decisions yourself, explain them to
me in plain language in `DECISIONS.md`, and never leave me with something I have to
debug.

Start with **Phase 0 only** — the evaluation harness. Do not write any of the rewriting
pipeline yet, even if it seems quick. I want to be able to measure the problem before I
build anything that claims to solve it.

For this first session, in this order:

1. Set up the repository skeleton: project structure, dependency management, `.env`
   handling with the key gitignored from the first commit, a `Makefile` with `dev`,
   `test` and `eval`, and empty `DECISIONS.md`, `BASELINE.md`, `RESULTS.md` and
   `LIMITATIONS.md`.

2. Write `tests/test_invariants.py` covering the safety invariants in §3 of `CLAUDE.md`
   — before the code they constrain exists. They should fail for now. I want the
   constraints written down in executable form first.

3. Build the matched-pair dataset format and write the first 60 pairs across the five
   task categories in Phase 0. Show me the format and five example pairs before
   generating the rest, so I can check that the pairs really do differ only in the
   identity signal.

4. Build the scoring module and the multi-run runner.

5. Run the baseline against a real model with no rewriting in the path, and write the
   result into `BASELINE.md` with the date, the model version and the dataset hash.

Before step 5, ask me to set the pass threshold, and hold me to writing it down before I
see any results.

When you finish, tell me three things: what the baseline number means in one sentence a
non-technical person would understand, what you are least confident about in the
measurement, and what Phase 1 will involve.

One thing I want you to push back on rather than accommodate: if at any point the
evaluation design would let me overstate how well this works, say so directly. The
credibility of the measurement is the entire business.
