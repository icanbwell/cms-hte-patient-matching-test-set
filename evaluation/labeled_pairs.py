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
reference matching engine's normalization-manager dependency - see
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
from typing import Any, Dict, Iterator, List, Mapping, Sequence

from drift_profile import DriftProfile
from hard_negatives import (
    mine_name_collision_negatives,
    mine_shared_address_hard_negatives,
)
from household_assignment import shared_contact_case
from identity_guard import is_possible_same_person
from mutations import (
    count_changed_fields,
    generate_compound_variant,
    generate_fuzzy_variant,
)
from normalization_edge_cases import diacritic_variant, punctuation_variant
from onc_loader import load_onc_patients
from placeholders import COLLISION_FIELDS, construct_placeholder_collision_negatives
from scenarios import generate_scenario_variants
from special_populations import (
    INSTITUTION_TYPES,
    construct_household_negatives,
    construct_institutional_negatives,
    mine_shared_surname_household_negatives,
    mine_sibling_negatives,
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


def _effective_profile(
    profile: DriftProfile | None,
    *,
    include_ssn_dropped: bool,
    include_marriage_variant: bool,
    include_phone_variant: bool,
) -> DriftProfile:
    """The caller's profile (default: DriftProfile()) with any session-14
    scenario whose `include_*` flag is False switched off."""
    off = [
        name
        for name, enabled in (
            ("ssn_dropped", include_ssn_dropped),
            ("marriage_variant", include_marriage_variant),
            ("phone_variant", include_phone_variant),
        )
        if not enabled
    ]
    return (profile or DriftProfile()).without(*off)


def generate_raw_pairs(
    patients: List[Patient],
    *,
    n_fuzzy_variants_per_patient: int = 1,
    include_normalization_edge_cases: bool = True,
    include_special_populations: bool = True,
    include_compound_variants: bool = True,
    n_compound_mutations: int = 2,
    include_ssn_dropped: bool = True,
    include_marriage_variant: bool = True,
    include_phone_variant: bool = True,
    include_sibling_negatives: bool = True,
    include_name_collision_negatives: bool = True,
    sibling_max_age_gap_years: int = 3,
    household_constructed_max: int = 250,
    placeholder_collision_max: int = 100,
    name_collision_max_distance: int = 1,
    institutional_group_size: int = 3,
    donors: Sequence[Patient] = (),
    profile: DriftProfile | None = None,
    households: Sequence[Sequence[str]] = (),
    seed: int = 0,
) -> Iterator[RawPair]:
    """Yield RawPairs from ONC patients: fuzzy-variant true-matches,
    mined-hard-negative true-non-matches (session 9), plus (session 10)
    normalization-edge-case true-matches and special-population
    true-non-matches (mined multi-generational-household pairs and
    constructed institutional pairs). Session 14 further extends this with
    compound (multi-field) true-match variants, SSN-dropped/marriage/phone-
    number true-match scenarios, and sibling/name-collision hard negatives -
    all additive, default-on, appended alongside every prior category.
    """
    rng = random.Random(seed)
    profile = _effective_profile(
        profile,
        include_ssn_dropped=include_ssn_dropped,
        include_marriage_variant=include_marriage_variant,
        include_phone_variant=include_phone_variant,
    )

    for idx, p in enumerate(patients):
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
        if include_compound_variants:
            compound, mutation_types = generate_compound_variant(
                p, n_mutations=n_compound_mutations, rng=rng
            )
            # A field group can legitimately no-op entirely (e.g. an empty
            # given name, a missing birthDate) even though a different group
            # in the same draw succeeds - compound != p alone isn't enough to
            # guarantee the emitted pair actually touches n_compound_mutations
            # distinct fields, only that it touches at least one.
            if count_changed_fields(p, compound) >= n_compound_mutations:
                yield RawPair(
                    pair_id=f"{p['id']}::compound::{'-'.join(mutation_types)}",
                    query_patient=p,
                    candidate_patient=compound,
                    is_true_match=True,
                    strata={
                        "pair_type": "compound_variant",
                        "mutations": ",".join(mutation_types),
                    },
                )
        for scenario, result in generate_scenario_variants(
            p,
            next_patient=patients[(idx + 1) % len(patients)],
            donors=donors,
            profile=profile,
            seed=seed,
        ):
            yield RawPair(
                pair_id=f"{p['id']}::{result.suffix}",
                query_patient=p,
                candidate_patient=result.variant,
                is_true_match=True,
                strata={"pair_type": scenario.pair_type, **result.strata},
            )

    for candidate in mine_shared_address_hard_negatives(patients):
        yield RawPair(
            pair_id=f"{candidate.query['id']}::{candidate.candidate['id']}",
            query_patient=candidate.query,
            candidate_patient=candidate.candidate,
            is_true_match=False,
            strata={"pair_type": "hard_negative", **candidate.shared_fields},
        )

    if include_name_collision_negatives:
        for name_candidate in mine_name_collision_negatives(
            patients, max_name_distance=name_collision_max_distance
        ):
            yield RawPair(
                pair_id=(
                    f"{name_candidate.query['id']}::"
                    f"{name_candidate.candidate['id']}::name_collision"
                ),
                query_patient=name_candidate.query,
                candidate_patient=name_candidate.candidate,
                is_true_match=False,
                strata={
                    "pair_type": "name_collision_negative",
                    **name_candidate.shared_fields,
                },
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
    for constructed_household in construct_household_negatives(
        patients,
        max_pairs=household_constructed_max,
        rng=random.Random(f"{seed}:household"),
    ):
        yield RawPair(
            pair_id=(
                f"{constructed_household.query['id']}::"
                f"{constructed_household.candidate['id']}::household_constructed"
            ),
            query_patient=constructed_household.query,
            candidate_patient=constructed_household.candidate,
            is_true_match=False,
            strata={
                "pair_type": "special_population",
                "category": "multi_generational_household",
                **constructed_household.shared_fields,
            },
        )
    for field in COLLISION_FIELDS:
        for collision in construct_placeholder_collision_negatives(
            patients,
            field,
            max_pairs=placeholder_collision_max,
            rng=random.Random(f"{seed}:placeholder_collision:{field}"),
        ):
            yield RawPair(
                pair_id=(
                    f"{collision.query['id']}::{collision.candidate['id']}"
                    f"::placeholder_{field}"
                ),
                query_patient=collision.query,
                candidate_patient=collision.candidate,
                is_true_match=False,
                strata={
                    "pair_type": "placeholder_collision_negative",
                    **collision.shared_fields,
                },
            )
    by_id = {p["id"]: p for p in patients}
    for household in households:
        members = [by_id[pid] for pid in household if pid in by_id]
        for position, a in enumerate(members):
            for b in members[position + 1 :]:
                if is_possible_same_person(a, b):
                    continue
                yield RawPair(
                    pair_id=f"{a['id']}::{b['id']}::household_member",
                    query_patient=a,
                    candidate_patient=b,
                    is_true_match=False,
                    strata={
                        "pair_type": "household_member_negative",
                        "case": shared_contact_case(a, b),
                    },
                )
    if include_sibling_negatives:
        for sibling_candidate in mine_sibling_negatives(
            patients, max_age_gap_years=sibling_max_age_gap_years
        ):
            yield RawPair(
                pair_id=(
                    f"{sibling_candidate.query['id']}::"
                    f"{sibling_candidate.candidate['id']}::sibling"
                ),
                query_patient=sibling_candidate.query,
                candidate_patient=sibling_candidate.candidate,
                is_true_match=False,
                strata={
                    "pair_type": "sibling_negative",
                    **sibling_candidate.shared_fields,
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
            or p.strata.get("category")
            or p.strata.get("mutations"),
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
