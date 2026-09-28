"""The learned self-presentation detector: Laya's encoder with a trained decision layer.

Keyword rules catch "I spent three weeks on it" and "my mom says it's perfect". They have
no word for "I haven't slept in days working on this" or "this is my baby". On the broad
set's held-out half, adding this detector to the rules caught 3 more of 42 things that
should go and lost nothing that had to stay (RESULTS.md, 2026-09-28).

It is optional. Laya needs PyTorch and an 808 MB model, and is not a dependency of
Neutral; where it is not installed, `detector()` returns None and the rules decide alone.
`NEUTRAL_LEARNED=off` turns it off where it is installed. Any failure while it runs
counts as "no", never as an error (S4): the rules' decision stands.

The decision layer is `data/self_presentation_probe.json`, produced by
`tools/train_self_presentation.py` from `datasets/relevance/v1/train_self_presentation.yaml`.
"""

from __future__ import annotations

import json
import math
import os
from functools import lru_cache
from pathlib import Path

PROBE = Path(__file__).resolve().parent / "data" / "self_presentation_probe.json"

_embed = None
_probe: dict | None = None
_broken = False


def available() -> bool:
    if os.environ.get("NEUTRAL_LEARNED", "").strip().lower() in ("off", "0", "false", "no"):
        return False
    if not PROBE.is_file():
        return False
    try:
        import laya  # noqa: F401
    except ImportError:
        return False
    return True


def _load() -> bool:
    global _embed, _probe, _broken
    if _embed is not None:
        return True
    if _broken:
        return False
    try:
        from laya import load
        from laya.shortlist import embed_fn_from_agent

        _probe = json.loads(PROBE.read_text())
        _embed = embed_fn_from_agent(load(_probe["model"]), max_length=_probe["max_length"])
        return True
    except Exception as exc:  # noqa: BLE001 - optional component; the rules stand without it
        _broken = True
        print(f"[learned] the self-presentation detector could not load and is off: {exc}")
        return False


@lru_cache(maxsize=4096)
def probability(clause: str) -> float:
    """How likely this clause is the person asking presenting themselves, 0 to 1."""
    if not _load():
        return 0.0
    try:
        vector = _embed([clause])[0]
        norm = math.sqrt(float((vector * vector).sum())) or 1.0
        z = _probe["intercept"] + sum(
            c * float(v) / norm for c, v in zip(_probe["coef"], vector, strict=True)
        )
        return 1.0 / (1.0 + math.exp(-z))
    except Exception as exc:  # noqa: BLE001
        print(f"[learned] a clause could not be scored and was left to the rules: {exc}")
        return 0.0


def _is_self_presentation(clause: str) -> bool:
    return probability(clause) >= _probe["threshold"] if _load() else False


def detector():
    """The detector for mechanisms/self_presentation.py, or None where it cannot run."""
    return _is_self_presentation if available() else None
