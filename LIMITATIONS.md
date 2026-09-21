# Limitations

Written as if a sceptical customer will read it, because one will.

This file is maintained alongside the results, not after them. A weakness recorded here
before the numbers arrive is a design note; one added afterwards looks like an excuse.

---

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
