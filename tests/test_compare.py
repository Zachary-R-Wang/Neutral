"""Comparing the two arms.

The headline number of this whole project comes out of this file, so the arithmetic is
tested against cases where the right answer is known by construction rather than by
running it and seeing what it says.
"""

from __future__ import annotations

import json

import pytest

from neutral.eval.compare import compare, compare_reports


def _effects(**pairs: float) -> dict[str, float]:
    return dict(pairs)


class TestTheArithmetic:
    def test_halving_the_effect_is_a_fifty_percent_reduction(self):
        c = compare(_effects(a=10, b=10, c=10), _effects(a=5, b=5, c=5))
        assert c.reduction_pct == pytest.approx(50.0)
        assert c.baseline == 10 and c.neutral == 5

    def test_removing_the_effect_entirely_is_a_hundred_percent(self):
        c = compare(_effects(a=8, b=12), _effects(a=0, b=0))
        assert c.reduction_pct == pytest.approx(100.0)

    def test_no_change_is_zero_percent(self):
        c = compare(_effects(a=7, b=9), _effects(a=7, b=9))
        assert c.reduction_pct == pytest.approx(0.0)

    def test_making_it_worse_is_a_negative_reduction(self):
        c = compare(_effects(a=4, b=4), _effects(a=8, b=8))
        assert c.reduction_pct < 0
        assert c.worsened and not c.improved

    def test_only_pairs_present_in_both_arms_are_used(self):
        """A pair lost in one arm cannot contribute to a paired comparison."""
        c = compare(_effects(a=10, b=10, lost=100), _effects(a=5, b=5))
        assert c.pairs == 2
        assert c.baseline == pytest.approx(10.0)

    def test_no_shared_pairs_is_reported_as_nothing_rather_than_crashing(self):
        c = compare(_effects(a=1), _effects(b=1))
        assert c.pairs == 0 and c.reduction_pct == 0

    def test_a_zero_baseline_does_not_divide_by_zero(self):
        c = compare(_effects(a=0, b=0), _effects(a=0, b=0))
        assert c.reduction_pct == 0.0


class TestTheInterval:
    def test_a_consistent_improvement_excludes_zero(self):
        base = {f"p{i}": 10.0 for i in range(40)}
        neut = {f"p{i}": 4.0 for i in range(40)}
        c = compare(base, neut)
        assert c.improved
        assert c.change_high < 0
        assert c.reduction_low > 0

    def test_noise_with_no_real_change_does_not_exclude_zero(self):
        base = {f"p{i}": 10.0 + (i % 5) for i in range(40)}
        neut = {f"p{i}": 10.0 + ((i + 2) % 5) for i in range(40)}
        c = compare(base, neut)
        assert not c.improved and not c.worsened

    def test_it_is_paired_so_a_consistent_small_shift_is_still_detected(self):
        """Unpaired, this noise would swamp the signal. Paired, the shift is visible."""
        base = {f"p{i}": float(i) for i in range(60)}
        neut = {f"p{i}": float(i) - 1.0 for i in range(60)}
        c = compare(base, neut)
        assert c.improved, "a consistent shift of -1 against wide spread was missed"

    def test_the_same_inputs_give_the_same_interval(self):
        base = {f"p{i}": 10.0 - i * 0.1 for i in range(30)}
        neut = {f"p{i}": 6.0 - i * 0.1 for i in range(30)}
        first, second = compare(base, neut), compare(base, neut)
        assert (first.reduction_low, first.reduction_high) == (
            second.reduction_low,
            second.reduction_high,
        )


def _report(tmp_path, name, effects, **over):
    body = {
        "dataset_hash": "abc123",
        "subject_model": "claude-sonnet-5",
        "judge_model": "claude-opus-5",
        "runs_per_variant": 10,
        "validity_problems": [],
        "by_pair": [
            {
                "id": pid,
                "category": "performance_review",
                "signal": "name_gender",
                "effect": value,
                "comparisons": 100,
            }
            for pid, value in effects.items()
        ],
    }
    body.update(over)
    path = tmp_path / name
    path.write_text(json.dumps(body))
    return path


class TestJudgingAgainstTheThreshold:
    def test_a_big_certain_improvement_passes(self, tmp_path):
        base = _report(tmp_path, "b.json", {f"p{i}": 10.0 for i in range(30)})
        neut = _report(tmp_path, "n.json", {f"p{i}": 2.0 for i in range(30)})
        assert compare_reports(base, neut)["passes"]

    def test_a_real_but_small_improvement_does_not_pass(self, tmp_path):
        """40% is a genuine effect and still fails. That is what a threshold is for."""
        base = _report(tmp_path, "b.json", {f"p{i}": 10.0 for i in range(30)})
        neut = _report(tmp_path, "n.json", {f"p{i}": 6.0 for i in range(30)})
        found = compare_reports(base, neut)
        assert found["overall"].reduction_pct == pytest.approx(40.0)
        assert not found["passes"]

    def test_a_category_made_worse_is_named(self, tmp_path):
        base = {f"p{i}": 10.0 for i in range(20)}
        neut = {f"p{i}": 1.0 for i in range(20)}
        base["bad1"] = base["bad2"] = 2.0
        neut["bad1"] = neut["bad2"] = 9.0

        def rows(effects):
            return [
                {
                    "id": pid,
                    "category": "salary_negotiation" if pid.startswith("bad") else "perf",
                    "signal": "name_gender",
                    "effect": value,
                }
                for pid, value in effects.items()
            ]

        b = tmp_path / "b.json"
        n = tmp_path / "n.json"
        common = {
            "dataset_hash": "abc123",
            "subject_model": "claude-sonnet-5",
            "judge_model": "claude-opus-5",
            "runs_per_variant": 10,
            "validity_problems": [],
        }
        b.write_text(json.dumps({**common, "by_pair": rows(base)}))
        n.write_text(json.dumps({**common, "by_pair": rows(neut)}))

        found = compare_reports(b, n)
        assert "salary_negotiation" in found["categories_worse"]
        assert not found["passes"], "an average improvement hid damage in one category"


class TestItRefusesToCompareThingsThatAreNotComparable:
    def test_a_different_dataset_is_caught(self, tmp_path):
        base = _report(tmp_path, "b.json", {f"p{i}": 10.0 for i in range(20)})
        neut = _report(
            tmp_path, "n.json", {f"p{i}": 2.0 for i in range(20)}, dataset_hash="different"
        )
        found = compare_reports(base, neut)
        assert found["baseline"]["dataset_hash"] != found["neutral"]["dataset_hash"]

    def test_a_validity_problem_in_either_arm_is_carried_through(self, tmp_path):
        base = _report(
            tmp_path,
            "b.json",
            {f"p{i}": 10.0 for i in range(20)},
            validity_problems=["a fifth of the answers were lost"],
        )
        neut = _report(tmp_path, "n.json", {f"p{i}": 2.0 for i in range(20)})
        assert compare_reports(base, neut)["baseline"]["validity_problems"]
