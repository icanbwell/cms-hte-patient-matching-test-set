"""Unit tests for special_populations.py (session 10). No numpy dependency."""

from __future__ import annotations

import pytest
from special_populations import (
    INSTITUTION_TYPES,
    INSTITUTIONAL_ADDRESSES,
    construct_institutional_negatives,
    mine_shared_surname_household_negatives,
)


def _patient(id_, family, given="Pat", zip_code="10001", dob="1980-01-01"):
    return {
        "resourceType": "Patient",
        "id": id_,
        "name": [{"family": family, "given": [given]}],
        "birthDate": dob,
        "telecom": [],
        "address": [{"line": ["1 Main St"], "city": "NY", "state": "NY", "postalCode": zip_code}],
        "identifier": [],
    }


class TestConstructInstitutionalNegatives:
    def test_assigns_same_synthetic_address_to_every_group_member(self):
        patients = [_patient("p1", "Smith"), _patient("p2", "Jones"), _patient("p3", "Lee")]
        candidates = construct_institutional_negatives(patients, "shelter", group_size=3)
        assert len(candidates) == 3  # 3 choose 2
        for c in candidates:
            assert c.query["address"][0]["postalCode"] == INSTITUTIONAL_ADDRESSES["shelter"]["postalCode"]
            assert c.candidate["address"][0]["postalCode"] == INSTITUTIONAL_ADDRESSES["shelter"]["postalCode"]
            assert c.shared_fields["institution_type"] == "shelter"

    def test_never_pairs_two_patients_with_the_same_family_name(self):
        patients = [_patient("p1", "Smith"), _patient("p2", "Smith"), _patient("p3", "Lee")]
        candidates = construct_institutional_negatives(patients, "shelter", group_size=3)
        # Only 2 distinct family names available (Smith deduped) - group caps at 2, 1 pair.
        assert len(candidates) == 1

    def test_rejects_unknown_institution_type(self):
        with pytest.raises(ValueError):
            construct_institutional_negatives([_patient("p1", "Smith")], "not_a_real_type")

    def test_does_not_mutate_the_original_patients(self):
        patients = [_patient("p1", "Smith"), _patient("p2", "Jones")]
        construct_institutional_negatives(patients, "shelter", group_size=2)
        assert patients[0]["address"][0]["postalCode"] == "10001"

    def test_every_institution_type_has_a_distinct_synthetic_zip(self):
        zips = [addr["postalCode"] for addr in INSTITUTIONAL_ADDRESSES.values()]
        assert len(zips) == len(set(zips)) == len(INSTITUTION_TYPES)

    def test_every_institution_type_has_a_synthetic_marker_in_its_address_line(self):
        for addr in INSTITUTIONAL_ADDRESSES.values():
            assert "SYNTHETIC TEST ADDRESS" in addr["line"]


class TestMineSharedSurnameHouseholdNegatives:
    def test_finds_same_surname_same_zip_generational_gap(self):
        patients = [
            _patient("p1", "Rivera", dob="1955-03-01"),
            _patient("p2", "Rivera", dob="1988-07-14"),
        ]
        candidates = mine_shared_surname_household_negatives(patients)
        assert len(candidates) == 1
        assert candidates[0].shared_fields["family_name"] == "RIVERA"

    @pytest.mark.parametrize(
        "dob_a,dob_b,expect_match",
        [
            ("1988-01-01", "1990-06-01", False),  # ~2 years - below threshold
            ("1988-01-01", "2002-06-01", False),  # exactly 14 years - just below threshold
            ("1988-01-01", "2003-01-02", True),  # just over 15 years - at/above threshold
        ],
    )
    def test_age_gap_threshold_boundary(self, dob_a, dob_b, expect_match):
        patients = [
            _patient("p1", "Rivera", dob=dob_a),
            _patient("p2", "Rivera", dob=dob_b),
        ]
        candidates = mine_shared_surname_household_negatives(patients)
        assert (len(candidates) == 1) is expect_match

    def test_excludes_different_surnames(self):
        patients = [
            _patient("p1", "Rivera", dob="1955-03-01"),
            _patient("p2", "Chen", dob="1988-07-14"),
        ]
        assert mine_shared_surname_household_negatives(patients) == []

    def test_excludes_same_id(self):
        patients = [
            _patient("p1", "Rivera", dob="1955-03-01"),
            _patient("p1", "Rivera", dob="1988-07-14"),
        ]
        assert mine_shared_surname_household_negatives(patients) == []

    def test_excludes_pairs_missing_a_dob(self):
        a = _patient("p1", "Rivera", dob="1955-03-01")
        b = _patient("p2", "Rivera")
        del b["birthDate"]
        assert mine_shared_surname_household_negatives([a, b]) == []
