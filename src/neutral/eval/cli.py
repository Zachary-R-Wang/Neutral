"""Command line entry point. Everything the founder runs goes through here.

Rule for this file: no error message may consist only of a stack trace. Each one says
what went wrong and what to do about it.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from neutral.config import ConfigError, Settings, load_settings, require_api_key
from neutral.eval.dataset import DatasetError, dataset_hash, load_dataset, spread_sample
from neutral.eval.stats import describe

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

    # The website and the measurement need keys from different places, and confusing the
    # two is how somebody concludes the product is broken when it is not. The website asks
    # each person for their own key in the browser and never reads .env. `make eval` runs
    # unattended against a fixed model, so that one does need a key on disk.
    website_only = bool(getattr(args, "web", False))

    if (ROOT / ".env").exists():
        print(f"{TICK} .env file found")
    elif website_only:
        print(f"{TICK} No .env file, which is fine - the website asks for a key in the browser")
    else:
        print(f"{CROSS} No .env file")
        problems.append("Run: cp .env.example .env    then put your API key in it.")

    if settings.api_key_present:
        print(f"{TICK} API key present")
    elif website_only:
        print(f"{TICK} No API key on disk - you will paste one into the website when it opens")
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
        print(f"{TICK} Dataset: {len(pairs)} matched pairs, all valid")
        for slice_name in sorted({p.slice_name for p in pairs}):
            in_slice = [p for p in pairs if p.slice_name == slice_name]
            label = "baseline" if slice_name == "hr" else "reported separately"
            print(f"      {slice_name} ({len(in_slice)} pairs, {label})")
            for category in sorted({p.category for p in in_slice}):
                count = sum(1 for p in in_slice if p.category == category)
                print(f"        {category:24} {count:3d}")
        print(f"{TICK} Dataset fingerprint: {dataset_hash(pairs)[:16]}")
    except DatasetError as exc:
        print(f"{CROSS} Dataset\n\n{exc}\n")
        if not website_only:
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

    if website_only:
        print("Everything is ready.")
    else:
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


BASELINE_PATH = ROOT / "BASELINE.md"

THRESHOLD_NOT_SET = """The pass threshold has not been set yet, so this run is refused.

Before measuring anything, you have to write down how much Neutral must reduce
divergence before you would say it works - and commit to it in BASELINE.md.

This is not bureaucracy. If you pick the threshold after seeing the number, any
result can be made to look like a success, and you will have spent months proving
something to yourself rather than to a customer. Your own CLAUDE.md puts it this
way: "Choosing the threshold after seeing the results is how founders fool
themselves."

To set it, open BASELINE.md and replace "*not set*" on the Threshold row with a
number, then run this again.

If you only want to check the plumbing works without seeing any result, run:

    make eval ARGS="--smoke"

That makes a handful of calls, tells you whether the API and the judge are
working, and deliberately shows you no divergence numbers at all."""


def threshold_is_set() -> bool:
    """True once BASELINE.md carries a real pass threshold."""
    if not BASELINE_PATH.exists():
        return False
    text = BASELINE_PATH.read_text()
    for line in text.splitlines():
        if line.strip().startswith("| Threshold"):
            value = line.split("|")[2].strip() if line.count("|") >= 3 else ""
            return bool(value) and value not in ("*not set*", "-", "—", "not set")
    return False


def _adapters(settings: Settings):
    from neutral.adapters.anthropic_api import AnthropicAdapter

    require_api_key(settings)
    subject = AnthropicAdapter(
        api_key=settings.api_key, model=settings.subject_model, max_tokens=8000, effort="high"
    )
    judge = AnthropicAdapter(
        api_key=settings.api_key, model=settings.judge_model, max_tokens=4000, effort="low"
    )
    return subject, judge


def neutral_transform(prompt: str) -> str:
    """What Neutral would actually send for this prompt.

    Uses pipeline.preview, which is the same detection, policy gate, substitution and S1
    check a real request goes through - everything except asking the model. So this arm
    measures the product as built, not an idealised version of it: a prompt the safety
    gate holds is sent unchanged here exactly as it would be in the web interface.

    Fails open to the original, as S4 requires. A rewriting that cannot be proved
    faithful must not be sent, and the measurement has to reflect that rather than
    quietly dropping the pair.
    """
    from neutral.pipeline import preview

    try:
        return preview(prompt).processed_prompt
    except Exception:  # noqa: BLE001 - S4: fail open to the original, never to a mangle
        return prompt


def run_eval(args: argparse.Namespace) -> int:
    from neutral.eval.report import write_html, write_json
    from neutral.eval.runner import estimate_run_cost, no_transform, run_evaluation
    from neutral.eval.scoring import RUBRIC_VERSION

    settings = load_settings()
    pairs = load_dataset(DATASET_DIR)

    if args.slice != "all":
        pairs = [p for p in pairs if p.slice_name == args.slice]
    available = len(pairs)
    if args.smoke:
        pairs = spread_sample(pairs, 2)
    elif args.limit:
        pairs = spread_sample(pairs, args.limit)
    partial = len(pairs) < available

    if not pairs:
        print(f"No pairs in slice {args.slice!r}.")
        return 1

    runs = 2 if args.smoke else settings.runs_per_variant
    calls, cost = estimate_run_cost(pairs, runs, settings.subject_model, settings.judge_model)

    print(
        f"\n  Pairs:            {len(pairs)}" + (f" of {available} (a sample)" if partial else "")
    )
    print(f"  Runs per variant: {runs}")
    arm = "Neutral in the path" if args.with_neutral else "baseline (no Neutral)"
    print(f"  Arm:              {arm}")
    print(f"  Model measured:   {settings.subject_model}")
    print(f"  Model scoring:    {settings.judge_model}")
    print(f"  API calls:        {calls}")
    print(f"  Estimated cost:   ${cost:,.2f}\n")

    if args.estimate:
        print("  Estimate only. Nothing was sent and nothing was charged.\n")
        return 0

    if not args.smoke and not threshold_is_set():
        print(THRESHOLD_NOT_SET + "\n")
        return 1

    if not args.yes:
        try:
            reply = input("  Type yes to run this and spend that money: ").strip().lower()
        except EOFError:
            reply = ""
        if reply != "yes":
            print("\n  Cancelled. Nothing was sent and nothing was charged.\n")
            return 1
        print()

    subject, judge = _adapters(settings)

    transform = no_transform
    if args.with_neutral:
        from neutral.detect import ner_model_name

        print(f"  Detector:         {ner_model_name()}")
        transform = neutral_transform

    summary = run_evaluation(
        pairs,
        subject,
        judge,
        runs_per_variant=runs,
        dataset_hash=dataset_hash(pairs),
        rubric_version=RUBRIC_VERSION,
        slice_name=args.slice,
        partial=partial,
        pairs_available=available,
        concurrency=settings.concurrency,
        transform=transform,
    )

    answers = summary.total_calls // 2
    print(f"\n  Done in {summary.seconds / 60:.1f} minutes. Actual cost ${summary.cost_usd:,.2f}.")
    print(f"  {answers - summary.failures} of {answers} answers scored successfully.")

    if args.smoke:
        print("\n  SMOKE TEST - no divergence numbers are shown by design.")
        print("  It checks the API, the judge and the scoring plumbing, nothing else.")
        ok = summary.failures == 0 and len(summary.usable()) == len(summary.results)
        if ok:
            print("\n  Everything works. Set the pass threshold in BASELINE.md, then")
            print("  run `make eval` for the real measurement.\n")
            return 0
        print(f"\n  Something is not working: {summary.failures} failures.")
        for result in summary.results:
            for a in result.answers:
                if a.error or a.judge_error:
                    print(f"    {a.pair_id} {a.variant}: {a.error or a.judge_error}")
        print()
        return 1

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = write_json(summary, ROOT / "reports" / f"eval-{stamp}.json")
    html_path = write_html(summary, ROOT / "reports" / f"eval-{stamp}.html")

    problems = summary.validity()
    if problems:
        print("\n  " + "=" * 70)
        print("  THIS RUN IS NOT A VALID MEASUREMENT.")
        print("  " + "=" * 70)
        for problem in problems:
            print(f"\n  - {problem}")
        print(
            "\n  Numbers are printed below so you can see what happened, but they are"
            "\n  not a result and must not be recorded as one. The confidence interval"
            "\n  only knows about answers that arrived; it cannot see the ones that"
            "\n  did not.\n"
        )

    effect, signal, noise = summary.effect(), summary.signal(), summary.noise()
    if partial:
        print("\n  " + "!" * 70)
        print(f"  THIS IS A {len(pairs)}-PAIR SAMPLE, NOT THE BASELINE.")
        print(f"  The baseline needs all {available} pairs. A sample this size cannot")
        print("  support a conclusion - the interval will be wide and the number will")
        print("  move a lot between runs. It is for seeing what the harness does.")
        print("  " + "!" * 70)
    print("\n" + "=" * 74)
    print("  Identity changed:  " + str(signal))
    print("  Nothing changed:   " + str(noise))
    print("  The gap:           " + str(effect))
    print("=" * 74)
    print("\n  " + describe(effect, noise, signal).replace("\n", "\n  "))
    if problems:
        print("\n  NOT A BASELINE - see the reasons above.")
    print(f"\n  Full report: {html_path}")
    print(f"  Raw data:    {json_path}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Without this, Python block-buffers stdout when output is piped or redirected, so a
    # run that takes half an hour shows nothing at all until it finishes. Progress during
    # a long, paid run is not a luxury: it is how you find out something is wrong before
    # you have paid for all of it.
    sys.stdout.reconfigure(line_buffering=True)

    parser = argparse.ArgumentParser(
        prog="neutral",
        description="Measure whether a model's answers change with who appears to ask.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_doctor = sub.add_parser("doctor", help="check the project is ready to run")
    p_doctor.add_argument("--offline", action="store_true", help="skip the live API check")
    p_doctor.add_argument(
        "--web",
        action="store_true",
        help="checking before starting the website, where the key is entered in the browser",
    )
    p_doctor.set_defaults(func=doctor)

    p_dataset = sub.add_parser("dataset", help="show the matched pairs")
    p_dataset.add_argument("--pair", help="show only this pair id")
    p_dataset.add_argument("--full", action="store_true", help="print both prompts in full")
    p_dataset.set_defaults(func=show_dataset)

    p_run = sub.add_parser("run", help="measure divergence and write a report")
    p_run.add_argument("--slice", default="all", help="'hr' for the baseline only, or 'all'")
    p_run.add_argument("--limit", type=int, help="use only the first N pairs")
    p_run.add_argument(
        "--smoke", action="store_true", help="check the plumbing on 2 pairs and show no results"
    )
    p_run.add_argument(
        "--estimate", action="store_true", help="print the cost and exit without calling anything"
    )
    p_run.add_argument("--yes", action="store_true", help="skip the spend confirmation")
    p_run.add_argument(
        "--with-neutral",
        action="store_true",
        help="send prompts through Neutral first, instead of unchanged",
    )
    p_run.set_defaults(func=run_eval)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"\n{exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
