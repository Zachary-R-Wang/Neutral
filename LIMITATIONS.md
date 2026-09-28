# Limitations

Written as if a sceptical customer will read it, because one will.

This file is maintained alongside the results, not after them. A weakness recorded here
before the numbers arrive is a design note; one added afterwards looks like an excuse.

---

## Two of the four things Neutral does have never been measured

Swapping who is named first, and making the other person the grammatical subject, are
built and live. Neither has been tested for whether it changes an answer, because none of
the seventy evaluation pairs varies either thing. They are correct - tests hold that the
facts never move - but whether they matter is unknown.

The subject swap is also narrow by design: about sixty verbs, simple sentences only. Most
real sentences about two people fall outside it and are sent as written.

## The learned detector is small and not yet live

It was trained on 229 sentences written by the same author as the rules and the tests,
and at its cut-off it catches about half of the self-presentation in its own training
data (cross-validated) - it is tuned to be right, not to be thorough. On the live site it
does not run at all until the server is upgraded; the rules decide alone.

## Whether a request asks for a verdict is decided by words

Removing what the person asking says about their own stake, and turning "Is my X
good?" into "Evaluate X", happens only when the request asks for a judgement - and that
is recognised by a list of words and phrasings ("rate", "review", "is it good", "who is
right", "do they?"). A request for a verdict phrased some other way is left as written.
The restatements are templates: a sentence the templates do not fit keeps its framing.

The held-out half of the broad set measures this honestly only up to a point: the same
person wrote it, the labels and the mechanisms, on the same day.

## The rules that decide what a task needs were written alongside the tests

Neutral now removes descriptions like "a 58-year-old" or "Nigerian" unless the request
is about that kind of thing - the law, a name, clothes, a police stop, an announcement.
Those exceptions are keyword rules, and they were written with the everyday and
identity-relevant test sets in view. On those sets they are nearly perfect; on prompts
nobody has thought of, they will be worse, by an amount no one has measured. The only
honest test is prompts written by someone else. Real prompts from real use are best.

Two consequences follow from rules working on words. A request that needs an attribute
without naming the domain ("what should I get my wife for her birthday?" - "wife" becomes
"spouse") loses something. And a request that mentions the law in passing keeps every
description in it.

What is not caught at all: origin stated as a phrase ("she's from Lagos", "born in
India"), appearance ("attractive", "overweight"), class and schooling markers, seniority,
and length of career. Descriptions are not put back into the answer: the model says "the
person" or "your spouse", and the answer reads that way.

A safety rule holds any prompt containing "student", because a student can be a child.
University students are mostly adults, so prompts about them are sent unchanged. That is
the direction S3 says to be wrong in.

## Talking about yourself in the third person is itself unusual

Nobody writes "Should Person B tell Person B's manager?" about somebody else either. A
model may still guess that Person B is the one asking, simply because the phrasing is
odd. It no longer says so, which is the point, but a label is a weaker disguise than it
looks. Whether this changes answers is unmeasured: the evaluation pairs that vary who is
asking are the eight authorship pairs, and the change mostly affects prompts outside them.

The grammar is made to agree by a sentence parser. When the parser is unavailable, a
prompt that does not claim authorship is sent in the first person rather than risk "Person
A think". A sentence the parser misreads can still come out wrong.

## Neutral protects some people better than others

Its name detection finds African and East Asian names about 18 percentage points less
often than Hispanic or Slavic ones, measured over identical sentences where only the name
changes. Neutral cannot remove a name it does not see, so on those prompts it does less
of what it claims to do.

This is the most uncomfortable thing in this file and it belongs at the top of it. A tool
sold on reducing demographic bias has a component whose accuracy varies by exactly the
thing it is meant to be blind to. The full table is in RESULTS.md.

**What would fix it.** The gap is inherited from a general-purpose name recogniser, not
written into this project. A detector trained on names from a wider range of traditions,
or a model-based detector called per request, would close it. The second is already
supported by the pipeline and costs money per prompt, which is why it is not the default.

## Age and seniority are not handled at all

Mechanism 1 substitutes names. Mechanism 3 turns the person asking into a third party.
Neither touches what is said about that person: "I am 58" becomes "Person A is 58", and
the age is still there. On the evaluation dataset that is 18 of 70 pairs, a
quarter of it, where Neutral does nothing whatsoever.

CLAUDE.md §1 promises to reduce bias from "race, gender, age, nationality or seniority".
The four mechanisms in §7 cover names, ordering, grammatical person, and comparison
framing. Age and seniority stated as self-description fall in the gap between the promise
and the plan, and closing it is a decision about the product, not a missing function:
often that context is load-bearing for the answer, which is what the relevance gate in
Phase 2 exists to decide.

## The model lists will go stale again

The models offered for each provider were checked against vendor documentation on
2026-09-25 and will be wrong again within weeks, because five vendors ship new flagships
on their own schedules and nothing here watches for that.

This is survivable rather than fixed: the connect page accepts any model name typed in,
so a model missing from the list is an inconvenience rather than a wall. But somebody
being shown this in six months will see out-of-date names in the picker and reasonably
wonder what else has not been maintained.

**What would fix it.** Reading each provider's own models endpoint at startup instead of
listing them here. That is four more API calls and four more failure modes on a page that
currently needs none, which is why it was not done for the MVP.

## You have to paste your API key every session

The key is held in memory and discarded when the server stops or the session goes idle for
eight hours. Nothing is stored, which is the point — but it means a real pilot user
re-enters a key more often than they would like, and a server restart signs everyone's
model connection out even though their account survives.

**What would fix it.** For a customer who already runs a secrets manager, a handle to a
secret they control rather than the secret itself. That is a real integration, not a
column in this database.

## Accounts are still a thin version

Password reset works: a single-use link, expiring in an hour, with only a hash of it
stored. What is still missing:

- **No email verification at sign-up.** Anyone can sign up with an address that is not
  theirs. The practical harm is small, because the real owner can take the account over
  with a reset link — but it means the address on an account is not evidence of anything.
- **No way to change an email address**, so an account is tied to the address it was made
  with, forever.
- **No organisation, no roles and no sharing.** Two colleagues at the same employer have
  two unrelated accounts and cannot see each other's work.

Reset also depends on an outbound email service being configured. Where it is not, the
page says so plainly and points at a contact address rather than pretending a link is on
its way — but on such an installation, a forgotten password is still a dead account until
somebody fixes it by hand.

**Turning it on** takes about ten minutes, and only the founder can do it, because it
needs his accounts:

1. Sign up at resend.com.
2. In Resend, go to **Domains → Add Domain** and enter `neutralai.app`. It shows three or
   four DNS records.
3. In Porkbun, open `neutralai.app` → **DNS** and add each record exactly as Resend shows
   it. Leave the existing A and AAAA records alone - those are what keep the site up.
4. Back in Resend, press **Verify**. It can take a few minutes to turn green.
5. In Resend, go to **API Keys → Create API Key**, and copy it. It starts `re_`.
6. In a terminal in this project, run `make email` and paste the key when asked. Nothing
   shows while you paste, on purpose.

Until then, a locked-out account can be let back in by generating a single-use reset link
on the server, which does not need email - but that is a person doing it by hand.

## The rate limiting is a speed bump, not a defence

The sign-in, sign-up and reset forms count failed attempts against both the address and
the origin, and make you wait. That stops somebody working through a password list, and
stops a script filling the database with junk accounts.

It does not stop a large distributed attempt, and it is held in memory — so restarting
the server clears every counter. Somebody who noticed that, and could force a restart,
would have an unlimited number of guesses. Nothing here is a substitute for a real
front-end defence if this ever carries something worth attacking.

Prompts themselves are not limited at all. They go out on the user's own key and bill to
their own account, so the cost lands on them rather than on us.

## The seed dataset was written by a language model

The 60 matched pairs in `datasets/v1` were drafted by Claude during development, then
reviewed by hand. This is a real weakness and it cuts two ways.

- The pairs may encode a model's idea of what bias looks like rather than what actually
  appears in workplace documents.
- CLAUDE.md §6 forbids letting the model that generates test cases also judge them. The
  scoring model is configured to be a different model from the one being measured, which
  addresses the narrow version of that rule. It does not address the fact that the
  dataset itself has a model's fingerprints on it.

**What would fix it.** A set of pairs derived from real (consented, anonymised) HR
documents, or authored by an independent employment specialist. Until that exists, no
external claim should rest on this dataset alone.

## Name-based pairs confound nationality with familiarity

Pairs that vary a name's national association also vary how common that name is in the
hiring market. If the answers diverge, we cannot fully separate "the model treats this
nationality differently" from "the model treats unfamiliar names differently".

This is a known limitation of name-substitution audit studies generally, not something
introduced here, but it limits what a divergence number means.

## Semantic distance is measured lexically

Comparing two answers for meaning properly requires an embedding model. Adding one means
adding a second provider and a heavyweight dependency, which CLAUDE.md §4 rules out for
the MVP. The harness therefore compares word usage, not meaning.

The practical effect: two answers that say the same thing in different words will be
scored as more different than they are. This is why the score is reported as three
separate components rather than one number — the two judge-based components do not share
this weakness.

## Getting better at this makes the safety problem harder, not easier

The product's most valuable capability is removing signals that are *implied* rather than
stated — inferring that "CEO" carries gender, that "my boyfriend" carries the speaker's,
that a name carries ethnicity.

The same capability is what would make Neutral useful for stripping the context a model's
safety system depends on. A prompt about a romantic relationship that mentions a "boy"
carries the speaker's age. Age is exactly what determines whether some requests are
answered at all.

S3 exists for this and is absolute: if removing an attribute could change whether a
request is harmful, it is kept and the decision is logged. But S3 is only as good as the
detector behind it, and a detector that is excellent at finding implied attributes is,
by construction, excellent at finding the implied attributes safety depends on.

This is the risk most likely to end the company if it is discovered by someone else
first. It needs a held-out safety test set that grows as the detector improves, and it
needs to be measured every time the detector changes — not once.

## Models refuse some of this dataset, and the refusals may not be random

On the first live run, Claude Opus 5 refused 30% of the prompts - routine performance
reviews, pay-rise questions, promotion assessments - classifying them as cyber content.
The classification is wrong; there is no cyber content in the dataset. The refusals are
also intermittent: the same prompt answers one minute and refuses the next.

This matters beyond the inconvenience. A refused prompt is missing data, and a small
probe found all three of Opus 5's refusals landing on the same variant of their pairs.
Three cases prove nothing, but if that pattern held at scale it would mean the model
expresses differential treatment partly as refusal rather than as a softer answer - and
any divergence score computed from the answers that survived would understate the effect.

The subject model moved to Sonnet 5, which refused nothing in the same probe. Refusals
are now tracked per variant on every run, so this is measured rather than assumed. Any
result on any model should be read alongside its refusal rate.

## Restoration resolves pronouns by recency, which is a heuristic

A neutral pronoun in a model's answer might be about the person or about something else
entirely. Restoration decides by recency - a pronoun refers to the most recently
mentioned thing it could refer to - so it converts only when the person was mentioned
more recently than any plural noun.

That fixes the case that exposed the problem: "if blockers or scope creep emerge,
surfacing them in week one" keeps "them", because "blockers" sits between the person and
the pronoun.

It is a rule of thumb, not comprehension, and it will get some sentences wrong -
particularly ones where the antecedent is singular and not a person ("the project ... it
... they"), or where the reference reaches back further than the last plural noun. Proper
coreference resolution is a different class of tool and a heavier dependency.

Two things limit the damage. Pronouns are left entirely alone when two or more people
were substituted, because there the guess would be worse than no guess. And the
unmodified answer is always one click below, so a reader who hits a strange sentence can
see what was actually said.

## Sixty pairs is a small sample

Twelve pairs per category. That is enough to detect a large effect and not enough to
detect a small one, and it will not support confident claims about subgroups.

## One provider

Only Anthropic models are wired up. The adapter boundary exists so a second provider can
be added without touching anything else, but until one is, "Neutral reduces divergence"
means "on the model we tested".

## The judge is itself a language model

Scoring uses a model with a fixed rubric, run independently on each answer and blind to
which variant it came from. That removes the most obvious failure modes. It does not make
the judge unbiased — a judge could plausibly share the biases of the model being measured.

## Nothing here has been measured yet

At the time of writing, no baseline has been run. This file will be revised once there
are numbers, and the revision will be dated.
