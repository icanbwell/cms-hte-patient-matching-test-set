"""Generate the age- and household-realistic dataset (session 15, Workstream C).

Pipeline: stratified sample across ALL ONC shards, one shard at a time
(population_sampling.py) -> household assignment (household_assignment.py) ->
the existing generators (registry scenarios, hard negatives, population pools).

Writes, next to the committed files but under different names (the committed
samples are curated snapshots and are never overwritten):

    realistic_labeled_pairs.jsonl
    realistic_population_candidates.jsonl
    realistic_population_queries.jsonl
    realistic_manifest.json

The generators apply the case exclusions in case_exclusions.py (rule 29
removed), so no hand filter is needed. The new drift positives are not yet
verified against the CMS reference algorithm, so these are a release CANDIDATE.

Run from the repo root (reads all 9 shards, about a minute):

    PYTHONPATH=. uv run python evaluation/export_realistic_dataset.py

A custom DRIFT_PROFILE_PATH JSON REPLACES the whole rates dict, so a profile that
omits household_shared_phone, household_shared_email or minor_ssn_absent
silently gets 0.0 for them.

Environment: SAMPLE_SIZE (2000), DONOR_SIZE (2000), SEED (0), OUTPUT_DIR
(evaluation/cases), DRIFT_PROFILE_PATH (placeholder default profile),
NEAR_MISS_CAP (3).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Sequence

from drift_profile import DriftProfile
from export_inputs import DEFAULT_DONOR_SIZE, iter_shard_batches, load_profile
from export_population_dataset import write_population_dataset
from export_test_dataset import (
    LabeledCaseRecord,
    build_test_case_records,
    write_jsonl,
)
from household_assignment import assign_households
from labeled_pairs import DEFAULT_SAMPLE_SIZE
from near_miss import DEFAULT_PER_KIND_CAP, find_near_misses
from negative_balance import rebalance_negatives
from population_cases import PopulationDataset, build_population_dataset
from population_sampling import age_of, band_of, stratified_sample
from population_targets import (
    AGE_BAND_TARGETS,
    AGE_BANDS,
    AS_OF,
    MEAN_HOUSEHOLD_SIZE,
    SINGLE_PERSON_HOUSEHOLD_SHARE,
    age_band_targets,
)
from prevalence_estimates import researched_frequency

Patient = Dict[str, Any]
CASES_DIR = Path(__file__).parent / "cases"
# Bumped when emitted resource content changes (session 16: FHIR-conformant loader).
DATASET_VERSION = "2"


CAVEATS: List[str] = [
    "drift positives not verified against the CMS reference algorithm",
    "drift and household sharing rates are placeholders, not measured",
    "households are mostly unrelated real records placed at one address",
]


def _target_sources() -> Dict[str, str]:
    sources = {name: AGE_BAND_TARGETS[name].source for name, _, _ in AGE_BANDS}
    sources["single_person_household_share"] = SINGLE_PERSON_HOUSEHOLD_SHARE.source
    sources["mean_household_size"] = MEAN_HOUSEHOLD_SIZE.source
    return sources


@dataclass(frozen=True)
class RealisticDataset:
    records: List[LabeledCaseRecord]
    population: PopulationDataset
    manifest: Dict[str, Any]


def generate_realistic(
    batches: Iterable[Sequence[Patient]],
    *,
    sample_size: int,
    donor_size: int,
    seed: int,
    profile: DriftProfile,
    decoy_batches: Callable[[], Iterable[Sequence[Patient]]] | None = None,
    target_negative_share: float | None = None,
    per_kind_cap: int = DEFAULT_PER_KIND_CAP,
) -> RealisticDataset:
    sample = stratified_sample(batches, sample_size, donor_n=donor_size, seed=seed)
    housed = assign_households(sample.patients, profile=profile, seed=seed)
    near_result = None
    if decoy_batches is not None:
        near_result = find_near_misses(
            housed.patients,
            decoy_batches(),
            exclude_ids={p["id"] for p in sample.patients}
            | {d["id"] for d in sample.donors},
            per_kind_cap=per_kind_cap,
            seed=seed,
        )
    near_misses = near_result.near_misses if near_result else []
    records = build_test_case_records(
        housed.patients,
        donors=sample.donors,
        profile=profile,
        households=housed.households,
        near_misses=near_misses,
        seed=seed,
        frequency_lookup=researched_frequency,
    )
    n_before = len(records)
    if target_negative_share is not None:
        records = rebalance_negatives(
            records, target_share=target_negative_share, seed=seed
        )
    population = build_population_dataset(
        housed.patients,
        donors=sample.donors,
        profile=profile,
        households=housed.households,
        near_misses=near_misses,
        seed=seed,
    )
    n_negatives = sum(1 for r in records if not r.expected_match)
    counts: Dict[str, int] = {}
    for patient in housed.patients:
        band = band_of(age_of(patient, AS_OF)) or "unknown"
        counts[band] = counts.get(band, 0) + 1
    manifest: Dict[str, Any] = {
        "kind": "realistic dataset: RELEASE CANDIDATE",
        "dataset_version": DATASET_VERSION,
        "seed": seed,
        "sample_size": sample_size,
        "donor_size": donor_size,
        "as_of": AS_OF.isoformat(),
        "caveats": list(CAVEATS),
        "age_band_targets": age_band_targets(),
        "target_sources": _target_sources(),
        "sample_band_counts": counts,
        "onc_band_supply": sample.supply,
        "households": asdict(housed.report),
        "profile_source": profile.source,
        "profile_rates": dict(profile.rates),
        "near_miss": {
            "per_kind_cap": per_kind_cap,
            "yield_by_kind": near_result.yield_by_kind if near_result else {},
        },
        "negative_share": n_negatives / len(records) if records else 0.0,
        "n_positives_dropped": n_before - len(records),
        "n_labeled_cases": len(records),
        "n_population_queries": len(population.cases),
    }
    return RealisticDataset(records=records, population=population, manifest=manifest)


def write_realistic_dataset(dataset: RealisticDataset, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(dataset.records, output_dir / "realistic_labeled_pairs.jsonl")
    write_population_dataset(
        dataset.population,
        output_dir / "realistic_population_candidates.jsonl",
        output_dir / "realistic_population_queries.jsonl",
    )
    (output_dir / "realistic_manifest.json").write_text(
        json.dumps(dataset.manifest, indent=2) + "\n"
    )


if __name__ == "__main__":
    sample_size = int(os.environ.get("SAMPLE_SIZE", DEFAULT_SAMPLE_SIZE))
    donor_size = int(os.environ.get("DONOR_SIZE", DEFAULT_DONOR_SIZE))
    result = generate_realistic(
        iter_shard_batches(),
        sample_size=sample_size,
        donor_size=donor_size,
        seed=int(os.environ.get("SEED", "0")),
        profile=load_profile(),
        decoy_batches=iter_shard_batches,
        target_negative_share=0.5,
        per_kind_cap=int(os.environ.get("NEAR_MISS_CAP", DEFAULT_PER_KIND_CAP)),
    )
    output_dir = Path(os.environ.get("OUTPUT_DIR", str(CASES_DIR)))
    write_realistic_dataset(result, output_dir)
    print(json.dumps(result.manifest, indent=2))
