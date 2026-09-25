# How Neutral is built for a server. Not used for local development - `make dev` runs it
# straight from the source and never touches this file.
#
# The layer order matters more than it looks. Dependencies are installed before the
# source is copied, so editing a Python file does not re-download the 15MB language
# model that name detection needs. Getting this backwards turns a ten-second deploy into
# a two-minute one.

FROM python:3.12-slim AS build

# The same uv the project uses locally, so the server installs from the same lockfile
# and cannot quietly end up on different versions than the tests ran against.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first. README.md is here because pyproject.toml names it, and the build
# fails without it in a way that does not mention README.md.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --- the image that actually runs -----------------------------------------------------
FROM python:3.12-slim

# Not root. If something goes wrong in a web process, it should go wrong with as little
# authority as possible.
RUN useradd --create-home --uid 1000 neutral

WORKDIR /app
COPY --from=build --chown=neutral:neutral /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Marks the session cookie "secure", so it is never sent over plain HTTP.
    NEUTRAL_PUBLIC=true \
    # On the mounted volume, so accounts survive a deploy. Anywhere else and every
    # account silently disappears the next time this is updated.
    NEUTRAL_ACCOUNTS_DB=/data/accounts.db

USER neutral
EXPOSE 8080

# --forwarded-allow-ips lets uvicorn trust the proxy in front of it about whether the
# original request was HTTPS. Without it the app believes every request arrived on plain
# HTTP, because by the time it reaches this process it has.
CMD ["uvicorn", "neutral.web.app:app", \
     "--host", "0.0.0.0", "--port", "8080", \
     "--forwarded-allow-ips", "*", \
     "--log-level", "warning"]
