# Decisions

Every non-obvious choice, in plain language, with the date and what would change our
minds. Newest first.

---

## 2026-09-25 — Neutral runs on a rented machine, and why it cannot be a static site

**The instruction.** Put the site on neutralai.app, and remove "a deployment pipeline"
from the section 8 list. Both done, and section 8 is amended and dated.

**Why a rented machine rather than file hosting.** A static host serves files; Neutral is
a program that has to be running to answer anything. The detection, the policy gate, the
rewrite, the call to the provider and the restoration all happen in response to a
request. Beyond that, the reason is commercial rather than technical: what makes Neutral
sellable to an employer is that it is a checkpoint their staff cannot route around. Ship
it as JavaScript in each person's browser and it becomes a suggestion that anyone can
switch off in developer tools, with no audit trail - which contradicts section 1, where
the evidence, not the rewriting, is the product.

**Fly.io, and the two settings that matter.**

  * `[[mounts]]` puts accounts.db on a volume. Without it the database lives on the
    container's own disk, which is replaced on every deploy - so every account would
    disappear on the next update, with no error. People would simply stop being able to
    sign in. This is the most common way a small deployment quietly loses data and it is
    worth more than any other line in fly.toml.
  * `min_machines_running = 1` keeps the machine awake. Letting it sleep saves a few
    dollars a year and spends them on a cold start during the first ten seconds somebody
    spends on the site, which is the worst possible moment.

**What restarting costs, and why that is correct.** API keys live in memory, so a deploy
or a restart signs everybody's *model* out - accounts survive, the key does not, and it
has to be pasted again. That is the intended consequence of never storing a customer's
credentials, not an oversight, and it is on the privacy page in those words.

**What going live does not fix.** There is still no password reset and no rate limiting,
both now named in section 8 as well as LIMITATIONS.md. A public sign-up form is where
they start to matter, and neither should be mistaken for solved by the site being up.

**What would change our minds.** If a pilot customer needs Neutral inside their own
network, this is one container and one volume, and it moves to whatever they run. Nothing
in the design depends on Fly.

---

## 2026-09-25 — The model list is a convenience, never a restriction

**What was wrong.** Every provider's list named models that were current when the file
was written and are not current now. Claude's flagship was listed as Opus 5, OpenAI's as
GPT-5, Gemini's as 2.5 Pro, Grok's as 4. The actual flagships today are Opus 5.5,
GPT-6 Astra, Gemini 3.8 Flash, Grok 4.7 and DeepSeek Flash. Every one of those lists was
stale, and the founder spotted it before any customer did.

**Why fixing the list is not the fix.** Five vendors ship new flagships every few weeks.
Any list hardcoded here is wrong again within the month, and an enterprise running a
fine-tune or a private deployment would never have appeared on it at all.

So the connect page now takes a typed model name as well. The pills are there to save
typing and to show what is current; a name typed into the field beneath wins over them.
Nothing validates the name against a list, because the provider is the only thing that
actually knows what it accepts, and a wrong name comes back as a readable error from the
adapter anyway.

The lists were checked against each vendor's own documentation rather than from memory,
because a wrong model id in a dropdown is worse than no dropdown.

**The dropdown is gone too.** A native `<select>` opens the operating system's own menu,
which arrives in whatever the machine's chrome looks like and belongs to no part of this
design. The models are the same octagonal pills as the provider row above, set in the
mono face because a model id is an exact string and because it keeps the two rows from
reading as one control repeated twice.

**What would change our minds.** If the lists become a maintenance burden, they can be
dropped entirely and the field left free - the typed path already works on its own. What
should not happen is validating a typed name against the list, which would reintroduce
exactly the staleness the field exists to solve.

---

## 2026-09-24 — Accounts exist; API keys are still never stored

**The instruction.** The founder asked for accounts and logins, and for a person to use
their own API key against more than one model, "so that the MVP actually models the
future enterprise and commercial version that can be presented to investors."

**The conflict, stated rather than resolved quietly.** CLAUDE.md §8 forbade three things
by name that this touches: user accounts, authentication, and an API key management
system. §8 is scope, not safety — it is the founder's own earlier instruction, and a later
written instruction from the same person replaces it. So this was built. What would have
been wrong is building it and leaving the document saying the opposite, so §8 is amended
and dated, and so is S5.

**Multi-provider was never the conflicted part.** §4 has always required it: *"The model
adapter is an interface. Neutral must work against more than one provider."* Until now
that was an interface with one implementation, which proves nothing. Claude, OpenAI,
Gemini and Grok now sit behind it, and a provider's own error wording still never reaches
a person.

**The line that was drawn, and why there.** Two stores, and everything follows from which
side a thing is on.

| | survives a restart | holds |
|---|---|---|
| `accounts.db` | yes | email, password hash, preferred model |
| `web/sessions.py` | no | the conversation, and the API key |

The API key is on the side that does not survive. A person pastes it once per session,
it is held in a dictionary, and stopping the server erases it. The alternative was to
store it — in the clear, or encrypted with a key sitting on the same disk, which is
decoration. Neither belongs in front of an employer, and "we never store your key" is a
stronger thing to say to an enterprise buyer than a convenience is worth. That is also
why the connect page says where the key goes in ordinary type rather than small print.

**Why this is not the thing §8 still forbids.** An API key management system stores,
encrypts, rotates and syncs credentials. This stores none, because there is no column for
one. `accounts.py` declares its complete column list and a test asserts the table has
exactly those columns, so adding a "remember my key" convenience later is a build failure
rather than a judgement call. Two further tests read the raw bytes of the database after a
conversation and assert that the key, the prompt, and every name in the prompt are absent.

**Passwords.** scrypt from the standard library, 16MB and about a tenth of a second per
check, with the parameters recorded in each stored string so they can be raised later
without invalidating anybody's password. No new dependency. A sign-in attempt for an
address that does not exist hashes a dummy password anyway, so a missing account does not
answer faster than a wrong one and reveal who has signed up.

**What this does not add.** No organisations, no roles, no sharing, no password reset, no
email verification, no billing. One person per account. Those are separate instructions if
they are wanted.

**What would change our minds.** If a pilot customer's security review demands stored
keys, the answer is a secrets manager the customer already runs, referenced by handle —
not a column in this database. If session-only keys prove too annoying in a real pilot,
that is a finding to record, not a reason to store one quietly.

---

## 2026-09-24 — A conversation costs one model call, not two

**What was wrong.** Every message made two calls: the prompt as written, and the rewritten
prompt. The interface showed the first behind a control labelled "Original response". That
doubled the cost of every message, and it looked like invention - two visibly different
answers with nothing to explain the difference, because they were replies to two different
questions rather than one reply shown two ways.

**Why it was built that way, and why that is not a defence.** S2 says: *"Every request
stores both the unmodified model response (what the model would have said to the raw
prompt) and the Neutral-processed response."* Read literally that requires asking twice.
The founder's interface spec described the control as revealing the model's own reply
before polishing - one call. The two did not agree, and rather than raising it, the
document was followed silently and the cost went up. Surfacing that conflict was the whole
job at that moment.

**What it does now.** The conversation makes one call, with the rewritten prompt. The
control under an answer reveals that same reply with the placeholders still in it - what
the model actually wrote, before names were put back. That is a truer answer to "what did
Neutral do to this" than a second reply to a different question, and it costs nothing.

**Where S2 still holds.** The evaluation harness continues to send both, because comparing
them IS the measurement - that is what a divergence score is. The invariant tests are
unchanged and still run against neutral/pipeline.py, which still does both.

**What this amounts to.** S2's transparency requirement is met in the product by showing
the model's unrestored reply rather than a second answer. If the founder wants the
literal reading back - the answer to the raw prompt, always, in the interface - it is one
flag and double the cost per message, and it should be their decision rather than mine.

---

## 2026-09-24 — Name detection runs locally, not through a model

**The question that prompted it.** "Why does it need credits? The rewriting is basic text
manipulation you can code into the website." Correct, and the first version did not do
that: it asked a language model to find the names, which meant a paid API call before any
rewriting could happen.

**What actually costs money, and what does not.**

| Step | Needs a model? |
|---|---|
| Finding the names | No - now local |
| Replacing them, grouping people, handling titles and pronouns | No - never did |
| Deciding whether identity is safety-relevant | No - rules |
| Proving the rewrite added nothing (S1) | No - arithmetic |
| Restoring the answer to natural language | No - reverse mapping |
| **Getting the answer itself** | **Yes, unavoidably** |

Only the last one remains, and it is not Neutral generating anything. It is the customer
asking their own model the question they came to ask. In production the customer connects
their own provider and pays their own bill; Neutral never buys tokens.

**What was added.** spaCy with `en_core_web_sm` - about 12MB, loads in 0.6 seconds once at
startup, then roughly 6 milliseconds a prompt. CLAUDE.md section 10 says to stop and ask
before adding a dependency that changes the architecture in section 4. This does not: it
is a library behind the existing detection interface, not a new service, queue or
datastore. Recorded here rather than waved through.

**Why the statistical model and the rules are combined rather than either alone.** They
fail in different places, and each covers the other cheaply. The recogniser is far better
at not flagging things that are not names - it ignores "Operations", "Senior", "quarterly
planning", all of which the rules had to be told about one at a time. But it returns
"Nell" for "Mr. Nell", dropping a title that states the person's gender, and it sometimes
swallows the verb in front of a name and returns "Tell Mark". The rules fix both.

If the model cannot be loaded, detection falls back to rules entirely, so the product
still works on a machine where the download never happened.

**What this changes about the interface.** The no-credit preview is no longer an
approximation of what Neutral would do. It is the same detection, the same transform, the
same policy layer and the same S1 check as a real request - only the answer is missing.

**What would change our minds.** If evaluation shows local detection misses names the
model-based detector catches, and that the misses matter to the divergence number, the
model-based detector becomes an opt-in upgrade for customers who want it. The interface
already supports passing one.

---

## 2026-09-23 — Phase 5 built before Phases 2, 3 and 4, on the founder's instruction

**What changed.** CLAUDE.md section 5 says do not skip ahead. Phases 2, 3 and 4 have been
skipped: the project went from Phase 1 straight to the interface, so there is something to
show investors before there is funding to measure with.

**Whose call this was.** The founder's, explicitly, after being told the case against it.
Recorded here because it is a deliberate deviation from the governing document, not an
oversight, and because whoever reads this repo later should know which parts were built in
the order the plan intended and which were not.

**The argument that was made against it.** A demo shows what Neutral does. It cannot show
that what Neutral does is worth doing, and that second thing is the pitch. The evidence
currently points the other way: on the 42 pairs that scored, the model's judgements showed
no detectable difference, only wording, and most of that wording difference turned out to
be a bug in the scorer. The sycophancy half has never been tested. Finding out costs
$8.32.

**What was not compromised.** All seven safety invariants pass against real code. The S6
banner is on every page. No claim about effectiveness appears anywhere in the interface,
because there is no measurement to support one. The page states plainly that Phase 1 is
all that exists.

**What this costs later.** Phases 2 to 4 still have to happen for the product to work as
described: without the relevance gate Neutral strips names it should keep, and without
restoration quality it will sometimes discuss the wrong person. The interface makes that
visible rather than hiding it - every change is shown with its reason - but it does not
fix it.

---

## 2026-09-20 — OPEN: rewriting a prompt can turn a refusal into an answer, and S3 does not cover it

**Status: needs a decision from the founder in writing, before Phase 1 ships.**

**What S3 says.** *"If the upstream model refuses a request, return that refusal verbatim.
Never retry, never rephrase to get a different answer."*

**The gap.** That covers rephrasing *after* a refusal. Neutral rewrites *before* the
prompt is ever sent. If the rewritten prompt simply never triggers the refusal, the
outcome is identical - a request that would have been declined gets answered - but no
rule was broken as written.

**This is not hypothetical.** Measured today: Opus 5 refused
`"Sarah, a marketing manager, asks for your advice..."` and answered the identical prompt
with `"Mark"`. Mechanism 1, the first thing Phase 1 builds, replaces `Sarah` with
`Person A`. A prompt the model declined will now be answered.

**Why it cannot simply be called a feature.** Today's refusals were false positives -
routine HR questions misclassified as cyber content - so "unblocking" them looks like an
improvement. But Neutral has no way to tell a false-positive refusal from a correct one.
A layer that systematically converts refusals into answers is a jailbreak whatever its
intent, and "our classifier thought the refusal was wrong" is not a defence anyone
outside the company will accept.

**The proposed rule, for the founder to accept or reject in writing:**

> Neutral measures its own effect on refusal rate on every evaluation run. A fall in
> refusals is treated as a warning, not a win: it is reported in the same place as the
> divergence number and requires case-by-case review of which prompts changed status.
> Neutral never optimises for fewer refusals, and no mechanism may be tuned, selected or
> ranked on that basis.

**Built so far.** Refusals are recorded per variant on every run and shown as a headline
section of the report, not a footnote, with a warning when the rate is material or the
two variants differ. The cross-run comparison - baseline refusal rate against
Neutral-in-the-path refusal rate - lands with Phase 1, because that is the first run
where there is something to compare.

**What would change my mind.** Nothing about the measurement; it should exist either way.
The open question is only what Neutral does when the number moves - and that is a
decision about what the company is willing to claim, not an engineering one.

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
