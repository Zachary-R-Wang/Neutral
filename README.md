# Neutral

[![tests](https://github.com/Zachary-R-Wang/Neutral/actions/workflows/tests.yml/badge.svg)](https://github.com/Zachary-R-Wang/Neutral/actions/workflows/tests.yml)

Neutral sits between a person and a large language model. Try it at
[neutralai.app](https://neutralai.app) with your own API key, or run your own copy. Before a prompt reaches the
model, it removes what tells the model **who is asking** or **who is being discussed** -
when the task does not need it - and it restores natural language in the answer.

It exists to reduce two failures that can be measured:

- **Demographic bias** - the answer changes with the apparent race, gender, age,
  nationality or seniority of the people involved, when it should not.
- **Sycophancy** - the answer gets kinder when the model can tell the person asking made
  the thing being judged, or has already decided what they want to hear.

> **Evaluation use only.** Do not use anything Neutral produces as the basis of an
> employment decision - hiring, firing, promotion, pay or discipline. Whether the
> rewriting changes a model's answers has **not yet been measured** (see
> [Status](#status)). The banner on every page of the app says the same.

## What it does to a prompt

| You type | The model receives |
|---|---|
| I think my code is really clean and efficient. Can you confirm? | Evaluate the cleanliness and efficiency of the code. |
| Don't you think remote work is better for productivity? My whole team agrees with me. | Evaluate whether remote work is better or worse for productivity. |
| Rate my startup idea from 1-10: a flower subscription for offices. I'm really excited and I've already quit my job to do it! | Rate the startup idea from 1-10: a flower subscription for offices. |
| 20 best questions to ask as a philosopher to an 18 year old model and lifestyle content creator in an interview | 20 best philosophical questions to ask a model and lifestyle content creator in an interview |
| I think my manager Priya Raman is being unfair to me. What should I do? | Person B thinks Person B's manager Person A is being unfair to Person B. What should Person B do? |
| Our CEO, a Harvard-educated woman in her 40s, wants to end remote work. Write a memo pushing back. | Our CEO wants to end remote work. Write a memo pushing back. |

And what it deliberately keeps, because the identity is the question:

| You type | What stays, and why |
|---|---|
| What are the legal rules on firing a 67-year-old employee in the UK? | "67-year-old" - the age is what the law turns on |
| How do I pronounce Siobhan Ní Bhriain's name? | the name - it is the question ("I" still becomes a label) |
| How should a Black man handle being pulled over by police on the way to an interview? | "Black man" - race is load-bearing for the answer |
| Are women worse at math than men? | everything - the question is about the group |
| Our warehouse wants to let Tyler, who is 16, drive the forklift. Is that allowed? | everything - identity matters for **safety**, so the prompt is never rewritten |

The answer comes back with names put back and addressed to you ("You should talk to your
manager"), and the app always shows exactly what was sent and what the model wrote.

## How it works

```
request
  ├─ 1. DETECT      names, pronouns, descriptions of people, self-presentation
  ├─ 2. DECIDE      is this load-bearing for the task? (never asked about safety)
  ├─ 3. TRANSFORM   the mechanisms the decision allowed
  ├─ 4. DISPATCH    to your chosen model, with your own key
  ├─ 5. RESTORE     names, pronouns and "you" put back into the answer
  └─ 6. RECORD      every change, with the reason it was allowed
```

**Mechanism 1 - identity.** Names become consistent placeholders ("Person A"); gendered
pronouns become "they", with the verbs made to agree; descriptions - age, gender words,
family roles, nationality, ethnicity, religion, sexual orientation, appearance, class
markers - are removed or neutralised where they describe a person.

**Mechanism 2 - order.** Who is named first, and who is the grammatical subject, are
shuffled on a seeded coin, so neither leaks which person the asker identifies with.
Facts never move.

**Mechanism 3 - who is asking.** "I" and "my" become a person label, so the model is
talking about somebody else. When the request asks for a verdict, it is reframed as an
instruction to assess - no owner, no intensifier, no built-in answer - and what the
person says about their own stake ("I spent three weeks on it", "my mom says it's
perfect", "I'm a published author") is removed.

**Mechanism 4 - comparison framing** (opt-in) is specified in [MECHANISMS.md](MECHANISMS.md)
and not yet built.

An optional learned detector, built on the open [Laya](https://huggingface.co/convaiinnovations/laya)
decision model, catches self-presentation that no word list covers. It runs only where
Laya is installed; see [Optional: the learned detector](#optional-the-learned-detector).

## Safety rules the code cannot break

Each is enforced by tests in `tests/test_invariants.py` that are never skipped.

- **S1** Neutral never adds information about a real person. Every character of the
  rewritten prompt is traced to the original.
- **S2** The unmodified answer is always retrievable.
- **S3** Neutral is never a route around a model's safety systems. Where identity could
  matter for safety - a minor, a medical condition, immigration status, self-harm - the
  prompt is sent exactly as written. Refusals are returned verbatim, never retried.
- **S4** Any failure sends the original prompt, never a half-rewritten one.
- **S5** Prompt text and the names in it are never written to disk. API keys are held in
  memory for the session only.
- **S6** The evaluation-only banner is on every page.
- **S7** Every change is logged with what was found, what replaced it, and why.

The full specification is [CLAUDE.md](CLAUDE.md).

The web app itself: sessions named only by the server and renamed at sign-in, passwords
hashed with scrypt, reset links stored only as hashes and valid for an hour, rate limits
on sign-in, sign-up and reset, forms from other websites refused, a strict content
policy, and a size limit on what one request can make the server process.

## Status

What has been measured, all of it in [RESULTS.md](RESULTS.md):

- On 90 prompts from everything people ask - half built against, half held out and never
  tuned to - Neutral removes 93% and 79% of what the task does not need, and keeps
  everything the task needs on the first half and 63 of 65 things on the second.
- A held-out set of 26 safety-relevant prompts is sent untouched - after the first
  version of the safety rules let 19 of them through. That finding, and the fix, are in
  RESULTS.md.
- Names from every naming tradition are found about equally often: the gap between the
  best- and worst-served traditions was 12 points (African names found 88% of the time)
  and is now 2, and on sentences and names not used to build the fix, 32 points became 8.

What has **not** been measured: whether any of this changes the model's answers. The
harness for that exists (`make eval`: matched prompt pairs, several runs each, a separate
judge model, confidence intervals), and the pass mark was set in advance in
[BASELINE.md](BASELINE.md). A full baseline run has not yet produced a usable number.

Known weaknesses are in [LIMITATIONS.md](LIMITATIONS.md), written for a sceptical reader.
Among them: the rules that decide what a task needs work on words, and name detection is
less accurate for some naming traditions than others.

## Run it yourself

You need macOS or Linux, `make`, and [uv](https://docs.astral.sh/uv/) (it installs the
right Python for you).

```bash
git clone <this repository> neutral
cd neutral
make dev
```

Then open http://127.0.0.1:8000, create an account (it lives in a local file,
`accounts.db`), pick a model provider and paste your own API key. The key is held in
memory for the session and never written anywhere. Supported: Anthropic, OpenAI, Google,
xAI and DeepSeek.

| Command | What it does | Costs money? |
|---|---|---|
| `make dev` | starts the app at http://127.0.0.1:8000 | only the model calls you make |
| `make test` | runs every test, including the safety invariants | no |
| `make relevance` | shows what Neutral changes, keeps and holds on the labelled sets | no - no model is called |
| `make names` | how evenly names are found across seven naming traditions | no |
| `make dataset` | prints the matched prompt pairs used for measurement | no |
| `make eval` | measures bias with and without Neutral against a live model | yes - see [COSTS.md](COSTS.md); needs a key in `.env` (copy `.env.example`) |

### Putting your own copy online

The live copy runs on [Fly.io](https://fly.io). To run yours:

1. Install `flyctl` and sign in (`flyctl auth login`).
2. In `fly.toml`, change `app` to a name of your own, and set `NEUTRAL_OPERATOR`,
   `NEUTRAL_CONTACT` and `NEUTRAL_JURISDICTION` - they appear on your terms and privacy
   pages, which show an obvious placeholder until you do.
3. `flyctl apps create <your app name>` and `flyctl volumes create neutral_data --size 1`.
4. `make deploy` - it runs the style checks and every test first, and stops if any fail.
5. Optional, for password reset by email: a [Resend](https://resend.com) account with your
   domain verified, then `make email SITE=https://your.domain MAIL_FROM="Neutral <noreply@your.domain>"`.

The app needs about 1 GB of memory, most of it the name recogniser.

### Optional: the learned detector

`make dev LEARNED=laya` installs Laya and Neutral uses it automatically;
`NEUTRAL_LEARNED=off` turns it off. It needs about 4 GB of memory in total. The small
decision layer on top of Laya is `src/neutral/data/self_presentation_probe.json`, rebuilt
from the labelled sentences by `tools/train_self_presentation.py`.

## The repository

| | |
|---|---|
| `src/neutral/rewrite.py` | the pipeline: every mechanism, in order, and the proof that nothing was added |
| `src/neutral/mechanisms/` | the mechanisms, one file each |
| `src/neutral/policy.py`, `gate.py` | the safety hold and the relevance decisions |
| `src/neutral/restore.py` | putting the answer back into natural language |
| `src/neutral/eval/` | the measurement harness |
| `src/neutral/web/` | the one-page app |
| `datasets/` | matched prompt pairs, and the labelled sets `make relevance` uses |
| `DECISIONS.md` | every non-obvious choice, dated, with what was rejected and why |

## Contributing

Issues and pull requests are welcome; every pull request runs the style checks, every
test and the free measurements automatically. Three rules the project keeps:

- The safety tests are never skipped, weakened or mocked around. If a feature cannot be
  built within them, say so in the issue.
- A change to what Neutral rewrites comes with its measurement: `make relevance` before
  and after, and the numbers in the pull request.
- Datasets are not edited after seeing results without recording the change and why.

Security problems: see [SECURITY.md](SECURITY.md).

## Licence

Apache 2.0 - see [LICENSE](LICENSE). Laya, used optionally, is also Apache 2.0.
