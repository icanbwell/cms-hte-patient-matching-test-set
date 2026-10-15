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

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Sequence

from dob_shift import shift_birth_date
from drift_profile import DriftProfile
from export_inputs import DEFAULT_DONOR_SIZE, iter_shard_batches, load_profile
from export_population_dataset import write_population_dataset
from export_test_dataset import (
    LabeledCaseRecord,
    build_test_case_records,
    write_jsonl,
)
from family_adults import add_family_adults
from household_assignment import assign_households
from labeled_pairs import DEFAULT_SAMPLE_SIZE
from near_miss import (
    DEFAULT_PER_KIND_CAP,
    DEFAULT_POOL_PER_KIND_CAP,
    find_near_misses,
    limit_per_kind,
)
from negative_balance import rebalance_negatives
from population_cases import PopulationDataset, build_population_dataset
from population_sampling import age_of, band_of, stratified_sample
from population_targets import (
    AGE_BAND_TARGETS,
    AGE_BANDS,
    AS_OF,
    DOB_SHIFT_YEARS,
    MEAN_HOUSEHOLD_SIZE,
    ONC_AS_OF,
    SINGLE_PERSON_HOUSEHOLD_SHARE,
    age_band_targets,
)
from prevalence_estimates import researched_frequency

Patient = Dict[str, Any]
CASES_DIR = Path(__file__).parent / "cases"
# Bumped when emitted resource content changes (session 16: FHIR-conformant loader).
DATASET_VERSION = "2"
TARGET_NEGATIVE_SHARE = 0.5

# Modules that decide what the committed realistic files contain. The audit,
# release gate, baselines and tests only read those files, so editing them does
# not make the files stale.
_NOT_GENERATORS = frozenset(
    {
        "audit",
        "release_gate",
        "rule_eval",
        "naive_baselines",
    }
)


def generator_fingerprint() -> str:
    """Hash of every generator module's source. The manifest records it and a
    test compares it, so a code change that is not followed by a regeneration
    fails CI instead of leaving stale committed data that still passes the gate."""
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        if path.stem.startswith("test_") or path.stem in _NOT_GENERATORS:
            continue
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


CAVEATS: List[str] = [
    "drift positives not verified against the CMS reference algorithm",
    "drift and household sharing rates are placeholders, not measured",
    "households are mostly unrelated ONC-derived records placed at one address; 70% of minors live with a same-surname adult only because family_adults.py adds ONC-derived adults to the sample to reach a placeholder target (a surname is a proxy for a parent; see family_adults and households in this manifest)",
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
    per_kind_cap: int = DEFAULT_POOL_PER_KIND_CAP,
    pairwise_per_kind_cap: int = DEFAULT_PER_KIND_CAP,
) -> RealisticDataset:
    if per_kind_cap < 1 or pairwise_per_kind_cap < 1:
        raise ValueError(
            "per_kind_cap and pairwise_per_kind_cap must be at least 1, got "
            f"{per_kind_cap} and {pairwise_per_kind_cap}"
        )
    # Sampling runs on ONC's own vintage; every record the release uses (sample,
    # donors and streamed decoys alike, so birth-date keys still line up) is then
    # moved forward so the same people have the same ages as of AS_OF.
    sample = stratified_sample(batches, sample_size, donor_n=donor_size, seed=seed)
    family = None
    sampled = sample.patients
    if decoy_batches is not None and profile.rate("minors_with_same_surname_adult") > 0:
        family = add_family_adults(
            sample.patients,
            decoy_batches,
            target_share=profile.rate("minors_with_same_surname_adult"),
            exclude_ids={d["id"] for d in sample.donors},
            seed=seed,
        )
        sampled = family.patients
    sample_patients = [shift_birth_date(p, DOB_SHIFT_YEARS) for p in sampled]
    donors = [shift_birth_date(d, DOB_SHIFT_YEARS) for d in sample.donors]
    housed = assign_households(sample_patients, profile=profile, seed=seed)
    near_result = None
    if decoy_batches is not None:
        near_result = find_near_misses(
            housed.patients,
            (
                [shift_birth_date(p, DOB_SHIFT_YEARS) for p in batch]
                for batch in decoy_batches()
            ),
            exclude_ids={p["id"] for p in sample_patients} | {d["id"] for d in donors},
            per_kind_cap=per_kind_cap,
            seed=seed,
            originals={p["id"]: p for p in sample_patients},
        )
    near_misses = near_result.near_misses if near_result else []
    records = build_test_case_records(
        housed.patients,
        donors=donors,
        profile=profile,
        households=housed.households,
        near_misses=limit_per_kind(near_misses, pairwise_per_kind_cap, seed=seed),
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
        donors=donors,
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
        "generator_fingerprint": generator_fingerprint(),
        "seed": seed,
        "sample_size": sample_size,
        "donor_size": donor_size,
        "as_of": AS_OF.isoformat(),
        "onc_as_of": ONC_AS_OF.isoformat(),
        "dob_shift_years": DOB_SHIFT_YEARS,
        "caveats": list(CAVEATS),
        "age_band_targets": age_band_targets(),
        "target_sources": _target_sources(),
        "sample_band_counts": counts,
        "onc_band_supply": sample.supply,
        "households": asdict(housed.report),
        "family_adults": (
            {
                "target_share": profile.rate("minors_with_same_surname_adult"),
                "n_added": family.n_added,
                "n_minors": family.n_minors,
                "minors_covered_before": family.n_covered_before,
                "minors_covered_after": family.n_covered_after,
            }
            if family is not None
            else None
        ),
        "profile_source": profile.source,
        "profile_rates": dict(profile.rates),
        "near_miss": {
            "per_kind_cap": per_kind_cap,
            "pairwise_per_kind_cap": pairwise_per_kind_cap,
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
        target_negative_share=TARGET_NEGATIVE_SHARE,
        per_kind_cap=int(os.environ.get("NEAR_MISS_CAP", DEFAULT_POOL_PER_KIND_CAP)),
        pairwise_per_kind_cap=int(
            os.environ.get("PAIRWISE_NEAR_MISS_CAP", DEFAULT_PER_KIND_CAP)
        ),
    )
    output_dir = Path(os.environ.get("OUTPUT_DIR", str(CASES_DIR)))
    write_realistic_dataset(result, output_dir)
    print(json.dumps(result.manifest, indent=2))
