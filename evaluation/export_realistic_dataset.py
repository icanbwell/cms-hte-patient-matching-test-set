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
(evaluation/cases), DRIFT_PROFILE_PATH (placeholder default profile).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

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


CAVEATS: List[str] = [
    "not filtered for CMS Table 2 rule 29 (BAI-1061)",
    "drift positives not verified against the CMS reference algorithm",
    "drift and household sharing rates are placeholders, not measured",
    "households are mostly unrelated real records placed at one address",
    "mined sibling, name-collision and hard-negative categories are scarce",
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
) -> RealisticDataset:
    sample = stratified_sample(batches, sample_size, donor_n=donor_size, seed=seed)
    housed = assign_households(sample.patients, profile=profile, seed=seed)
    records = build_test_case_records(
        housed.patients,
        donors=sample.donors,
        profile=profile,
        households=housed.households,
        seed=seed,
        frequency_lookup=researched_frequency,
    )
    population = build_population_dataset(
        housed.patients,
        donors=sample.donors,
        profile=profile,
        households=housed.households,
        seed=seed,
    )
    counts: Dict[str, int] = {}
    for patient in housed.patients:
        band = band_of(age_of(patient, AS_OF)) or "unknown"
        counts[band] = counts.get(band, 0) + 1
    manifest: Dict[str, Any] = {
        "kind": "realistic dataset: RELEASE CANDIDATE, not filtered for CMS rule 29",
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
    )
    output_dir = Path(os.environ.get("OUTPUT_DIR", str(CASES_DIR)))
    write_realistic_dataset(result, output_dir)
    print(json.dumps(result.manifest, indent=2))
