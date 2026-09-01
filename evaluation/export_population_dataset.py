"""Materialize population_cases.py's PopulationDataset as the population-query
tier's portable manifest - session_12.md's Task 3.

Two files, not one, because a candidate frequently appears in more than one
query's pool (a real ONC record used as a random distractor for several
different queries, or a mined hard-negative candidate shared across queries)
- repeating its full FHIR JSON body once per appearance would bloat the file
for no benefit, per the current cross-org Doc's own framing of this tier as
"mostly splitting an existing file rather than generating one from scratch":

- `population_candidates.jsonl` - the flat candidate pool, one row per unique
  candidate id: `{"id": ..., "patient": {FHIR Patient JSON}}`.
- `population_queries.jsonl` - one row per query:
  `{"query_id": ..., "query": {FHIR Patient JSON}, "candidate_ids": [...],
  "expected_match_ids": [...], "rationale": ...}`. Every id in a query's
  `candidate_ids`/`expected_match_ids` resolves against a row in
  `population_candidates.jsonl`.

Run standalone from the repo root:

    PYTHONPATH=. python evaluation/export_population_dataset.py

Same one-shard, SAMPLE_SIZE-limited default and memory/scale caution as
export_test_dataset.py / labeled_pairs.py - see SYNTHETIC_DATA_SETUP.md's
"Memory & scale" section before raising SAMPLE_SIZE or POOL_SIZE.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from labeled_pairs import DEFAULT_SAMPLE_SIZE
from onc_loader import load_onc_patients
from population_cases import (
    DEFAULT_POOL_SIZE,
    PopulationDataset,
    build_population_dataset,
)

DEFAULT_CANDIDATES_PATH = (
    Path(__file__).parent / "cases" / "population_candidates.jsonl"
)
DEFAULT_QUERIES_PATH = Path(__file__).parent / "cases" / "population_queries.jsonl"


def write_population_dataset(
    dataset: PopulationDataset, candidates_path: Path, queries_path: Path
) -> None:
    """Write both manifest files, creating parent directories if needed."""
    candidates_path.parent.mkdir(parents=True, exist_ok=True)
    queries_path.parent.mkdir(parents=True, exist_ok=True)

    with candidates_path.open("w") as f:
        for candidate_id, patient in sorted(dataset.candidates.items()):
            f.write(json.dumps({"id": candidate_id, "patient": patient}) + "\n")

    with queries_path.open("w") as f:
        for case in dataset.cases:
            f.write(
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


if __name__ == "__main__":
    sample_size = int(os.environ.get("SAMPLE_SIZE", DEFAULT_SAMPLE_SIZE))
    pool_size = int(os.environ.get("POOL_SIZE", DEFAULT_POOL_SIZE))
    onc_dir = Path(__file__).parent / "fixtures" / "onc"
    # One shard only, not sorted(onc_dir.glob("*.csv")) (all 9) - see
    # population_cases.py's and SYNTHETIC_DATA_SETUP.md's "Memory & scale".
    shard = sorted(onc_dir.glob("*.csv"))[0]
    patients = load_onc_patients([shard])[:sample_size]
    dataset = build_population_dataset(patients, pool_size=pool_size)

    candidates_path = Path(
        os.environ.get("CANDIDATES_PATH", str(DEFAULT_CANDIDATES_PATH))
    )
    queries_path = Path(os.environ.get("QUERIES_PATH", str(DEFAULT_QUERIES_PATH)))
    write_population_dataset(dataset, candidates_path, queries_path)

    n_nonempty = sum(1 for c in dataset.cases if c.expected_match_ids)
    print(
        f"Wrote {len(dataset.cases)} population queries ({n_nonempty} with a non-empty "
        f"expected match set) and {len(dataset.candidates)} candidates from {len(patients)} "
        f"ONC patients (one shard, sampled to SAMPLE_SIZE={sample_size}, POOL_SIZE={pool_size}) "
        f"to {candidates_path} and {queries_path}"
    )
