"""Turning a run into a JSON file and an HTML page a non-engineer can read.

The page leads with the thing that is actually true - the gap between how much answers
differ when identity changes and how much they differ anyway - and shows the confidence
interval on every number. Where an interval crosses zero the page says so in words, not
only in geometry, because a reader should not have to interpret a chart to find out that
a result means nothing.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from html import escape
from pathlib import Path

from neutral.eval.stats import Interval, describe
from neutral.invariants import BANNER

# Dot-and-interval geometry.
ROW_H = 30
PLOT_W = 460
LABEL_W = 230
PAD = 18


def _summary_dict(summary) -> dict:
    effect, signal, noise = summary.effect(), summary.signal(), summary.noise()
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "subject_model": summary.subject_model,
        "judge_model": summary.judge_model,
        "runs_per_variant": summary.runs_per_variant,
        "dataset_hash": summary.dataset_hash,
        "rubric_version": summary.rubric_version,
        "slice": summary.slice_name,
        "is_baseline": not summary.partial,
        "pairs_available": summary.pairs_available,
        "pairs_total": len(summary.results),
        "pairs_usable": len(summary.usable()),
        "api_calls": summary.total_calls,
        "failures": summary.failures,
        "refusals": summary.refusals,
        "refusal_detail": summary.refusal_report(),
        "cost_usd": round(summary.cost_usd, 2),
        "seconds": round(summary.seconds, 1),
        "headline": {
            "effect": _iv(effect),
            "cross_variant_divergence": _iv(signal),
            "within_variant_noise_floor": _iv(noise),
            "effect_detected": effect.excludes_zero,
            "plain_english": describe(effect, noise, signal),
        },
        "by_component": {k: _iv(v) for k, v in summary.by_component().items()},
        "by_category": {k: _iv(v) for k, v in summary.by_group(lambda p: p.category).items()},
        "by_signal": {k: _iv(v) for k, v in summary.by_group(lambda p: p.signal).items()},
        "by_pair": [
            {
                "id": r.pair.id,
                "category": r.pair.category,
                "signal": r.pair.signal,
                "effect": round(r.effect, 2),
                "comparisons": len(r.cross),
            }
            for r in summary.usable()
        ],
    }


# What each internal name is called on the page. Anything not listed falls back to
# replacing underscores, so a new component never renders as a raw identifier.
LABELS = {
    "favourability": "How positive the answer is",
    "recommendation_strength": "How strongly it recommends",
    "criticism_specificity": "How specific the criticism is",
    "hedging": "How much it hedges",
    "lexical": "How differently it is worded",
    "numeric": "The rating it gave",
    "defect": "Whether it caught the real bug",
    "performance_review": "Performance review",
    "hiring_recommendation": "Hiring recommendation",
    "salary_negotiation": "Salary negotiation",
    "promotion_readiness": "Promotion readiness",
    "written_work_critique": "Critique of written work",
    "technical_judgement": "Technical judgement",
    "drafting_feedback": "Feedback on drafts",
    "decision_advice": "Decision advice",
    "name_gender": "Name implying gender",
    "name_nationality": "Name implying nationality",
    "pronoun": "Pronoun",
    "seniority": "Seniority of the asker",
    "age": "Age",
    "authorship": "Who wrote it",
}


def label_for(key: str) -> str:
    return LABELS.get(key, key.replace("_", " ").capitalize())


def _iv(i: Interval) -> dict:
    return {
        "mean": round(i.mean, 2),
        "ci_low": round(i.low, 2),
        "ci_high": round(i.high, 2),
        "n": i.n,
        "excludes_zero": i.excludes_zero,
    }


def write_json(summary, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_summary_dict(summary), indent=2) + "\n")
    return path


def _forest(rows: list[tuple[str, Interval]], caption: str) -> str:
    """A dot-and-interval plot: one row per group, a dot at the mean, whiskers to the
    interval bounds, and an emphasised line at zero.

    Whether an interval crosses zero is the whole question, so it is carried by geometry
    rather than by colour - nothing here depends on telling two hues apart.
    """
    if not rows:
        return "<p class='empty'>No data.</p>"

    lows = [i.low for _, i in rows] + [0.0]
    highs = [i.high for _, i in rows] + [0.0]
    lo, hi = min(lows), max(highs)
    span = (hi - lo) or 1.0
    lo, hi = lo - span * 0.12, hi + span * 0.12
    span = hi - lo

    def x(v: float) -> float:
        return LABEL_W + PAD + (v - lo) / span * PLOT_W

    # rows*ROW_H + 24 is the axis; + 34 the caption baseline; + 10 for the descender.
    height = len(rows) * ROW_H + 68
    zero = x(0.0)
    parts = [
        f'<svg class="forest" viewBox="0 0 {LABEL_W + PLOT_W + PAD * 3} {height}" '
        f'role="img" aria-label="{escape(caption)}">'
    ]

    parts.append(
        f'<line class="zero" x1="{zero:.1f}" y1="8" x2="{zero:.1f}" y2="{len(rows) * ROW_H + 16}"/>'
    )

    for idx, (label, iv) in enumerate(rows):
        y = 22 + idx * ROW_H
        detected = "yes" if iv.excludes_zero else "no"
        tip = (
            f"{label}: {iv.mean:.1f} points "
            f"(95% confidence interval {iv.low:.1f} to {iv.high:.1f}, "
            f"{iv.n} pairs). Effect distinguishable from zero: {detected}."
        )
        parts.append(f"<g><title>{escape(tip)}</title>")
        parts.append(
            f'<text class="rowlabel" x="{LABEL_W}" y="{y + 4}" text-anchor="end">'
            f"{escape(label)}</text>"
        )
        parts.append(
            f'<line class="whisker" x1="{x(iv.low):.1f}" y1="{y}" x2="{x(iv.high):.1f}" y2="{y}"/>'
        )
        for bound in (iv.low, iv.high):
            parts.append(
                f'<line class="cap" x1="{x(bound):.1f}" y1="{y - 5}" '
                f'x2="{x(bound):.1f}" y2="{y + 5}"/>'
            )
        dot = "dot" if iv.excludes_zero else "dot hollow"
        parts.append(f'<circle class="{dot}" cx="{x(iv.mean):.1f}" cy="{y}" r="5"/>')
        parts.append("</g>")

    axis_y = len(rows) * ROW_H + 24
    parts.append(
        f'<line class="axis" x1="{LABEL_W + PAD}" y1="{axis_y}" '
        f'x2="{LABEL_W + PAD + PLOT_W}" y2="{axis_y}"/>'
    )
    for value in (lo + span * 0.05, 0.0, hi - span * 0.05):
        parts.append(
            f'<text class="tick" x="{x(value):.1f}" y="{axis_y + 16}" '
            f'text-anchor="middle">{value:.0f}</text>'
        )
    parts.append(
        f'<text class="tick" x="{LABEL_W + PAD + PLOT_W / 2:.0f}" y="{axis_y + 34}" '
        f'text-anchor="middle">effect in points - right of the line means identity '
        f"changed the answer</text>"
    )
    parts.append("</svg>")
    return "".join(parts)


def _table(rows: list[tuple[str, Interval]]) -> str:
    body = "".join(
        f"<tr><td>{escape(label)}</td><td class='num'>{iv.mean:.1f}</td>"
        f"<td class='num'>{iv.low:.1f} to {iv.high:.1f}</td>"
        f"<td class='num'>{iv.n}</td>"
        f"<td>{'yes' if iv.excludes_zero else 'no'}</td></tr>"
        for label, iv in rows
    )
    return (
        "<table><thead><tr><th>Group</th><th class='num'>Effect</th>"
        "<th class='num'>95% interval</th><th class='num'>Pairs</th>"
        "<th>Distinguishable from zero</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


def _section(title: str, note: str, rows: list[tuple[str, Interval]]) -> str:
    return (
        f"<section><h2>{escape(title)}</h2><p class='note'>{escape(note)}</p>"
        f"{_forest(rows, title)}"
        f"<details><summary>Show as a table</summary>{_table(rows)}</details></section>"
    )


CSS = """
:root {
  --surface-1:#fcfcfb; --plane:#f9f9f7; --ink:#0b0b0b; --ink-2:#52514e;
  --muted:#898781; --grid:#e1e0d9; --axis:#c3c2b7; --series-1:#2a78d6;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --surface-1:#1a1a19; --plane:#0d0d0d; --ink:#fff; --ink-2:#c3c2b7;
    --muted:#898781; --grid:#2c2c2a; --axis:#383835; --series-1:#3987e5;
    color-scheme: dark;
  }
}
:root[data-theme="dark"] {
  --surface-1:#1a1a19; --plane:#0d0d0d; --ink:#fff; --ink-2:#c3c2b7;
  --muted:#898781; --grid:#2c2c2a; --axis:#383835; --series-1:#3987e5;
  color-scheme: dark;
}
* { box-sizing: border-box; }
body {
  margin:0; background:var(--plane); color:var(--ink);
  font:15px/1.6 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif;
}
.wrap { max-width:860px; margin:0 auto; padding:32px 16px 64px; }
.banner {
  background:#fab219; color:#0b0b0b; padding:10px 16px; border-radius:8px;
  font-weight:600; margin-bottom:28px;
}
h1 { font-size:26px; margin:0 0 4px; letter-spacing:-0.01em; }
h2 { font-size:18px; margin:0 0 4px; letter-spacing:-0.01em; }
.sub { color:var(--ink-2); margin:0 0 28px; }
section { background:var(--surface-1); border:1px solid var(--grid);
  border-radius:12px; padding:20px; margin-bottom:20px; }
.hero { font-size:44px; font-weight:650; letter-spacing:-0.02em; margin:6px 0 2px; }
.hero-ci { color:var(--ink-2); font-size:15px; margin:0 0 14px; }
.verdict { font-size:16px; line-height:1.65; margin:0; }
.note { color:var(--ink-2); font-size:14px; margin:0 0 14px; }
.forest { width:100%; height:auto; display:block; margin:6px 0 10px; }
.rowlabel { fill:var(--ink-2); font-size:13px; }
.whisker { stroke:var(--series-1); stroke-width:2; }
.cap { stroke:var(--series-1); stroke-width:2; }
.dot { fill:var(--series-1); stroke:var(--surface-1); stroke-width:2; }
.dot.hollow { fill:var(--surface-1); stroke:var(--series-1); stroke-width:2; }
.zero { stroke:var(--axis); stroke-width:2; stroke-dasharray:4 4; }
.axis { stroke:var(--axis); stroke-width:1; }
.tick { fill:var(--muted); font-size:11px; }
table { border-collapse:collapse; width:100%; font-size:14px; margin-top:12px; }
th,td { text-align:left; padding:7px 10px; border-bottom:1px solid var(--grid); }
th { color:var(--ink-2); font-weight:600; }
.num { text-align:right; font-variant-numeric:tabular-nums; }
details summary { cursor:pointer; color:var(--ink-2); font-size:14px; margin-top:6px; }
dl { display:grid; grid-template-columns:auto 1fr; gap:6px 18px; margin:0; font-size:14px; }
dt { color:var(--ink-2); }
dd { margin:0; font-variant-numeric:tabular-nums; }
.warn { color:#d03b3b; font-weight:600; }
.warnbanner { background:#d03b3b; color:#fff; }
.empty { color:var(--muted); }
@media (max-width:620px) { .hero { font-size:34px; } .wrap { padding:20px 16px 48px; } }
"""


def write_html(summary, path: Path) -> Path:
    data = _summary_dict(summary)
    head = data["headline"]
    effect, signal, noise = summary.effect(), summary.signal(), summary.noise()

    rows_component = [(label_for(k), v) for k, v in summary.by_component().items()]
    rows_category = [(label_for(k), v) for k, v in summary.by_group(lambda p: p.category).items()]
    rows_signal = [(label_for(k), v) for k, v in summary.by_group(lambda p: p.signal).items()]

    component_section = _section(
        "By what was measured",
        "Each component of the divergence score, on its own. A component whose interval "
        "crosses the dashed line is not distinguishable from the model's own randomness.",
        rows_component,
    )

    partial_note = ""
    if summary.partial:
        partial_note = (
            f'<div class="banner warnbanner">Sample of {len(summary.results)} pairs, '
            f"not the baseline. The baseline needs all {summary.pairs_available}. A "
            f"sample this size cannot support a conclusion - treat these numbers as a "
            f"demonstration of what the harness does, not as a result.</div>"
        )

    failed_note = ""
    if summary.failures:
        share = summary.failures / max(1, summary.total_calls // 2) * 100
        cls = "warn" if share > 10 else ""
        failed_note = (
            f"<p class='{cls}'>{summary.failures} of "
            f"{summary.total_calls // 2} answers failed or were refused "
            f"({share:.1f}%) and were excluded from scoring.</p>"
        )

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Neutral - divergence report</title>
<style>{CSS}</style></head>
<body><div class="wrap">
<div class="banner">{escape(BANNER)}</div>
{partial_note}

<h1>Does the answer change with who is asking?</h1>
<p class="sub">{escape(summary.subject_model)} &middot; {summary.runs_per_variant} runs per
variant &middot; {len(summary.usable())} of {len(summary.results)} pairs usable &middot;
dataset {escape(summary.dataset_hash[:16])}</p>

<section>
  <h2>The headline</h2>
  <p class="note">How much more the answers differ when the identity signal changes than
  when nothing changes at all.</p>
  <p class="hero">{effect.mean:+.1f} points</p>
  <p class="hero-ci">95% confidence interval {effect.low:.1f} to {effect.high:.1f},
  across {effect.n} pairs</p>
  <p class="verdict">{escape(head["plain_english"])}</p>
</section>

<section>
  <h2>The two numbers behind it</h2>
  <p class="note">The finding is the gap between these. Neither means much alone.</p>
  <dl>
    <dt>Identity changed</dt>
    <dd>{signal.mean:.1f} ({signal.low:.1f} to {signal.high:.1f})</dd>
    <dt>Nothing changed</dt>
    <dd>{noise.mean:.1f} ({noise.low:.1f} to {noise.high:.1f})</dd>
    <dt>Gap</dt>
    <dd>{effect.mean:+.1f} ({effect.low:.1f} to {effect.high:.1f})</dd>
  </dl>
</section>

{component_section}
{_section("By task category", "Where the effect shows up, and where it does not.", rows_category)}
{_section("By identity signal", "Which kind of signal moves the answer.", rows_signal)}

<section>
  <h2>How this run was done</h2>
  <dl>
    <dt>Model measured</dt><dd>{escape(summary.subject_model)}</dd>
    <dt>Model scoring</dt><dd>{escape(summary.judge_model)}</dd>
    <dt>Rubric version</dt><dd>{escape(summary.rubric_version)}</dd>
    <dt>Dataset fingerprint</dt><dd>{escape(summary.dataset_hash)}</dd>
    <dt>Dataset slice</dt><dd>{escape(summary.slice_name)}</dd>
    <dt>Runs per variant</dt><dd>{summary.runs_per_variant}</dd>
    <dt>API calls</dt><dd>{summary.total_calls}</dd>
    <dt>Cost</dt><dd>${summary.cost_usd:,.2f}</dd>
    <dt>Time taken</dt><dd>{summary.seconds / 60:.1f} minutes</dd>
    <dt>Generated</dt><dd>{escape(data["generated_at"])}</dd>
  </dl>
  {failed_note}
  <p class="note">The judge never saw which variant it was scoring, never saw the other
  answer, and never saw the name, pronoun or role that differed between them.</p>
</section>

</div></body></html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html)
    return path
