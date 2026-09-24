"""The web app. One page, two routes, no database.

There is no database on purpose. S5 says identity mappings live in memory for one request
and are then discarded, and nothing identifying is written to disk unless AUDIT_RETAIN is
set. The simplest way to satisfy that is to have nowhere to write to. SQLite arrives when
audit retention does, and not before.
"""

from __future__ import annotations

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse

from neutral.adapters.anthropic_api import AnthropicAdapter
from neutral.config import ConfigError, load_settings
from neutral.pipeline import process
from neutral.web.page import page

app = FastAPI(title="Neutral", docs_url=None, redoc_url=None)

NO_KEY = (
    "No Anthropic API key is configured, so Neutral cannot reach a model. Copy "
    ".env.example to .env and put your key on the ANTHROPIC_API_KEY line, then restart."
)


def _adapter():
    settings = load_settings()
    if not settings.api_key_present:
        raise ConfigError(NO_KEY)
    return AnthropicAdapter(
        api_key=settings.api_key,
        model=settings.subject_model,
        max_tokens=4000,
        effort="medium",
    )


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    return HTMLResponse(page())


@app.post("/", response_class=HTMLResponse)
def run(prompt: str = Form(default="")) -> HTMLResponse:
    """Run one prompt. Defined with `def`, so FastAPI runs it off the event loop."""
    text = (prompt or "").strip()
    if not text:
        return HTMLResponse(page(prompt="", error="Type a prompt first."))

    try:
        adapter = _adapter()
    except ConfigError as exc:
        return HTMLResponse(page(prompt=text, error=str(exc)))

    try:
        result = process(text, adapter=adapter)
    except Exception as exc:  # noqa: BLE001 - the page must never show a stack trace
        return HTMLResponse(
            page(
                prompt=text,
                error=f"Something went wrong and nothing was sent to the model: {exc}",
            )
        )

    # The result holds the real names in its audit trail. It is rendered and dropped;
    # nothing here writes it anywhere.
    return HTMLResponse(page(prompt=text, result=result))


@app.get("/health")
def health() -> dict:
    return {"ok": True}
