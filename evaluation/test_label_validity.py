"""Label-validity invariants (session 15): no non-match pair may be possibly the
same person, in either output tier, for any generation category."""

from __future__ import annotations

from pathlib import Path

import pytest
from identity_guard import is_possible_same_person
from labeled_pairs import generate_raw_pairs
from onc_loader import load_onc_patients
from population_cases import build_population_dataset

ONC_DIR = Path(__file__).parent / "fixtures" / "onc"
SAMPLE = 1500


@pytest.fixture(scope="module")
def patients():
    shard = sorted(ONC_DIR.glob("*.csv"))[0]
    return load_onc_patients([shard])[:SAMPLE]


def test_no_per_provision_non_match_could_be_the_same_person(patients):
    offenders = [
        pair.pair_id
        for pair in generate_raw_pairs(patients, seed=0)
        if not pair.is_true_match
        and is_possible_same_person(pair.query_patient, pair.candidate_patient)
    ]
    assert offenders == []


def test_no_population_decoy_could_be_the_same_person_as_its_query(patients):
    dataset = build_population_dataset(patients, seed=0)
    offenders = []
    for case in dataset.cases:
        expected = set(case.expected_match_ids)
        for candidate_id in case.candidate_ids:
            if candidate_id in expected:
                continue
            if is_possible_same_person(
                case.query_patient, dataset.candidates[candidate_id]
            ):
                offenders.append(f"{case.query_id}::{candidate_id}")
    assert offenders == []


def test_every_multi_generational_household_pair_shares_a_street(patients):
    from special_populations import _street_key

    household = [
        pair
        for pair in generate_raw_pairs(patients, seed=0)
        if pair.strata.get("category") == "multi_generational_household"
    ]
    assert household
    assert all(
        _street_key(p.query_patient) == _street_key(p.candidate_patient)
        for p in household
    )
