"""Assemble a labeled CMS test-dataset sample - (Outside Record, Internal
Record, IsMatch) - from the ONC dataset.

This is session_9's concrete answer to session_8.md's 2026-08-13 open question
("the test-data simulation methodology itself is still open"): true-match rows
come from mutations.py's single-edit fuzzy variants of a real record; true-
non-match rows come from hard_negatives.py's mined real-record pairs - not
random cross-pairs and not mutations asserted to be non-matches (see
hard_negatives.py's module docstring for why that would only test an
algorithm's own tolerance, not reality).

Session 10 extends this module with two further categories, both additive
(default-on, appended alongside session 9's existing pairs rather than
replacing them): normalization-edge-case true-matches
(normalization_edge_cases.py - diacritics, punctuation/whitespace) and
special-population true-non-matches (special_populations.py - mined
multi-generational-household pairs and constructed institutional pairs).

Run standalone from the repo root:

    PYTHONPATH=. python evaluation/labeled_pairs.py

SCOPE, per session 13: this module no longer normalizes patients (dropped the
`patient_matching.normalization.NormalizationManager` dependency - see
session_13.md) or wraps output for any matching engine to consume - this repo
only produces portable test data now, per Design Principle 1's
algorithm-agnostic stance. `generate_raw_pairs()`'s output carries whatever
case/punctuation `onc_loader.load_onc_patients()` read from the raw ONC CSVs;
consumers apply their own normalization convention before matching.

MEMORY & SCALE - read before raising SAMPLE_SIZE or passing more than one ONC
shard. `onc_loader.load_onc_patients()` reads its input CSV(s) into a single
Python list of nested dicts with no streaming. Materializing all ~1,000,000
ONC records this way (all 9 shards) - and then running mutation transforms
across all of them at once - is exactly the failure pattern that has
previously crashed a Databricks cluster running this dataset (per an internal
report, 2026-08-14). This script defaults to one shard, sampled down further,
for exactly that reason. See SYNTHETIC_DATA_SETUP.md's "Memory & scale"
section before scaling this up.
"""

from __future__ import annotations

import os
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping

from hard_negatives import mine_shared_address_hard_negatives
from mutations import generate_fuzzy_variant
from normalization_edge_cases import diacritic_variant, punctuation_variant
from onc_loader import load_onc_patients
from special_populations import (
    INSTITUTION_TYPES,
    construct_institutional_negatives,
    mine_shared_surname_household_negatives,
)

Patient = Dict[str, Any]

# Keeps a standalone run's memory footprint small by default: one shard
# (~110K rows, not all 9 / ~1M), sampled further down to this count. Override
# via the SAMPLE_SIZE env var only after reading SYNTHETIC_DATA_SETUP.md's
# "Memory & scale" section - this default exists because of a prior real
# cluster crash running this dataset at full scale, not as an arbitrary limit.
DEFAULT_SAMPLE_SIZE = 2000


@dataclass(frozen=True)
class RawPair:
    """One generated (query, candidate) pair - the shared representation
    export_test_dataset.py (raw FHIR JSON, for a portable test-case manifest)
    and population_cases.py's pool assembly are built from, so the mutation/
    mining/construction logic in mutations.py/hard_negatives.py/
    normalization_edge_cases.py/special_populations.py is written exactly
    once."""

    pair_id: str
    query_patient: Patient
    candidate_patient: Patient
    is_true_match: bool
    strata: Mapping[str, Any]


def generate_raw_pairs(
    patients: List[Patient],
    *,
    n_fuzzy_variants_per_patient: int = 1,
    include_normalization_edge_cases: bool = True,
    include_special_populations: bool = True,
    institutional_group_size: int = 3,
    seed: int = 0,
) -> Iterator[RawPair]:
    """Yield RawPairs from ONC patients: fuzzy-variant true-matches,
    mined-hard-negative true-non-matches (session 9), plus (session 10)
    normalization-edge-case true-matches and special-population
    true-non-matches (mined multi-generational-household pairs and
    constructed institutional pairs).
    """
    rng = random.Random(seed)

    for p in patients:
        for _ in range(n_fuzzy_variants_per_patient):
            variant, mutation_type = generate_fuzzy_variant(p, rng=rng)
            yield RawPair(
                pair_id=f"{p['id']}::{mutation_type}",
                query_patient=p,
                candidate_patient=variant,
                is_true_match=True,
                strata={"pair_type": "fuzzy_variant", "mutation": mutation_type},
            )
        if include_normalization_edge_cases:
            diacritic = diacritic_variant(p, rng=rng)
            yield RawPair(
                pair_id=f"{p['id']}::diacritic",
                query_patient=p,
                candidate_patient=diacritic,
                is_true_match=True,
                strata={"pair_type": "normalization_edge_case", "case": "diacritic"},
            )
            punctuated = punctuation_variant(p, rng=rng)
            yield RawPair(
                pair_id=f"{p['id']}::punctuation",
                query_patient=p,
                candidate_patient=punctuated,
                is_true_match=True,
                strata={"pair_type": "normalization_edge_case", "case": "punctuation"},
            )

    for candidate in mine_shared_address_hard_negatives(patients):
        yield RawPair(
            pair_id=f"{candidate.query['id']}::{candidate.candidate['id']}",
            query_patient=candidate.query,
            candidate_patient=candidate.candidate,
            is_true_match=False,
            strata={"pair_type": "hard_negative", **candidate.shared_fields},
        )

    if not include_special_populations:
        return

    for household_candidate in mine_shared_surname_household_negatives(patients):
        yield RawPair(
            pair_id=(
                f"{household_candidate.query['id']}::"
                f"{household_candidate.candidate['id']}::household"
            ),
            query_patient=household_candidate.query,
            candidate_patient=household_candidate.candidate,
            is_true_match=False,
            strata={
                "pair_type": "special_population",
                "category": "multi_generational_household",
                **household_candidate.shared_fields,
            },
        )
    for institution_type in INSTITUTION_TYPES:
        for institutional_candidate in construct_institutional_negatives(
            patients, institution_type, group_size=institutional_group_size, rng=rng
        ):
            yield RawPair(
                pair_id=(
                    f"{institutional_candidate.query['id']}::"
                    f"{institutional_candidate.candidate['id']}::{institution_type}"
                ),
                query_patient=institutional_candidate.query,
                candidate_patient=institutional_candidate.candidate,
                is_true_match=False,
                strata={
                    "pair_type": "special_population",
                    "category": institution_type,
                },
            )


if __name__ == "__main__":
    sample_size = int(os.environ.get("SAMPLE_SIZE", DEFAULT_SAMPLE_SIZE))
    onc_dir = Path(__file__).parent / "fixtures" / "onc"
    # One shard only, not sorted(onc_dir.glob("*.csv")) (all 9) - see this
    # module's docstring and SYNTHETIC_DATA_SETUP.md before changing this.
    shard = sorted(onc_dir.glob("*.csv"))[0]
    patients = load_onc_patients([shard])[:sample_size]
    pairs = list(generate_raw_pairs(patients))
    counts = Counter(
        (
            p.strata.get("pair_type"),
            p.strata.get("mutation")
            or p.strata.get("case")
            or p.strata.get("category"),
        )
        for p in pairs
    )
    print(
        f"Built {len(pairs)} raw pairs from {len(patients)} ONC patients "
        f"(one shard, sampled to SAMPLE_SIZE={sample_size}):"
    )
    for (pair_type, subtype), count in sorted(counts.items(), key=lambda kv: -kv[1]):
        label = f"{pair_type}/{subtype}" if subtype else pair_type
        print(f"  {label}: {count}")
    print(
        "\nThis intentionally does not load all 9 ONC shards (~1,000,000 records) - "
        'see SYNTHETIC_DATA_SETUP.md\'s "Memory & scale" section before scaling up.'
    )
