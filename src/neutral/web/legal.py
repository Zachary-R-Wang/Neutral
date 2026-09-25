"""Terms and privacy pages.

Written by an engineer, not a lawyer, and that limit is stated on the pages themselves.
They close the obvious gaps for something that is not yet public; they are not a
substitute for advice before anyone outside the project uses this.

The one that matters most is not the disclaimer - it is the disclosure that a prompt
leaves this machine and goes to a third-party model provider. Someone pasting a real
performance review about a real employee is sending that person's data to a company they
have not chosen and may not know about. Saying so plainly is the minimum.

Anything that must be filled in before publishing is wrapped in [[double brackets]] -
delimited rather than guessed at, so the highlighting cannot run past the end of the
placeholder and swallow the sentence around it.
"""

from __future__ import annotations

# Replace these before the site is reachable by anyone else. They are rendered in a way
# that is impossible to overlook, so the site cannot quietly go out with them in place.
#
# Neutral is operated by an individual rather than a company, so OPERATOR is a person's
# name. That is a fact about liability, not a formatting choice: there is no company
# between him and a claim, which is part of why the banner in section S6 says this is
# for evaluation and not for deciding anything about a real employee.
OPERATOR = "Zachary R. Wang"
CONTACT = "zachary.wang1@sisyphus.website"
JURISDICTION = "[[the country whose law governs this, e.g. England and Wales]]"

TERMS = f"""
## What this is

Neutral is an evaluation tool. It rewrites a prompt to remove signals about who is
asking, sends the rewritten prompt to a large language model of your choosing, and shows
you the answer with the names put back, alongside the answer exactly as the model wrote
it.

It is operated by {OPERATOR}.

## It is not for making decisions about people

**Do not use anything this produces as the basis of an employment decision** - hiring,
firing, promotion, pay, discipline, or any other decision affecting someone's job.

This is stated on every page for a reason. The tool is unproven: at the time of writing
no evaluation has established that it reduces bias, and there is published evidence in
the project's own repository that its effect may be small. Treating its output as a
fair assessment of a real person would be unsafe and, depending on where you are, may be
unlawful.

## It is not advice

Nothing here is legal, HR, employment, medical, or financial advice. Large language
models state incorrect things confidently. Check anything you intend to rely on.

## What you are responsible for

By using this you confirm that you have the right to put the text you enter into it, and
that you will not enter:

- personal data about anyone who has not agreed to it being processed this way
- special category data - health, race, religion, sexual orientation, trade union
  membership, biometric or genetic data
- anything confidential that you are not permitted to disclose to a third party
- credentials, payment details, or government identifiers

You are responsible for what you do with the output.

## No warranty

This is provided as is, with no warranty of any kind. It may be wrong, unavailable, or
may change without notice. To the fullest extent the law allows, {OPERATOR} accepts no
liability for any loss arising from its use.

The rewriting can fail in ways that are not obvious. It may remove something that
mattered, keep something that did not, or attribute part of an answer to the wrong
person. The unmodified answer is always shown alongside so you can check.

## Your prompts go to someone else

See the privacy page. This is the most important thing on either of them.

## Changes

These terms may change. Continuing to use the tool means accepting the current version.

## Governing law

{JURISDICTION}.

## Contact

{CONTACT}
"""

PRIVACY = f"""
## The short version

Your prompts are **sent to a third-party model provider**. Your account is stored here.
Your prompts and your API key are not.

## What leaves this machine

To answer you, Neutral sends your text to a large language model operated by another
company - whichever provider you connect. It is sent once.

Usually it is sent **rewritten**, with names replaced by placeholders, so the provider
does not receive the real ones. But your text is sent **exactly as you wrote it, names
and all**, in three cases:

- when the prompt touches something where who is involved matters for safety, which
  Neutral will not strip out
- when the rewriting cannot be shown to be faithful to what you wrote, and is abandoned
  rather than guessed at
- when there was nothing in it that needed changing

Neutral tells you which of these happened, underneath each answer. Assume anything you
paste may reach the provider. Once it does it is **handled under their terms and privacy
policy, not this one** - their retention, their location, their staff.

If you are pasting a real performance review about a real employee, that employee's
personal data is going to a company they have not chosen, and probably do not know about.
Consider whether you are permitted to do that before you paste it.

## What is kept here

**Your account is written to disk** and survives a restart. It is three things and
nothing else:

- the email address you signed up with
- a scrambled form of your password, which the password cannot be recovered from
- which model provider and model you last chose

Nothing else is kept. Specifically:

- **Your API key is never written down.** It is held in memory for your session only,
  and there is no place in the database that could hold one. It is gone when you sign
  out, and gone when the server restarts.
- **Prompts and answers** exist in memory for as long as your conversation is open, and
  are gone when the server restarts. They are not saved to any file or database.
- **The map between real names and placeholders** exists for the length of a single
  request and is discarded before the response is returned. It is never stored, not even
  in memory between messages.
- **One cookie**, holding a random identifier, so the page can find your session again.
  It contains nothing about you and is not used for tracking or analytics.

There is no analytics, no advertising, no third-party script other than a web font.

## Your rights

You can ask for your account record - the email address, the scrambled password and the
model preference described above - to be sent to you, corrected, or deleted. Email
{CONTACT} and it will be done.

There is currently no way to do that yourself from the site. That is a missing feature,
not a policy.

Beyond that record there is nothing to access or delete, because nothing else is kept.
Close the page and your conversation is gone.

This changes the moment audit retention is switched on, which it is not by default. If
that changes, this page changes with it.

## Contact

{CONTACT}
"""
