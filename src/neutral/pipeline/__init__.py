"""The Neutral pipeline: DETECT, DECIDE, TRANSFORM, DISPATCH, RESTORE, RECORD.

NOT BUILT YET. This is Phase 0; the project is building the measurement before the
product, deliberately. The interface is defined here because the safety invariant tests
in tests/test_invariants.py are written against it, and those tests exist before the code
they constrain.

Phase 1 will implement Mechanism 1 (identity substitution) behind this same signature.
"""

from __future__ import annotations

from neutral.core import NeutralResult

NOT_BUILT_MESSAGE = (
    "The Neutral pipeline has not been built yet.\n"
    "\n"
    "This is expected. The project is in Phase 0, which builds the measurement harness\n"
    "before any rewriting code, so that the problem can be measured before anything\n"
    "claims to solve it. See CLAUDE.md section 5 for the build order.\n"
    "\n"
    "Nothing is broken. To measure the current, un-rewritten behaviour of the model,\n"
    "run:  make eval"
)


def process(
    prompt: str,
    *,
    adapter: object,
    mechanisms: tuple[str, ...] = (),
    comparison_framing: bool = False,
) -> NeutralResult:
    """Run one prompt through Neutral and return a fully auditable result.

    Arrives in Phase 1. Raises until then, with a message that explains rather than
    dumping a stack trace at someone who cannot read one.
    """
    raise NotImplementedError(NOT_BUILT_MESSAGE)
