"""Run export_test_dataset.py's and export_population_dataset.py's generation
logic across the full, all-9-shard ONC dataset (~1,000,000 records) - the
scale export_test_dataset.py/export_population_dataset.py deliberately don't
attempt by default (see SYNTHETIC_DATA_SETUP.md's "Memory & scale" section).

This does NOT flatten all 9 shards into one in-memory list the way
`load_onc_patients(sorted(onc_dir.glob("*.csv")))` would - that's exactly the
pattern that crashed a Databricks cluster before. Instead it follows the
docs' "prefer one shard at a time, not all 9 concatenated" guidance literally:
load one shard (~110K rows), generate that shard's cases, write them, discard
the shard, move to the next. Peak memory stays bounded to one shard's worth of
patients plus that shard's generated cases, never the full dataset.

No SAMPLE_SIZE/POOL_SIZE-driven downsampling of the *input* is applied here
(every patient in every shard is used) - POOL_SIZE still bounds each
population query's candidate pool, per population_cases.py's own contract.

One category is disabled here despite that "no downsampling" default:
hard_negatives.mine_name_collision_negatives() is the one generator in this
pipeline that's O(n^2) rather than O(n)/O(n)-blocked (its own docstring
measures ~142s at n=16000; extrapolated to a full ~110K-record shard that's
roughly two hours per shard, ~18 hours for all 9 - confirmed by actually
running it). Every other true-match/hard-negative/special-population
generator runs unmodified against the full shard. population_cases.py (the
population-query tier) never calls this function at all, so it's unaffected.
The sampled tier (export_test_dataset.py, small-n by design) still generates
this category as before.

Writes to full_labeled_pairs.jsonl / full_population_candidates.jsonl /
full_population_queries.jsonl by default - deliberately NOT the same
filenames as export_test_dataset.py/export_population_dataset.py's
sample_labeled_pairs.jsonl / population_candidates.jsonl /
population_queries.jsonl. Those are committed, consumer-facing files whose
documented semantics (evaluation/cases/README.md) are a curated,
rare-case-oversampled *sample*, not full-dataset scale; this script must not
silently replace them with an unbounded, ~9x-larger full-dataset run. Pass
OUTPUT_PATH/CANDIDATES_PATH/QUERIES_PATH explicitly if you deliberately want
to replace the sample files.

Run standalone from the repo root:

    PYTHONPATH=. uv run python evaluation/export_full_onc_dataset.py

or via `make generate-full-dataset`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from export_test_dataset import build_test_case_records
from onc_loader import load_onc_patients
from population_cases import DEFAULT_POOL_SIZE, build_population_dataset
from prevalence_estimates import researched_frequency

DEFAULT_OUTPUT_PATH = Path(__file__).parent / "cases" / "full_labeled_pairs.jsonl"
DEFAULT_CANDIDATES_PATH = (
    Path(__file__).parent / "cases" / "full_population_candidates.jsonl"
)
DEFAULT_QUERIES_PATH = Path(__file__).parent / "cases" / "full_population_queries.jsonl"


def _all_shards() -> list[Path]:
    onc_dir = Path(__file__).parent / "fixtures" / "onc"
    return sorted(onc_dir.glob("*.csv"))


def export_full_test_dataset(output_path: Path) -> None:
    """Write sample_labeled_pairs.jsonl-format cases for every shard, one
    shard at a time, appending as it goes rather than accumulating all
    shards' records in memory before writing."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    total_true = 0
    with output_path.open("w") as f:
        for shard in _all_shards():
            patients = load_onc_patients([shard])
            records = build_test_case_records(
                patients,
                frequency_lookup=researched_frequency,
                include_name_collision_negatives=False,
            )
            for record in records:
                f.write(
                    json.dumps(
                        {
                            "case_id": record.case_id,
                            "source": record.source,
                            "target": record.target,
                            "expected_match": record.expected_match,
                            "rationale": record.rationale,
                            "frequency": record.frequency,
                        }
                    )
                    + "\n"
                )
            total += len(records)
            total_true += sum(r.expected_match for r in records)
            print(f"{shard.name}: {len(patients)} patients -> {len(records)} cases")
    print(
        f"Wrote {total} test cases ({total_true} expected_match=true, "
        f"{total - total_true} expected_match=false) from all 9 ONC shards to "
        f"{output_path}"
    )


def export_full_population_dataset(
    candidates_path: Path, queries_path: Path, *, pool_size: int
) -> None:
    """Write population_candidates.jsonl/population_queries.jsonl for every
    shard, one shard at a time, appending as it goes. Candidate/query ids are
    safe to append without cross-shard dedup: onc_loader.py's module
    docstring notes every EnterpriseID in this vendored dataset is unique
    dataset-wide, not just per shard, and institutional candidate ids are
    namespaced off of those same globally-unique ids."""
    candidates_path.parent.mkdir(parents=True, exist_ok=True)
    queries_path.parent.mkdir(parents=True, exist_ok=True)
    total_queries = 0
    total_nonempty = 0
    total_candidates = 0
    with candidates_path.open("w") as cf, queries_path.open("w") as qf:
        for shard in _all_shards():
            patients = load_onc_patients([shard])
            dataset = build_population_dataset(patients, pool_size=pool_size)
            for candidate_id, patient in sorted(dataset.candidates.items()):
                cf.write(json.dumps({"id": candidate_id, "patient": patient}) + "\n")
            for case in dataset.cases:
                qf.write(
                    json.dumps(
                        {
                            "query_id": case.query_id,
                            "query": case.query_patient,
                            "candidate_ids": case.candidate_ids,
                            "expected_match_ids": case.expected_match_ids,
                            "rationale": case.rationale,
                        }
                    )
                    + "\n"
                )
            total_queries += len(dataset.cases)
            total_nonempty += sum(1 for c in dataset.cases if c.expected_match_ids)
            total_candidates += len(dataset.candidates)
            print(
                f"{shard.name}: {len(patients)} patients -> "
                f"{len(dataset.cases)} queries, {len(dataset.candidates)} candidates"
            )
    print(
        f"Wrote {total_queries} population queries ({total_nonempty} with a "
        f"non-empty expected match set) and {total_candidates} candidates "
        f"(POOL_SIZE={pool_size}) from all 9 ONC shards to {candidates_path} "
        f"and {queries_path}"
    )


if __name__ == "__main__":
    pool_size = int(os.environ.get("POOL_SIZE", DEFAULT_POOL_SIZE))

    test_output_path = Path(os.environ.get("OUTPUT_PATH", str(DEFAULT_OUTPUT_PATH)))
    export_full_test_dataset(test_output_path)

    candidates_path = Path(
        os.environ.get("CANDIDATES_PATH", str(DEFAULT_CANDIDATES_PATH))
    )
    queries_path = Path(os.environ.get("QUERIES_PATH", str(DEFAULT_QUERIES_PATH)))
    export_full_population_dataset(candidates_path, queries_path, pool_size=pool_size)
