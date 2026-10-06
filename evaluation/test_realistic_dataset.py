"""End-to-end test of the age/household-realistic pipeline (session 15, Workstream C).

Generates a small realistic dataset from ONE ONC shard (fast) and gates it with
release_thresholds_realistic.json, so CI checks the realism targets without
committing the generated files.
"""

from __future__ import annotations

import json

import pytest
from audit import (
    age_band_max_error,
    build_report,
    read_jsonl,
    unique_source_patients,
)
from drift_profile import DriftProfile
from export_inputs import iter_shard_batches
from export_realistic_dataset import generate_realistic, write_realistic_dataset
from population_targets import age_band_targets
from release_gate import (
    REALISTIC_THRESHOLDS_PATH,
    check,
    failures,
    load_thresholds,
    run,
)

SAMPLE = 300


@pytest.fixture(scope="module")
def realistic(tmp_path_factory):
    dataset = generate_realistic(
        iter_shard_batches(limit=1),
        sample_size=SAMPLE,
        donor_size=SAMPLE,
        seed=0,
        profile=DriftProfile(),
    )
    out = tmp_path_factory.mktemp("realistic")
    write_realistic_dataset(dataset, out)
    return dataset, out


def test_writes_the_four_files(realistic):
    _, out = realistic
    assert sorted(p.name for p in out.iterdir()) == [
        "realistic_labeled_pairs.jsonl",
        "realistic_manifest.json",
        "realistic_population_candidates.jsonl",
        "realistic_population_queries.jsonl",
    ]


def test_age_bands_match_the_targets_within_rounding(realistic):
    dataset, out = realistic
    rows = read_jsonl(out / "realistic_labeled_pairs.jsonl")
    assert age_band_max_error(unique_source_patients(rows)) < 0.01
    counts = dataset.manifest["sample_band_counts"]
    assert sum(counts.values()) == SAMPLE
    assert counts["85+"] == round(SAMPLE * age_band_targets()["85+"])


def test_households_reach_roughly_the_target_size(realistic):
    dataset, _ = realistic
    assert dataset.manifest["households"]["mean_size"] == pytest.approx(2.5, abs=0.4)
    assert dataset.manifest["households"]["n_minors"] > 0


def test_the_realistic_thresholds_pass_on_the_generated_files(realistic):
    _, out = realistic
    report = build_report(
        out / "realistic_labeled_pairs.jsonl",
        out / "realistic_population_queries.jsonl",
        out / "realistic_population_candidates.jsonl",
    )
    results = check(report, load_thresholds(REALISTIC_THRESHOLDS_PATH))
    assert failures(results) == [], [(r.name, r.value) for r in failures(results)]


def test_household_members_appear_as_non_matches_in_both_tiers(realistic):
    _, out = realistic
    pairs = read_jsonl(out / "realistic_labeled_pairs.jsonl")
    household = [
        r for r in pairs if r["rationale"].startswith("household_member_negative")
    ]
    assert household and all(r["expected_match"] is False for r in household)
    queries = read_jsonl(out / "realistic_population_queries.jsonl")
    assert any("household_member_negative" in q["rationale"] for q in queries)


def test_manifest_records_how_the_dataset_was_built(realistic):
    _, out = realistic
    manifest = json.loads((out / "realistic_manifest.json").read_text())
    assert "RELEASE CANDIDATE" in manifest["kind"]
    assert manifest["as_of"] == "2017-01-01"
    assert manifest["age_band_targets"] == age_band_targets()
    assert "PLACEHOLDER" in manifest["profile_source"]


def test_an_unknown_dataset_name_is_rejected():
    with pytest.raises(ValueError, match="committed"):
        run("nope")
