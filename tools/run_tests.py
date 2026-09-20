"""Run the test suite and explain the result in English.

Why this exists instead of a bare `pytest`:

The safety invariant tests in tests/test_invariants.py are written before the pipeline
they constrain, on purpose. Seven of them fail today and will keep failing until Phase 1
builds the rewriting pipeline. CLAUDE.md forbids skipping them or marking them xfail, so
they must genuinely run and genuinely fail.

That leaves a problem: a permanently red suite means nobody can tell an expected failure
from a real one. This wrapper solves that by separating the two, and - importantly - it
only tolerates the Phase 0 failures while the pipeline genuinely does not exist. The
moment neutral.pipeline.process stops raising NotImplementedError, those same failures
become real failures and this script starts reporting the suite as broken.

Nothing here changes, skips, or relaxes a test.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTEST = [sys.executable, "-m", "pytest"]

PIPELINE_TESTS_CLASS = "TestPipelineSatisfiesInvariants"


def run(args: list[str]) -> tuple[int, str]:
    result = subprocess.run(PYTEST + args, cwd=ROOT, capture_output=True, text=True, check=False)
    return result.returncode, result.stdout + result.stderr


def counts(output: str) -> tuple[int, int]:
    passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", output)) else 0
    failed = int(m.group(1)) if (m := re.search(r"(\d+) failed", output)) else 0
    return passed, failed


def pipeline_is_built() -> bool:
    """True once Phase 1 has implemented the pipeline."""
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from neutral.pipeline import process

        process("probe", adapter=None)
    except NotImplementedError:
        return False
    except Exception:
        return True
    return True


def main() -> int:
    print("Running the test suite.\n")

    harness_code, harness_out = run(["tests", "-m", "not invariant"])
    harness_passed, harness_failed = counts(harness_out)

    inv_code, inv_out = run(["tests", "-m", "invariant"])
    inv_passed, inv_failed = counts(inv_out)

    built = pipeline_is_built()

    print(f"  Measurement harness ............ {harness_passed} passed, {harness_failed} failed")
    print(f"  Safety checks themselves ....... {inv_passed} passed")
    print(f"  Pipeline safety invariants ..... {inv_failed} failed")
    print()

    real_failure = harness_failed > 0 or harness_code not in (0, 5)

    if inv_failed and not built:
        print("The pipeline invariant failures are expected right now.")
        print()
        print("  The project is in Phase 0: the measurement is built before the product.")
        print("  Those tests describe what the rewriting pipeline must never do. The")
        print("  pipeline does not exist yet, so they fail. They are written first so")
        print("  they cannot be quietly relaxed later to make a feature fit.")
        print()
        print("  They will turn green in Phase 1 - and if the pipeline is ever built in a")
        print("  way that breaks one of them, this command fails instead of explaining.")
    elif inv_failed and built:
        print("SAFETY INVARIANT FAILURE.")
        print()
        print("  The pipeline now exists, so these failures are real. A safety invariant")
        print("  from CLAUDE.md section 3 is being broken. Do not weaken the test.")
        print()
        print(inv_out[-3000:])
        real_failure = True

    if harness_failed:
        print("\nThe measurement harness has failing tests:\n")
        print(harness_out[-3000:])

    print()
    if real_failure:
        print("RESULT: something is broken. See above.")
        return 1

    print("RESULT: everything that should pass, passes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
