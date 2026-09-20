"""Settings, loaded from .env.

Every error in here is written for someone who is not going to read a stack trace.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent


class ConfigError(RuntimeError):
    """Something is missing from the setup, with instructions for fixing it."""


@dataclass(frozen=True)
class Settings:
    api_key: str
    subject_model: str
    judge_model: str
    runs_per_variant: int
    concurrency: int
    audit_retain: bool
    audit_retention_hours: int

    @property
    def api_key_present(self) -> bool:
        return bool(self.api_key)


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(
            f"{name} in your .env file is {raw!r}, which is not a whole number.\n"
            f"Set it to a number, or delete the line to use the default ({default})."
        ) from exc


def load_settings(env_file: Path | None = None) -> Settings:
    load_dotenv(env_file or ROOT / ".env", override=False)

    settings = Settings(
        api_key=os.environ.get("ANTHROPIC_API_KEY", "").strip(),
        subject_model=os.environ.get("NEUTRAL_SUBJECT_MODEL", "claude-opus-5").strip(),
        judge_model=os.environ.get("NEUTRAL_JUDGE_MODEL", "claude-sonnet-5").strip(),
        runs_per_variant=_int("NEUTRAL_RUNS_PER_VARIANT", 5),
        concurrency=_int("NEUTRAL_CONCURRENCY", 8),
        audit_retain=os.environ.get("AUDIT_RETAIN", "false").strip().lower() == "true",
        audit_retention_hours=_int("AUDIT_RETENTION_HOURS", 24),
    )

    if settings.runs_per_variant < 5:
        raise ConfigError(
            f"NEUTRAL_RUNS_PER_VARIANT is {settings.runs_per_variant}, but the minimum "
            f"is 5.\n"
            f"Below five runs, the model's own randomness cannot be told apart from a "
            f"real difference caused by identity, and the result would not mean "
            f"anything."
        )

    if settings.judge_model == settings.subject_model:
        raise ConfigError(
            f"NEUTRAL_SUBJECT_MODEL and NEUTRAL_JUDGE_MODEL are both "
            f"{settings.subject_model!r}.\n"
            f"The model being measured must not also grade its own answers. Set them to "
            f"two different models in your .env file."
        )

    return settings


MISSING_KEY_HELP = """No Anthropic API key found.

To fix this:

  1. Copy the example file:      cp .env.example .env
  2. Open .env in a text editor.
  3. Replace sk-ant-... on the ANTHROPIC_API_KEY line with your own key.
     You can create one at https://console.anthropic.com/settings/keys

.env is never committed to the repository."""


def require_api_key(settings: Settings) -> str:
    if not settings.api_key_present:
        raise ConfigError(MISSING_KEY_HELP)
    return settings.api_key
