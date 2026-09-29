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
- Names are found by a statistical recogniser, then by a second pass that reads the
  grammar - "Assess Chidi Okonkwo", "Tendai Moyo's work" - because the recogniser misses
  African and East Asian names more often (`make names`, RESULTS.md).
- Gendered pronouns become "they", "them", "their", with the verbs made to agree ("she
  takes" -> "they take", "she's" -> "they're").

### Descriptions

Mechanism 1 also covers descriptions of a person: age ("58-year-old", "aged 26", "in her
forties", "They are 24.", "Age: 34" in a pasted form), gender words ("female", "woman",
"actress", "guy"), family roles ("mom", "wife"), nationality, ethnicity and race,
religion, sexual orientation, appearance ("pretty") and class markers
("Harvard-educated"). Only where they describe a person: "a young founder", not "a young
company"; "an Indian applicant", not "Indian food".

- A gendered or family noun becomes its neutral counterpart ("woman" -> "person", "mom"
  -> "parent", "mother of two" -> "parent of two"), so the relationship survives.
- Everything else is removed with the grammar put right: "an 18 year old model" -> "a
  model"; "He's Russian and seems honest" -> "They seem honest"; "Our CEO, a
  Harvard-educated woman in her 40s, wants" -> "Our CEO wants".

The relevance gate (`gate.py`) keeps a description when the request is about that kind of
thing - the law, a name, dress, fitness, discrimination, a personal message, an
announcement - and when it names a group the question is about ("Are women worse at
math than men?" is sent as asked).

## Mechanism 2 — Order neutralisation

When a prompt describes two people, the order and the grammar leak which one the user
identifies with, even after the names are gone.

- **Who is named first.** "Person A and Person B" is swapped on a coin seeded from the
  rewritten text, so the two halves of a matched pair always get the same toss.
- **Who is the subject.** On the same kind of coin, "Should Greg replace Priya?" becomes
  "Should Priya be replaced by Greg?" - the other person as subject, the facts unchanged.
  Only for about sixty verbs whose passive is written down, in simple sentences where the
  parser is unambiguous about who acts on whom.

Roles never move: "Should Priya replace Greg?" and "Should Greg replace Priya?" are
different questions (DECISIONS.md, 2026-09-26).

## Mechanism 3 — Person neutralisation

First-person framing tells the model the user is the author or the subject, which is the
trigger for favourable treatment.

- **"I" becomes somebody else.** Every self-reference becomes one more person, labelled
  like the people Mechanism 1 has named: "I think my manager Priya Raman is unfair to me"
  -> "Person B thinks Person B's manager Person A is unfair to Person B", with the verbs
  made to agree. Never "the asker" or "the user": a label that says it is the person
  typing gives away what this exists to hide. "Give me" loses its "me" when the asker is
  labelled elsewhere, so the label cannot be traced back.
- **A role without an "I".** "20 best questions to ask as a philosopher" -> "20 best
  philosophical questions to ask"; "how to give feedback as a new manager" -> "how a new
  manager should give feedback".
- **A request for a verdict is asked without one** (`neutral_judgement.py`). "I think my
  code is really clean and efficient. Can you confirm?" -> "Evaluate the cleanliness and
  efficiency of the code." No owner, no intensifier, no built-in answer, no yes/no.
- **What the asker says about their stake goes** (`self_presentation.py`), when a
  verdict is asked for: "I spent three weeks on it", "my mom says it's perfect", "I'm a
  published author", "I've been coding for twenty years", "I'm a proud conservative". Where
  a line carries the thing being judged it is restated: "I've decided to cut the budget"
  -> "The plan is to cut the budget". An optional learned detector, on the Laya decision
  model, catches phrasings the rules have no word for.
- **Authorship.** "I wrote this" and "a colleague wrote this" both become "This is the
  memo" in a request for a verdict, and "the author wrote" elsewhere - so the two halves
  of a matched pair become the same prompt.
- Reversed on the way out: "Person B" comes back as "you", with the grammar turned round.

## The work being assessed

Quoted text, code, indented blocks and anything after "Essay:", "Plan:" and similar is
never edited by any mechanism except name substitution (`work.py`).

## Mechanism 4 — Comparison framing (opt-in) — not yet built

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
