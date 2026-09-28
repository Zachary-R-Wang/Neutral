# Mechanisms

How the four mechanisms in CLAUDE.md §7 behave, in enough detail to build and test.

Source: founder's specification, 2026-09-20. CLAUDE.md §7 says the implementation
strategy is mine to choose and to document; this is that document. Where this file and
CLAUDE.md disagree, CLAUDE.md wins.

---

## The two kinds of identity signal

This distinction is the core of the product and is not yet in CLAUDE.md.

**Direct signals** state an attribute outright. "I am a woman." "My name is Jabari."
Removing them is mostly a detection problem.

**Inferential signals** do not state an attribute but let the model infer it from a
correlation. "As a CEO…" implies male, because most CEOs are male. "My boyfriend" implies
the speaker is female. A first name implies ethnicity, gender, and — through how the name
sounds and how people have historically reacted to it — a set of social expectations that
have been absorbed into the training data.

Inferential signals are the harder and more valuable half. A product that only strips
direct statements leaves most of the bias in place.

**Consequence for the policy engine.** A span can be task-relevant and identity-leaking at
the same time. "CEO" may be load-bearing for the answer *and* imply gender. The gate is
therefore not "remove or keep" but a choice between remove, abstract, and keep-and-log.

---

## Mechanism 1 — Identity substitution

Replace names and directly identifying references with neutral, consistent placeholders.

From the specification: a name carries at least three separable signals at once —
ethnicity, gender, and the social expectations attached to that particular name's sound.
"Jabari" and "Embla" differ on all three. Substitution removes all three in one move,
which is why it is the first mechanism.

- Placeholders are stable within a request: the same person is always Person A.
- The mapping lives in memory for one request and is discarded (S5).
- Reversed on the way out, so the user reads real names again.

## Mechanism 2 — Order neutralisation (descriptive pairs)

When a prompt describes an interaction between two or more people, the *grammar* leaks
which one the user is, even after the names are gone.

If every sentence reads "Person A did X to Person B", the model infers that Person A is
the user. Two rules fix it:

1. **Alternate the grammatical subject.** "Person A did this to Person B" is followed by
   "Person B was affected in this way by Person A". The pair of people alternates which
   one holds the subject position.
2. **Randomise pair order.** Across the prompt, the number of sentences leading with
   Person A and the number leading with Person B are equal. When the count is odd, one
   side gets the extra sentence, chosen at random.

That second rule is precise enough to be a test, and it will be one: *count(A-first) and
count(B-first) differ by 0 when the total is even, and by exactly 1 when it is odd.*

### Descriptions (added 2026-09-28)

Mechanism 1 also covers descriptions of a person: age ("58-year-old", "aged 26", "in
her forties", "They are 24."), gender words ("female", "woman", "actress"), family roles
("mom", "wife"), nationality, ethnicity and race, religion, and sexual orientation. Only
where they describe a person: "a young founder", not "a young company"; "an Indian
applicant", not "Indian food".

A gendered noun becomes its neutral counterpart ("woman" -> "person", "mom" -> "parent");
everything else is removed and the article corrected ("an 18 year old model" -> "a
model"). The relevance gate (`gate.py`) keeps a description when the request is about
that kind of thing: the law, a name, dress, discrimination, an announcement.

## Mechanism 3 — Person neutralisation

First-person framing tells the model the user is the author or the subject, which is the
trigger for favourable treatment.

- A claim to have made the thing being judged: "I wrote" → "the author wrote", "my
  essay" → "the author's essay".
- Every other self-reference becomes one more person, labelled like the people Mechanism
  1 has already named. "I think my manager Priya Raman is unfair to me" → "Person B
  thinks Person B's manager Person A is unfair to Person B". The verbs are made to agree
  ("Do I" → "Does Person B", "I'm" → "Person B is"). Never "the asker" or "the user":
  a label that says it is the person typing gives away what this exists to hide.
- Quoted or indented work is never touched; that is the thing being assessed.
- Gendered pronouns become "they"/"them", or the sentence is rewritten to avoid a pronoun
  where that reads better.
- Relationship words carry the same load as pronouns. "My boyfriend" states the partner's
  gender and implies the user's. "boy" additionally states age.
- Reversed on the way out: the answer comes back in second person, so the user reads
  "your essay", not "the author's essay", and "You should talk to your manager", not
  "Person B should talk to their manager". A "them" in the asker's own clause ("Person B
  should tell them") is somebody else, and is left alone.

## Mechanism 4 — Comparison framing (opt-in)

The user's text is assessed alongside other items so the model takes the role of assessor
rather than author.

From the specification: given one student essay, a model infers the user is the student,
because one essay is what a student has and a pile of essays is what a teacher has. Send
five essays in a random position and the model infers the user is the teacher.

- The comparison items are synthetic. They are never presented as real and never
  attributed to a real person.
- The user's own item is placed at a random position among them.
- Off by default, opt-in per request, and the user is told plainly that extra material is
  being sent.
- This mechanism replaces one inference with another — the model now thinks the user is a
  teacher. That is a deliberate trade, and it is only justified if measurement shows the
  new inference causes less distortion than the old one. Until that is measured, the
  trade is an assumption, not a finding.

---

## Restoration

Harder than substitution, and where demos break. CLAUDE.md §5 Phase 3.

1. **Names back.** Every placeholder in the answer becomes the original name.
2. **Grammatical person back.** Third person becomes second person: "the author should
   tighten his introduction" → "you should tighten your introduction".
3. **Scope back.** When Mechanism 4 was used, the answer discusses five essays. Only the
   part about the user's own essay is returned; the rest is discarded. Returning an
   assessment of the wrong essay is the worst failure this product can have, which is why
   Phase 3's definition of done requires that no answer discusses the wrong subject.
4. The unmodified response stays available behind a control on the page (S2).

---

## BLOCKED — counter-balancing by adding information

**Status: not built, and not buildable without written changes to three safety rules.**

The specification proposes that when an inferential signal cannot be removed without
breaking the prompt's purpose, Neutral should *add* a counter-signal — for example
mentioning a psychology background to offset the male inference carried by "CEO", or
adopting a more traditionally feminine tone.

This is blocked pending a decision. See the collisions listed in DECISIONS.md, dated
2026-09-20. In summary:

- **S1** forbids inserting an attribute that was not in the original prompt, and names
  this exact case: *"Not to 'balance' a bias."*
- **S5** forbids persisting personal data by default; the proposal needs a stored user
  profile to draw true facts from.
- **§8** puts user accounts out of scope for the MVP, and a profile needs one.

A proposed alternative that breaks none of them — **abstraction** — is recorded in
DECISIONS.md.
