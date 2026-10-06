"""Unit tests for hard_negatives.py (session 9). No numpy dependency."""

from __future__ import annotations

from hard_negatives import (
    mine_name_collision_negatives,
    mine_shared_address_hard_negatives,
)


def _patient(id_: str, family: str, zip_code: str = "10001", dob: str = "1980-01-01"):
    return {
        "resourceType": "Patient",
        "id": id_,
        "name": [{"family": family, "given": ["Pat"]}],
        "birthDate": dob,
        "telecom": [],
        "address": [
            {"line": ["1 Main St"], "city": "NY", "state": "NY", "postalCode": zip_code}
        ],
        "identifier": [],
    }


class TestMineSharedAddressHardNegatives:
    def test_finds_distinct_family_names_sharing_zip_and_dob(self) -> None:
        patients = [
            _patient("p1", "Smith"),
            _patient("p2", "Jones"),
        ]
        candidates = mine_shared_address_hard_negatives(patients)
        assert len(candidates) == 1
        assert {candidates[0].query["id"], candidates[0].candidate["id"]} == {
            "p1",
            "p2",
        }
        assert candidates[0].shared_fields == {
            "postalCode": "10001",
            "birthDate": "1980-01-01",
        }

    def test_excludes_pairs_sharing_the_same_family_name(self) -> None:
        """Same ZIP+DOB+family name looks like a mutation/duplicate variant of one
        identity, not a genuine hard negative - this module's job is disjoint from
        mutations.py's."""
        patients = [
            _patient("p1", "Smith"),
            _patient("p2", "Smith"),
        ]
        assert mine_shared_address_hard_negatives(patients) == []

    def test_excludes_records_missing_zip_or_dob(self) -> None:
        p1 = _patient("p1", "Smith")
        p1["address"] = []
        p2 = _patient("p2", "Jones")
        assert mine_shared_address_hard_negatives([p1, p2]) == []

    def test_never_pairs_a_record_with_itself(self) -> None:
        patient = _patient("p1", "Smith")
        assert mine_shared_address_hard_negatives([patient, patient]) == []

    def test_no_shared_zip_dob_yields_no_candidates(self) -> None:
        patients = [
            _patient("p1", "Smith", zip_code="10001"),
            _patient("p2", "Jones", zip_code="20002"),
        ]
        assert mine_shared_address_hard_negatives(patients) == []

    def test_group_of_three_yields_all_pairwise_candidates(self) -> None:
        patients = [
            _patient("p1", "Smith"),
            _patient("p2", "Jones"),
            _patient("p3", "Lee"),
        ]
        candidates = mine_shared_address_hard_negatives(patients)
        pairs = {frozenset({c.query["id"], c.candidate["id"]}) for c in candidates}
        assert pairs == {
            frozenset({"p1", "p2"}),
            frozenset({"p1", "p3"}),
            frozenset({"p2", "p3"}),
        }

    def test_excludes_pairs_sharing_a_real_ssn(self) -> None:
        a = _patient("p1", "Smith", zip_code="10001", dob="1980-01-01")
        b = _patient("p2", "Jones", zip_code="10001", dob="1980-01-01")
        # Same ZIP+DOB, different family names - all OTHER filters pass
        # But they share a real SSN, so is_possible_same_person should exclude them
        ssn = {"system": "http://hl7.org/fhir/sid/us-ssn", "value": "892-39-5115"}
        for patient in (a, b):
            patient["identifier"] = [ssn]
        assert mine_shared_address_hard_negatives([a, b]) == []


def _named_patient(id_: str, given: str, family: str, zip_code: str, dob: str):
    return {
        "resourceType": "Patient",
        "id": id_,
        "name": [{"family": family, "given": [given]}],
        "birthDate": dob,
        "telecom": [],
        "address": [
            {"line": ["1 Main St"], "city": "NY", "state": "NY", "postalCode": zip_code}
        ],
        "identifier": [],
    }


class TestMineNameCollisionNegatives:
    def test_finds_near_identical_names_with_no_zip_or_dob_overlap(self) -> None:
        patients = [
            _named_patient("p1", "Pat", "Smith", "10001", "1980-01-01"),
            _named_patient("p2", "Pat", "Smyth", "20002", "1990-05-05"),
        ]
        candidates = mine_name_collision_negatives(patients)
        assert len(candidates) == 1
        assert candidates[0].shared_fields["name_distance"] == "1"

    def test_excludes_pairs_sharing_a_zip_code(self) -> None:
        patients = [
            _named_patient("p1", "Pat", "Smith", "10001", "1980-01-01"),
            _named_patient("p2", "Pat", "Smyth", "10001", "1990-05-05"),
        ]
        assert mine_name_collision_negatives(patients) == []

    def test_excludes_pairs_sharing_a_dob(self) -> None:
        patients = [
            _named_patient("p1", "Pat", "Smith", "10001", "1980-01-01"),
            _named_patient("p2", "Pat", "Smyth", "20002", "1980-01-01"),
        ]
        assert mine_name_collision_negatives(patients) == []

    def test_excludes_names_beyond_max_distance(self) -> None:
        patients = [
            _named_patient("p1", "Pat", "Smith", "10001", "1980-01-01"),
            _named_patient("p2", "Pat", "Johnson", "20002", "1990-05-05"),
        ]
        assert mine_name_collision_negatives(patients, max_name_distance=1) == []

    def test_excludes_identical_names(self) -> None:
        patients = [
            _named_patient("p1", "Pat", "Smith", "10001", "1980-01-01"),
            _named_patient("p2", "Pat", "Smith", "20002", "1990-05-05"),
        ]
        assert mine_name_collision_negatives(patients) == []

    def test_never_pairs_a_record_with_itself(self) -> None:
        patient = _named_patient("p1", "Pat", "Smith", "10001", "1980-01-01")
        assert mine_name_collision_negatives([patient, patient]) == []

    def test_different_first_letter_is_not_found_due_to_blocking(self) -> None:
        patients = [
            _named_patient("p1", "Pat", "Smith", "10001", "1980-01-01"),
            _named_patient("p2", "Pat", "Amith", "20002", "1990-05-05"),
        ]
        assert mine_name_collision_negatives(patients) == []

    def test_finds_collisions_within_a_large_same_letter_bucket_without_timing_out(
        self,
    ) -> None:
        # Every patient here lands in the same first-letter bucket ("S") - the
        # length-window pruning inside the bucket must still find the one real
        # collision (Smith/Smyth) among 300 same-letter, mostly-unrelated names,
        # and must do so fast (this test itself is the regression guard: it
        # would take minutes, not milliseconds, without pruning).
        patients = [
            _named_patient(
                f"filler{i}",
                "Pat",
                f"S{'x' * (i % 12 + 3)}",
                f"{10100 + i}",
                "1970-01-01",
            )
            for i in range(300)
        ]
        patients.append(_named_patient("p1", "Pat", "Smith", "10001", "1980-01-01"))
        patients.append(_named_patient("p2", "Pat", "Smyth", "20002", "1990-05-05"))
        candidates = mine_name_collision_negatives(patients)
        pairs = {frozenset({c.query["id"], c.candidate["id"]}) for c in candidates}
        assert frozenset({"p1", "p2"}) in pairs

    def test_excludes_pairs_sharing_a_real_ssn(self) -> None:
        a = _named_patient("p1", "Pat", "Smith", "10001", "1980-01-01")
        b = _named_patient("p2", "Pat", "Smyth", "20002", "1990-05-05")
        # Name distance is 1 (Smith/Smyth), different ZIP and DOB - all OTHER filters pass
        # But they share a real SSN, so is_possible_same_person should exclude them
        ssn = {"system": "http://hl7.org/fhir/sid/us-ssn", "value": "892-39-5115"}
        for patient in (a, b):
            patient["identifier"] = [ssn]
        assert mine_name_collision_negatives(patients=[a, b]) == []
