"""Unit tests for onc_loader.py."""

from __future__ import annotations

import pytest
from onc_loader import _row_to_patient, make_nanp_valid


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
        patient = _row_to_patient(_row(PHONE="555-234-1111", PHONE2="555-222-3333"))
        phone_values = [
            t["value"] for t in patient["telecom"] if t["system"] == "phone"
        ]
        assert phone_values == ["555-234-1111", "555-222-3333"]

    def test_email_still_loads_after_both_phones(self) -> None:
        patient = _row_to_patient(
            _row(PHONE="555-234-1111", PHONE2="555-222-3333", EMAIL="jane@example.com")
        )
        assert patient["telecom"][-1] == {
            "system": "email",
            "value": "jane@example.com",
        }

    def test_missing_phone2_yields_a_single_phone_entry(self) -> None:
        patient = _row_to_patient(_row(PHONE="555-234-1111"))
        phone_entries = [t for t in patient["telecom"] if t["system"] == "phone"]
        assert len(phone_entries) == 1

    def test_missing_both_phones_yields_no_phone_entries(self) -> None:
        patient = _row_to_patient(_row())
        assert not any(t["system"] == "phone" for t in patient["telecom"])


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("917-130-8285", "917-230-8285"),  # exchange starts with 1 -> invalid NANP
        ("917-030-8285", "917-330-8285"),  # exchange starts with 0
        ("(917) 130-8285", "(917) 230-8285"),  # formatting preserved
        ("+1 917 130 8285", "+1 917 230 8285"),  # country code kept
        ("19171308285", "19172308285"),
        ("347-984-6839", "347-984-6839"),  # already valid -> unchanged
        ("", ""),  # empty -> unchanged
        ("917-130-828", "917-130-828"),  # not a 10-digit number -> unchanged
    ],
)
def test_make_nanp_valid(raw: str, expected: str) -> None:
    assert make_nanp_valid(raw) == expected


def test_make_nanp_valid_is_idempotent() -> None:
    once = make_nanp_valid("718-124-7797")
    assert make_nanp_valid(once) == once


def test_row_to_patient_phones_are_nanp_valid() -> None:
    patient = _row_to_patient(_row(PHONE="917-130-8285", PHONE2="347-984-6839"))
    values = [t["value"] for t in patient["telecom"] if t["system"] == "phone"]
    assert values == ["917-230-8285", "347-984-6839"]
