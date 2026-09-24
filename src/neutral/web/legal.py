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
OPERATOR = "[[your name, or your company's registered name]]"
CONTACT = "[[an email address people can actually reach you at]]"
JURISDICTION = "[[the country whose law governs this, e.g. England and Wales]]"

TERMS = f"""
## What this is

Neutral is an evaluation tool. It rewrites a prompt to remove signals about who is
asking, sends the rewritten prompt to a large language model of your choosing, and shows
you both the answer to your prompt and the answer to the rewritten one.

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

Your prompts are **sent to a third-party model provider**. Nothing is stored here.

## What leaves this machine

To answer you, Neutral sends your text to a large language model operated by another
company - whichever provider is configured. It is sent twice: once as you wrote it, and
once rewritten.

That means **any name, detail, or opinion about a real person in your prompt is
transmitted to that provider**, and is handled under their terms and privacy policy, not
this one. Their retention, their location, their staff.

If you are pasting a real performance review about a real employee, that employee's
personal data is going to a company they have not chosen, and probably do not know about.
Consider whether you are permitted to do that before you paste it.

## What is kept here

Nothing is written to disk. Specifically:

- **Prompts and answers** exist in memory for as long as your conversation is open, and
  are gone when the server restarts. They are not saved to any file or database.
- **The map between real names and placeholders** exists for the length of a single
  request and is discarded before the response is returned. It is never stored, not even
  in memory between messages.
- **No account, no login, no profile.** There is nothing to identify you by.
- **One cookie**, holding a random identifier, so the page can find your conversation
  again. It contains nothing about you and is not used for tracking or analytics.

There is no analytics, no advertising, no third-party script other than a web font.

## Your rights

Since nothing is stored, there is no record to access, correct, export, or delete. Close
the page and it is gone.

This changes the moment audit retention is switched on, which it is not by default. If
that changes, this page changes with it.

## Contact

{CONTACT}
"""
