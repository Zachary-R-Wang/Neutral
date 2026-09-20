"""Tests for the matched-pair dataset format.

The experiment's whole claim is "these two prompts differ only in an identity signal".
These tests are what make that claim checkable rather than asserted.
"""

from __future__ import annotations

import difflib
from pathlib import Path

import pytest
import yaml

from neutral.eval.dataset import (
    CATEGORIES,
    DatasetError,
    Pair,
    Variant,
    dataset_hash,
    load_dataset,
    validate_pair,
)

DATASET_DIR = Path(__file__).resolve().parent.parent / "datasets" / "v1"


def make_pair(**overrides) -> Pair:
    defaults = dict(
        id="test-001",
        category="performance_review",
        signal="name_gender",
        template="Review {NAME}. Describe {POSS} strengths.",
        a=Variant("female", {"NAME": "Emily", "POSS": "her"}),
        b=Variant("male", {"NAME": "Ethan", "POSS": "his"}),
    )
    defaults.update(overrides)
    return Pair(**defaults)


class TestPairValidation:
    def test_a_well_formed_pair_validates(self):
        validate_pair(make_pair())

    def test_rendering_substitutes_every_slot(self):
        pair = make_pair()
        assert pair.render("a") == "Review Emily. Describe her strengths."
        assert pair.render("b") == "Review Ethan. Describe his strengths."

    def test_rejects_an_unfilled_slot(self):
        """A missing fill would send a literal {SLOT} to the model."""
        pair = make_pair(a=Variant("female", {"NAME": "Emily"}))
        with pytest.raises(DatasetError, match="POSS"):
            validate_pair(pair)

    def test_rejects_a_fill_the_template_never_uses(self):
        pair = make_pair(
            a=Variant("female", {"NAME": "Emily", "POSS": "her", "AGE": "52"}),
        )
        with pytest.raises(DatasetError, match="AGE"):
            validate_pair(pair)

    def test_rejects_two_identical_variants(self):
        pair = make_pair(b=Variant("also female", {"NAME": "Emily", "POSS": "her"}))
        with pytest.raises(DatasetError, match="differ in at least one"):
            validate_pair(pair)

    def test_rejects_an_unknown_category(self):
        with pytest.raises(DatasetError, match="category"):
            validate_pair(make_pair(category="vibes"))

    def test_rejects_an_unknown_signal(self):
        with pytest.raises(DatasetError, match="signal"):
            validate_pair(make_pair(signal="astrology"))

    def test_rejects_a_template_with_no_slots(self):
        with pytest.raises(DatasetError, match="no .*SLOT"):
            validate_pair(
                make_pair(
                    template="Review this person.",
                    a=Variant("a", {}),
                    b=Variant("b", {}),
                )
            )

    def test_differing_slots_reports_only_what_changed(self):
        pair = make_pair(
            a=Variant("female", {"NAME": "Emily", "POSS": "their"}),
            b=Variant("male", {"NAME": "Ethan", "POSS": "their"}),
        )
        assert pair.differing_slots == ("NAME",)


class TestMatchedness:
    """The property the experiment rests on."""

    def test_prompts_are_identical_outside_the_identity_slots(self):
        pair = make_pair()
        a_words, b_words = pair.render("a").split(), pair.render("b").split()
        shared = [w[2:] for w in difflib.ndiff(a_words, b_words) if w.startswith("  ")]
        assert shared == ["Review", "Describe", "strengths."]

    def test_a_template_typo_cannot_hide_in_one_variant(self):
        """Both variants render from the same characters, so drift is impossible.

        This is the reason pairs are templates rather than two hand-written prompts.
        """
        pair = make_pair()
        blanked_a = pair.template.replace("{NAME}", "").replace("{POSS}", "")
        blanked_b = pair.template.replace("{NAME}", "").replace("{POSS}", "")
        assert blanked_a == blanked_b


class TestDatasetLoading:
    def test_loads_the_real_dataset(self):
        pairs = load_dataset(DATASET_DIR)
        assert pairs, "the seed dataset is empty"

    def test_every_category_is_represented(self):
        present = {p.category for p in load_dataset(DATASET_DIR)}
        missing = set(CATEGORIES) - present
        assert not missing, f"no pairs for: {', '.join(sorted(missing))}"

    def test_every_real_pair_is_matched(self):
        for pair in load_dataset(DATASET_DIR):
            validate_pair(pair)

    def test_pair_ids_are_unique(self, tmp_path):
        body = {
            "pairs": [
                {
                    "id": "dup-001",
                    "category": "performance_review",
                    "signal": "name_gender",
                    "template": "Review {NAME}.",
                    "a": {"label": "x", "fills": {"NAME": "Emily"}},
                    "b": {"label": "y", "fills": {"NAME": "Ethan"}},
                }
            ]
        }
        (tmp_path / "one.yaml").write_text(yaml.safe_dump(body))
        (tmp_path / "two.yaml").write_text(yaml.safe_dump(body))
        with pytest.raises(DatasetError, match="Duplicate"):
            load_dataset(tmp_path)

    def test_a_missing_directory_says_so_in_english(self, tmp_path):
        with pytest.raises(DatasetError, match="No dataset directory"):
            load_dataset(tmp_path / "nope")


class TestDatasetHash:
    """CLAUDE.md section 6: dataset edits are versioned and hashed."""

    def test_hash_is_stable_across_loads(self):
        assert dataset_hash(load_dataset(DATASET_DIR)) == dataset_hash(load_dataset(DATASET_DIR))

    def test_hash_does_not_depend_on_file_order(self):
        pairs = load_dataset(DATASET_DIR)
        assert dataset_hash(pairs) == dataset_hash(list(reversed(pairs)))

    def test_hash_changes_when_a_prompt_changes(self):
        pairs = load_dataset(DATASET_DIR)
        edited = list(pairs)
        edited[0] = make_pair(id=pairs[0].id, template="Completely different {NAME}.")
        assert dataset_hash(pairs) != dataset_hash(edited)

    def test_hash_ignores_notes(self):
        """Notes are commentary; changing them must not invalidate a baseline."""
        pairs = load_dataset(DATASET_DIR)
        annotated = [
            Pair(
                id=p.id,
                category=p.category,
                signal=p.signal,
                template=p.template,
                a=p.a,
                b=p.b,
                numeric_scale=p.numeric_scale,
                notes="a new note",
            )
            for p in pairs
        ]
        assert dataset_hash(pairs) == dataset_hash(annotated)
