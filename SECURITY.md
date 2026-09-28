# Security

Please do not report security problems in public issues.

Use the repository's **Security** tab and choose **Report a vulnerability**. That sends
a private report to the maintainers only.

Neutral handles other people's API keys and prompts about real people, so reports in
these areas are especially welcome:

- anything that writes a prompt, a name from a prompt, or an API key to disk, a log or
  the database (safety rule S5);
- a way to make the rewriting strip context from a request that should have been sent
  exactly as written for safety reasons (S3);
- a way to read another account's conversation or session;
- a way around the rate limits on sign-in, sign-up and password reset.

A report that includes the prompt or steps that reproduce it will be acted on fastest.
