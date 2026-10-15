"""Unit tests for fhir_conformance.py."""

from __future__ import annotations

from typing import Any, Dict

from fhir_conformance import SSN_SYSTEM, V2_0203_SYSTEM, prune_empty, violations

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
