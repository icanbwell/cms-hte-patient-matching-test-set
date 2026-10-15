"""Unit tests for onc_loader.py."""

from __future__ import annotations

from fhir_conformance import violations
from onc_loader import MOTHERS_MAIDEN_NAME_URL, _row_to_patient


def _row(**overrides):
    base = {
        "EnterpriseID": "1",
        "LAST": "SMITH",
        "FIRST": "JANE",
        "MIDDLE": "",
        "SUFFIX": "",
        "DOB": "8476",
        "GENDER": "FEMALE",
        "SSN": "",
        "ADDRESS1": "",
        "ADDRESS2": "",
        "ZIP": "",
        "MOTHERS_MAIDEN_NAME": "",
        "MRN": "",
        "CITY": "",
        "STATE": "",
        "PHONE": "",
        "PHONE2": "",
        "EMAIL": "",
        "ALIAS": "",
    }
    base.update(overrides)
    return base


class TestPhone2Loading:
    def test_both_phone_columns_load_as_separate_phone_telecom_entries(self) -> None:
        patient = _row_to_patient(_row(PHONE="555-000-1111", PHONE2="555-222-3333"))
        phone_values = [
            t["value"] for t in patient["telecom"] if t["system"] == "phone"
        ]
        assert phone_values == ["555-000-1111", "555-222-3333"]

    def test_email_still_loads_after_both_phones(self) -> None:
        patient = _row_to_patient(
            _row(PHONE="555-000-1111", PHONE2="555-222-3333", EMAIL="jane@example.com")
        )
        assert patient["telecom"][-1] == {
            "system": "email",
            "value": "jane@example.com",
        }

    def test_missing_phone2_yields_a_single_phone_entry(self) -> None:
        patient = _row_to_patient(_row(PHONE="555-000-1111"))
        phone_entries = [t for t in patient["telecom"] if t["system"] == "phone"]
        assert len(phone_entries) == 1

    def test_missing_both_phones_yields_no_phone_entries(self) -> None:
        patient = _row_to_patient(_row())
        assert not any(t["system"] == "phone" for t in patient["telecom"])


class TestNames:
    def test_empty_first_name_emits_no_given(self) -> None:
        patient = _row_to_patient(_row(FIRST=""))
        assert "given" not in patient["name"][0]
        # restored to == [] in Task 3
        assert not [v for v in violations(patient) if v.startswith("name")]

    def test_blank_suffix_and_middle_are_omitted(self) -> None:
        patient = _row_to_patient(_row(MIDDLE="", SUFFIX=""))
        assert patient["name"] == [
            {"use": "official", "family": "SMITH", "given": ["JANE"]}
        ]

    def test_middle_is_appended_to_given_and_suffix_kept(self) -> None:
        patient = _row_to_patient(_row(MIDDLE="Q", SUFFIX="JR"))
        assert patient["name"][0]["given"] == ["JANE", "Q"]
        assert patient["name"][0]["suffix"] == ["JR"]

    def test_alias_is_a_separate_nickname_entry_not_a_given_name(self) -> None:
        patient = _row_to_patient(_row(ALIAS="JANIE"))
        assert patient["name"][0]["given"] == ["JANE"]
        assert patient["name"][1] == {"use": "nickname", "text": "JANIE"}

    def test_row_with_no_name_parts_omits_name(self) -> None:
        patient = _row_to_patient(_row(FIRST="", LAST="", MIDDLE="", SUFFIX=""))
        assert "name" not in patient


class TestMothersMaidenName:
    def test_maps_to_the_standard_extension_not_a_name_entry(self) -> None:
        patient = _row_to_patient(_row(MOTHERS_MAIDEN_NAME="JONES"))
        assert len(patient["name"]) == 1
        assert patient["extension"] == [
            {"url": MOTHERS_MAIDEN_NAME_URL, "valueString": "JONES"}
        ]

    def test_absent_when_the_column_is_empty(self) -> None:
        assert "extension" not in _row_to_patient(_row())
