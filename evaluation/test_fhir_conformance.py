"""Unit tests for fhir_conformance.py."""

from __future__ import annotations

import csv
from typing import Any, Dict

from drift_profile import DriftProfile
from export_inputs import ONC_DIR, load_sample_and_donors
from fhir_conformance import (
    SSN_SYSTEM,
    V2_0203_SYSTEM,
    export_ready,
    prune_empty,
    renumber_telecom_ranks,
    violations,
)
from household_assignment import assign_households
from labeled_pairs import generate_raw_pairs
from onc_loader import _row_to_patient

SSN_TYPE = {"coding": [{"system": V2_0203_SYSTEM, "code": "SS"}]}


def _patient(**overrides):
    base = {
        "resourceType": "Patient",
        "id": "1",
        "name": [{"use": "official", "family": "Smith", "given": ["Jane"]}],
        "gender": "female",
        "telecom": [{"system": "phone", "value": "555-000-1111", "rank": 1}],
        "identifier": [
            {"system": SSN_SYSTEM, "type": SSN_TYPE, "value": "892-39-5115"}
        ],
    }
    base.update(overrides)
    return base


class TestViolations:
    def test_a_conformant_patient_has_no_violations(self) -> None:
        assert violations(_patient()) == []

    def test_empty_string_is_reported_with_its_path(self) -> None:
        patient = _patient(name=[{"use": "official", "family": "Smith", "given": [""]}])
        assert violations(patient) == ["name[0].given[0]: empty string"]

    def test_empty_array_is_reported(self) -> None:
        assert violations(_patient(address=[])) == ["address: empty array"]

    def test_null_is_reported(self) -> None:
        assert violations(_patient(birthDate=None)) == ["birthDate: null"]

    def test_caret_in_telecom_value_is_reported(self) -> None:
        patient = _patient(
            telecom=[{"system": "phone", "value": "555-000-1111^^555-222-3333"}]
        )
        assert violations(patient) == ["telecom[0].value: contains '^'"]

    def test_unknown_telecom_system_is_reported(self) -> None:
        patient = _patient(telecom=[{"system": "carrier-pigeon", "value": "x"}])
        assert violations(patient) == [
            "telecom[0].system: 'carrier-pigeon' not a ContactPointSystem"
        ]

    def test_duplicate_rank_within_a_system_is_reported(self) -> None:
        patient = _patient(
            telecom=[
                {"system": "phone", "value": "1", "rank": 1},
                {"system": "phone", "value": "2", "rank": 1},
            ]
        )
        assert violations(patient) == ["telecom: duplicate rank within system 'phone'"]

    def test_same_rank_in_different_systems_is_fine(self) -> None:
        patient = _patient(
            telecom=[
                {"system": "phone", "value": "1", "rank": 1},
                {"system": "email", "value": "a@b.c", "rank": 1},
            ]
        )
        assert violations(patient) == []

    def test_name_use_outside_the_binding_is_reported(self) -> None:
        patient = _patient(name=[{"use": "alias", "family": "Smith"}])
        assert violations(patient) == ["name[0].use: 'alias' not in NameUse"]

    def test_ssn_identifier_without_type_is_reported(self) -> None:
        patient = _patient(identifier=[{"system": SSN_SYSTEM, "value": "892-39-5115"}])
        assert violations(patient) == [
            "identifier[0]: SSN identifier lacks type coding SS"
        ]


class TestPruneEmpty:
    def test_removes_empty_values_recursively(self) -> None:
        value: Dict[str, Any] = {
            "a": "",
            "b": [],
            "c": {},
            "d": None,
            "e": {"f": [""], "g": 1},
        }
        assert prune_empty(value) == {"e": {"g": 1}}

    def test_keeps_zero_and_false(self) -> None:
        assert prune_empty({"rank": 0, "active": False}) == {"rank": 0, "active": False}

    def test_does_not_mutate_its_input(self) -> None:
        value: Dict[str, Any] = {"identifier": []}
        prune_empty(value)
        assert value == {"identifier": []}


class TestCorpus:
    def test_every_50th_row_of_every_onc_shard_is_conformant(self) -> None:
        checked = 0
        for path in sorted(ONC_DIR.glob("*.csv")):
            with open(path, newline="", encoding="utf-8") as f:
                for index, row in enumerate(csv.DictReader(f)):
                    if index % 50:
                        continue
                    patient = _row_to_patient(row)
                    assert violations(patient) == [], (path.name, row["EnterpriseID"])
                    checked += 1
        assert checked > 15000


class TestRenumberTelecomRanks:
    def test_duplicate_rank_one_becomes_one_two(self) -> None:
        telecom = [
            {"system": "phone", "value": "1", "rank": 1},
            {"system": "phone", "value": "2", "rank": 1},
        ]
        result = renumber_telecom_ranks(_patient(telecom=telecom))
        assert [t["rank"] for t in result["telecom"]] == [1, 2]
        assert violations(result) == []

    def test_stale_lone_rank_two_becomes_one(self) -> None:
        telecom = [{"system": "phone", "value": "1", "rank": 2}]
        result = renumber_telecom_ranks(_patient(telecom=telecom))
        assert result["telecom"][0]["rank"] == 1

    def test_ranks_restart_per_system(self) -> None:
        telecom = [
            {"system": "phone", "value": "1", "rank": 3},
            {"system": "email", "value": "a@x.org", "rank": 2},
            {"system": "phone", "value": "2", "rank": 1},
        ]
        result = renumber_telecom_ranks(_patient(telecom=telecom))
        assert [(t["system"], t["rank"]) for t in result["telecom"]] == [
            ("phone", 1),
            ("email", 1),
            ("phone", 2),
        ]

    def test_rankless_entries_stay_rankless(self) -> None:
        telecom = [
            {"system": "phone", "value": "1"},
            {"system": "phone", "value": "2", "rank": 5},
        ]
        result = renumber_telecom_ranks(_patient(telecom=telecom))
        assert "rank" not in result["telecom"][0]
        assert result["telecom"][1]["rank"] == 1

    def test_patient_without_telecom_is_unchanged(self) -> None:
        patient = _patient()
        del patient["telecom"]
        assert renumber_telecom_ranks(patient) == patient

    def test_input_is_not_mutated(self) -> None:
        telecom = [
            {"system": "phone", "value": "1", "rank": 1},
            {"system": "phone", "value": "2", "rank": 1},
        ]
        patient = _patient(telecom=telecom)
        renumber_telecom_ranks(patient)
        assert [t["rank"] for t in patient["telecom"]] == [1, 1]


class TestExportReady:
    def test_prunes_and_renumbers(self) -> None:
        telecom = [
            {"system": "phone", "value": "1", "rank": 2},
            {"system": "phone", "value": "2", "rank": 2},
        ]
        result = export_ready(_patient(telecom=telecom, identifier=[]))
        assert "identifier" not in result
        assert [t["rank"] for t in result["telecom"]] == [1, 2]


class TestGeneratedPairs:
    def test_every_generated_pair_is_conformant_after_export_ready(self) -> None:
        patients, donors = load_sample_and_donors(300, 300)
        profile = DriftProfile()
        housed = assign_households(patients, profile=profile, seed=0)
        for pair in generate_raw_pairs(
            housed.patients,
            donors=donors,
            profile=profile,
            households=housed.households,
            seed=0,
        ):
            for side in (pair.query_patient, pair.candidate_patient):
                assert violations(export_ready(side)) == [], pair.pair_id
