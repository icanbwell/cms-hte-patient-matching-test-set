"""Unit tests for special_populations.py (session 10). No numpy dependency."""

from __future__ import annotations

import random

import pytest
from special_populations import (
    INSTITUTION_TYPES,
    INSTITUTIONAL_ADDRESSES,
    construct_household_negatives,
    construct_institutional_negatives,
    mine_shared_surname_household_negatives,
    mine_sibling_negatives,
)


def _patient(
    id_, family, given="Pat", zip_code="10001", dob="1980-01-01", street="1 Main St"
):
    return {
        "resourceType": "Patient",
        "id": id_,
        "name": [{"family": family, "given": [given]}],
        "birthDate": dob,
        "telecom": [],
        "address": [
            {"line": [street], "city": "NY", "state": "NY", "postalCode": zip_code}
        ],
        "identifier": [],
    }


class TestConstructInstitutionalNegatives:
    def test_assigns_same_synthetic_address_to_every_group_member(self):
        patients = [
            _patient("p1", "Smith"),
            _patient("p2", "Jones"),
            _patient("p3", "Lee"),
        ]
        candidates = construct_institutional_negatives(
            patients, "shelter", group_size=3
        )
        assert len(candidates) == 3  # 3 choose 2
        for c in candidates:
            assert (
                c.query["address"][0]["postalCode"]
                == INSTITUTIONAL_ADDRESSES["shelter"]["postalCode"]
            )
            assert (
                c.candidate["address"][0]["postalCode"]
                == INSTITUTIONAL_ADDRESSES["shelter"]["postalCode"]
            )
            assert c.shared_fields["institution_type"] == "shelter"

    def test_never_pairs_two_patients_with_the_same_family_name(self):
        patients = [
            _patient("p1", "Smith"),
            _patient("p2", "Smith"),
            _patient("p3", "Lee"),
        ]
        candidates = construct_institutional_negatives(
            patients, "shelter", group_size=3
        )
        # Only 2 distinct family names available (Smith deduped) - group caps at 2, 1 pair.
        assert len(candidates) == 1

    def test_never_groups_two_possible_same_person_records(self):
        ssn = {"system": "http://hl7.org/fhir/sid/us-ssn", "value": "892-39-5115"}
        for seed in range(20):
            p1, p2 = _patient("p1", "Smith"), _patient("p2", "Jones")
            p1["identifier"] = [ssn]
            p2["identifier"] = [ssn]
            candidates = construct_institutional_negatives(
                [p1, p2, _patient("p3", "Lee")],
                "shelter",
                group_size=3,
                rng=random.Random(seed),
            )
            for c in candidates:
                assert {c.query["id"], c.candidate["id"]} != {"p1", "p2"}

    def test_rejects_unknown_institution_type(self):
        with pytest.raises(ValueError):
            construct_institutional_negatives(
                [_patient("p1", "Smith")], "not_a_real_type"
            )

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
            (
                "1988-01-01",
                "2002-06-01",
                False,
            ),  # exactly 14 years - just below threshold
            (
                "1988-01-01",
                "2003-01-02",
                True,
            ),  # just over 15 years - at/above threshold
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

    def test_excludes_pairs_with_missing_street_keys(self) -> None:
        a = _patient("p1", "Rivera", dob="1955-03-01")
        b = _patient("p2", "Rivera", dob="1988-07-14")
        # Remove address lines, leaving only postal codes - _street_key returns None
        a["address"][0]["line"] = []
        b["address"][0]["line"] = []
        # Both have postal codes but no street lines, so _street_key() returns None for both
        # Should be excluded because same_street=True requires them to share a street
        assert mine_shared_surname_household_negatives([a, b]) == []

    def test_household_miner_excludes_ssn_same_person(self) -> None:
        a = _patient("p1", "Rivera", given="Rosa", dob="1950-03-01", street="1 Main St")
        b = _patient("p2", "Rivera", given="Luis", dob="1988-07-14", street="1 Main St")
        # Same street, 38 year gap, different first names - all OTHER filters pass
        # But they share a real SSN, so is_possible_same_person should exclude them
        ssn = {"system": "http://hl7.org/fhir/sid/us-ssn", "value": "892-39-5115"}
        for patient in (a, b):
            patient["identifier"] = [ssn]
        assert mine_shared_surname_household_negatives([a, b]) == []


class TestMineSiblingNegatives:
    def test_finds_same_family_same_zip_close_in_age(self) -> None:
        patients = [
            _patient("p1", "Rivera", given="Ana", dob="2010-01-01"),
            _patient("p2", "Rivera", given="Luis", dob="2011-06-01"),
        ]
        candidates = mine_sibling_negatives(patients)
        assert len(candidates) == 1
        assert candidates[0].shared_fields["age_gap_years"] == "1"

    def test_excludes_pairs_beyond_max_age_gap_years(self) -> None:
        patients = [
            _patient("p1", "Rivera", dob="1970-01-01"),
            _patient("p2", "Rivera", dob="2010-01-01"),
        ]
        assert mine_sibling_negatives(patients, max_age_gap_years=3) == []

    def test_boundary_gap_equal_to_max_is_included(self) -> None:
        patients = [
            _patient("p1", "Rivera", given="Ana", dob="2010-01-01"),
            _patient("p2", "Rivera", given="Luis", dob="2013-01-01"),
        ]
        candidates = mine_sibling_negatives(patients, max_age_gap_years=3)
        assert len(candidates) == 1

    def test_excludes_different_family_names(self) -> None:
        patients = [
            _patient("p1", "Rivera", dob="2010-01-01"),
            _patient("p2", "Chen", dob="2010-06-01"),
        ]
        assert mine_sibling_negatives(patients) == []

    def test_excludes_different_zip_codes(self) -> None:
        patients = [
            _patient("p1", "Rivera", zip_code="10001", dob="2010-01-01"),
            _patient("p2", "Rivera", zip_code="20002", dob="2010-06-01"),
        ]
        assert mine_sibling_negatives(patients) == []

    def test_never_pairs_a_record_with_itself(self) -> None:
        patient = _patient("p1", "Rivera", dob="2010-01-01")
        assert mine_sibling_negatives([patient, patient]) == []

    def test_excludes_same_first_name_even_with_a_different_dob(self) -> None:
        patients = [
            _patient("p1", "Rivera", given="Ana", dob="2010-01-01"),
            _patient("p2", "Rivera", given="ANA", dob="2011-06-01"),
        ]
        assert mine_sibling_negatives(patients) == []

    def test_excludes_pairs_sharing_a_real_ssn(self) -> None:
        a = _patient("p1", "Rivera", given="Ana", dob="2010-01-01")
        b = _patient("p2", "Rivera", given="Luis", dob="2011-06-01")
        for patient in (a, b):
            patient["identifier"] = [
                {"system": "http://hl7.org/fhir/sid/us-ssn", "value": "892-39-5115"}
            ]
        assert mine_sibling_negatives([a, b]) == []


class TestHouseholdSameStreet:
    def test_mined_household_pairs_must_share_a_street(self) -> None:
        patients = [
            _patient("p1", "Rivera", dob="1955-03-01", street="1 Main St"),
            _patient("p2", "Rivera", dob="1988-07-14", street="9 Elm St"),
        ]
        assert mine_shared_surname_household_negatives(patients) == []

    def test_street_comparison_ignores_case_and_punctuation(self) -> None:
        patients = [
            _patient("p1", "Rivera", dob="1955-03-01", street="1 Main St."),
            _patient("p2", "Rivera", dob="1988-07-14", street="1 MAIN ST"),
        ]
        assert len(mine_shared_surname_household_negatives(patients)) == 1


class TestConstructHouseholdNegatives:
    def _family(self):
        return [
            _patient(
                "p1",
                "Rivera",
                given="Rosa",
                dob="1950-03-01",
                zip_code="10001",
                street="1 Main St",
            ),
            _patient(
                "p2",
                "Rivera",
                given="Luis",
                dob="1988-07-14",
                zip_code="20002",
                street="9 Elm St",
            ),
        ]

    def test_gives_the_younger_record_the_elders_address(self) -> None:
        (candidate,) = construct_household_negatives(self._family())
        assert candidate.query["id"] == "p1"
        assert candidate.candidate["id"] == "p2"
        assert candidate.candidate["address"] == candidate.query["address"]
        assert candidate.shared_fields["address_source"] == "constructed"
        assert candidate.shared_fields["age_gap_years"] == "38"

    def test_does_not_mutate_the_input_patients(self) -> None:
        patients = self._family()
        construct_household_negatives(patients)
        assert patients[1]["address"][0]["postalCode"] == "20002"

    def test_skips_pairs_that_already_share_a_street(self) -> None:
        patients = [
            _patient("p1", "Rivera", given="Rosa", dob="1950-03-01"),
            _patient("p2", "Rivera", given="Luis", dob="1988-07-14"),
        ]
        assert construct_household_negatives(patients) == []

    def test_skips_gaps_below_the_minimum(self) -> None:
        patients = self._family()
        patients[1]["birthDate"] = "1960-01-01"
        assert construct_household_negatives(patients) == []

    def test_excludes_records_that_could_be_the_same_person(self) -> None:
        patients = self._family()
        # Gap is already 38 years (>= 15), streets are different (will trigger construction)
        # Different first names (Rosa vs Luis), so require_distinct_given passes
        # But they share a real SSN, so is_possible_same_person should exclude them
        ssn = {"system": "http://hl7.org/fhir/sid/us-ssn", "value": "892-39-5115"}
        for patient in patients:
            patient["identifier"] = [ssn]
        assert construct_household_negatives(patients) == []

    def test_respects_max_pairs_and_is_deterministic_for_a_seed(self) -> None:
        patients = []
        for i, family in enumerate(["Rivera", "Chen", "Okafor"]):
            elder, younger = self._family()
            elder["id"], younger["id"] = f"e{i}", f"y{i}"
            for p in (elder, younger):
                p["name"][0]["family"] = family
            patients += [elder, younger]
        first = construct_household_negatives(
            patients, max_pairs=2, rng=random.Random(1)
        )
        again = construct_household_negatives(
            patients, max_pairs=2, rng=random.Random(1)
        )
        assert len(first) == 2
        assert [c.query["id"] for c in first] == [c.query["id"] for c in again]

    def test_ignores_patients_without_an_address_or_birth_date(self) -> None:
        bare = {"resourceType": "Patient", "id": "x", "name": [{"family": "Rivera"}]}
        patients = [bare, dict(bare, id="y")]
        assert construct_household_negatives(patients) == []

    def test_unparseable_birth_dates_are_skipped_not_fatal(self) -> None:
        patients = self._family()
        patients[1]["birthDate"] = "unknown"
        assert construct_household_negatives(patients) == []

    def test_max_pairs_zero_returns_nothing(self) -> None:
        assert construct_household_negatives(self._family(), max_pairs=0) == []

    def _three_generations(self):
        return [
            _patient("g1", "Rivera", given="Rosa", dob="1950-03-01", street="1 A St"),
            _patient("g2", "Rivera", given="Luis", dob="1990-07-14", street="2 B St"),
            _patient("g3", "Rivera", given="Ana", dob="2005-02-02", street="3 C St"),
        ]

    def test_picks_the_smallest_eligible_age_gap_in_a_family(self) -> None:
        (candidate,) = construct_household_negatives(self._three_generations())
        assert candidate.query["id"] == "g2"
        assert candidate.candidate["id"] == "g3"
        assert candidate.shared_fields["age_gap_years"] == "15"

    def test_malformed_birth_date_drops_only_that_record(self) -> None:
        patients = self._family()
        patients.append(
            _patient("bad", "Rivera", given="Zed", dob="unknown", street="5 E St")
        )
        (candidate,) = construct_household_negatives(patients)
        assert {candidate.query["id"], candidate.candidate["id"]} == {"p1", "p2"}

    def test_equal_gap_tie_break_is_independent_of_input_order(self) -> None:
        def members():
            return [
                _patient("a", "Rivera", given="A", dob="1950-01-01", street="1 A St"),
                _patient("b", "Rivera", given="B", dob="1950-01-01", street="2 B St"),
                _patient("c", "Rivera", given="C", dob="1980-01-01", street="3 C St"),
                _patient("d", "Rivera", given="D", dob="1980-01-01", street="4 D St"),
            ]

        chosen = set()
        for order in ([0, 1, 2, 3], [3, 2, 1, 0], [2, 0, 3, 1]):
            patients = members()
            (c,) = construct_household_negatives([patients[i] for i in order])
            chosen.add((c.query["id"], c.candidate["id"]))
        assert chosen == {("a", "c")}
