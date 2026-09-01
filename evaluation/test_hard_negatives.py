"""Unit tests for hard_negatives.py (session 9). No numpy dependency."""

from __future__ import annotations

from hard_negatives import mine_shared_address_hard_negatives


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
