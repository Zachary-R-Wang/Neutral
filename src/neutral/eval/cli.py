"""Command line entry point. Everything the founder runs goes through here.

Rule for this file: no error message may consist only of a stack trace. Each one says
what went wrong and what to do about it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from neutral.config import ConfigError, Settings, load_settings
from neutral.eval.dataset import CATEGORIES, DatasetError, dataset_hash, load_dataset

ROOT = Path(__file__).resolve().parent.parent.parent.parent
DATASET_DIR = ROOT / "datasets" / "v1"

TICK = "  ok  "
CROSS = " FAIL "
WARN = " note "


def _check_live_api(settings: Settings) -> tuple[bool, str]:
    from neutral.adapters.anthropic_api import AnthropicAdapter

    adapter = AnthropicAdapter(
        api_key=settings.api_key,
        model=settings.subject_model,
        max_tokens=16,
        effort="low",
    )
    result = adapter.complete("Reply with the single word: ready")
    if result.error:
        return False, result.error
    return True, f"{settings.subject_model} answered"


def doctor(args: argparse.Namespace) -> int:
    """Check that everything needed to run an evaluation is in place."""
    print("Checking the project is ready to run.\n")
    problems: list[str] = []

    version = sys.version_info
    if version >= (3, 11):
        print(f"{TICK} Python {version.major}.{version.minor}.{version.micro}")
    else:
        print(f"{CROSS} Python {version.major}.{version.minor} - 3.11 or newer is needed")
        problems.append("Run `make dev` to rebuild the environment.")

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"{CROSS} Settings\n\n{exc}\n")
        return 1

    if (ROOT / ".env").exists():
        print(f"{TICK} .env file found")
    else:
        print(f"{CROSS} No .env file")
        problems.append("Run: cp .env.example .env    then put your API key in it.")

    if settings.api_key_present:
        print(f"{TICK} API key present")
    else:
        print(f"{CROSS} No API key in .env")
        problems.append(
            "Open .env and set ANTHROPIC_API_KEY. Get a key at\n"
            "    https://console.anthropic.com/settings/keys"
        )

    print(f"{TICK} Model being measured: {settings.subject_model}")
    print(f"{TICK} Model doing the scoring: {settings.judge_model}")
    print(f"{TICK} Runs per variant: {settings.runs_per_variant}")

    try:
        pairs = load_dataset(DATASET_DIR)
        by_category = {c: sum(1 for p in pairs if p.category == c) for c in CATEGORIES}
        print(f"{TICK} Dataset: {len(pairs)} matched pairs, all valid")
        for category, count in by_category.items():
            marker = "   " if count else " ! "
            print(f"      {marker}{category:24} {count:3d}")
        print(f"{TICK} Dataset fingerprint: {dataset_hash(pairs)[:16]}")
    except DatasetError as exc:
        print(f"{CROSS} Dataset\n\n{exc}\n")
        problems.append("Fix the dataset file named above.")

    if settings.audit_retain:
        print(f"{WARN} AUDIT_RETAIN is on - identifying data will be written to disk")

    if settings.api_key_present and not args.offline:
        print("\n  Calling the API once to check the key works...")
        ok, detail = _check_live_api(settings)
        print(f"{TICK if ok else CROSS} Live API check: {detail}")
        if not ok:
            problems.append("Fix the API problem above, then run `make dev` again.")

    print()
    if problems:
        print("Not ready yet. To fix:\n")
        for item in problems:
            print(f"  - {item}")
        print()
        return 1

    print("Everything is ready. Run `make eval` to measure the baseline.")
    return 0


def show_dataset(args: argparse.Namespace) -> int:
    """Print the matched pairs so they can be checked by eye."""
    try:
        pairs = load_dataset(DATASET_DIR)
    except DatasetError as exc:
        print(exc)
        return 1

    selected = [p for p in pairs if not args.pair or p.id == args.pair]
    if not selected:
        print(f"No pair with id {args.pair!r}. Available: {', '.join(p.id for p in pairs)}")
        return 1

    import difflib

    for pair in selected:
        a, b = pair.render("a"), pair.render("b")
        print("=" * 78)
        print(f"{pair.id}  [{pair.category}]  signal: {pair.signal}")
        print(f"  A = {pair.a.label}")
        print(f"  B = {pair.b.label}")
        print("=" * 78)
        if args.full:
            print("\n--- variant A ---\n")
            print(a)
            print("--- variant B ---\n")
            print(b)
        words_a, words_b = a.split(), b.split()
        diff = list(difflib.ndiff(words_a, words_b))
        same = sum(1 for w in diff if w.startswith("  "))
        only_a = [w[2:] for w in diff if w.startswith("- ")]
        only_b = [w[2:] for w in diff if w.startswith("+ ")]
        print(f"\n  {same} words identical in both prompts")
        print(f"  only in A: {' '.join(only_a)}")
        print(f"  only in B: {' '.join(only_b)}")
        print()

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="neutral",
        description="Measure whether a model's answers change with who appears to ask.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_doctor = sub.add_parser("doctor", help="check the project is ready to run")
    p_doctor.add_argument("--offline", action="store_true", help="skip the live API check")
    p_doctor.set_defaults(func=doctor)

    p_dataset = sub.add_parser("dataset", help="show the matched pairs")
    p_dataset.add_argument("--pair", help="show only this pair id")
    p_dataset.add_argument("--full", action="store_true", help="print both prompts in full")
    p_dataset.set_defaults(func=show_dataset)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"\n{exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
