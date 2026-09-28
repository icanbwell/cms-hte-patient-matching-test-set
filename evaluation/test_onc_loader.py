"""Unit tests for onc_loader.py."""

from __future__ import annotations

from onc_loader import _row_to_patient


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
