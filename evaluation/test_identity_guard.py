"""Unit tests for identity_guard.py (session 15)."""

from __future__ import annotations

from typing import Any, Dict

import pytest
from identity_guard import (
    SSN_SYSTEM,
    identity_key,
    is_possible_same_person,
    normalize_phone,
    normalize_token,
    ssn_of,
)


def _patient(
    id_: str,
    given: str = "Katherine",
    family: str = "Smith",
    dob: str | None = "1980-06-15",
    ssn: str | None = None,
):
    patient: Dict[str, Any] = {
        "resourceType": "Patient",
        "id": id_,
        "name": [{"family": family, "given": [given]}],
        "telecom": [],
        "address": [],
        "identifier": [],
    }
    if dob:
        patient["birthDate"] = dob
    if ssn:
        patient["identifier"].append({"system": SSN_SYSTEM, "value": ssn})
    return patient


class TestNormalizeToken:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Katherine", "katherine"),
            ("O'Brien", "obrien"),
            ("José", "jose"),
            ("  Smith-Jones ", "smithjones"),
            (None, ""),
        ],
    )
    def test_casefolds_strips_diacritics_and_punctuation(self, raw, expected):
        assert normalize_token(raw) == expected


class TestNormalizePhone:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("347-984-6839", "3479846839"),
            ("(347) 984-6839", "3479846839"),
            ("+1 347 984 6839", "3479846839"),
            ("1-347-984-6839", "3479846839"),
            ("984-6839", "9846839"),
            (None, ""),
        ],
    )
    def test_drops_formatting_and_a_leading_country_code(self, raw, expected):
        assert normalize_phone(raw) == expected


class TestSsnOf:
    def test_returns_digits_only(self):
        assert ssn_of(_patient("p1", ssn="892-39-5115")) == "892395115"

    @pytest.mark.parametrize(
        "placeholder", ["000-00-0000", "999-99-9999", "123-45-6789", "111-11-1111"]
    )
    def test_placeholder_ssns_are_treated_as_absent(self, placeholder):
        assert ssn_of(_patient("p1", ssn=placeholder)) is None

    def test_none_when_no_ssn_identifier(self):
        assert ssn_of(_patient("p1")) is None


class TestIdentityKey:
    def test_none_when_dob_missing(self):
        assert identity_key(_patient("p1", dob=None)) is None

    def test_none_when_name_missing(self):
        patient = _patient("p1")
        patient["name"] = []
        assert identity_key(patient) is None

    def test_normalizes_name_parts(self):
        assert identity_key(_patient("p1", given="JOSÉ", family="O'Neil")) == (
            "jose",
            "oneil",
            "1980-06-15",
        )


class TestIsPossibleSamePerson:
    def test_same_first_family_dob_under_different_ids(self):
        a = _patient("p1")
        b = _patient("p2", given="KATHERINE", family="SMITH")
        assert is_possible_same_person(a, b)

    def test_same_real_ssn_even_when_names_differ(self):
        a = _patient("p1", given="Ana", ssn="892-39-5115")
        b = _patient("p2", given="Luis", family="Rivera", ssn="892-39-5115")
        assert is_possible_same_person(a, b)

    def test_shared_placeholder_ssn_is_not_evidence(self):
        a = _patient("p1", given="Ana", ssn="000-00-0000")
        b = _patient("p2", given="Luis", family="Rivera", ssn="000-00-0000")
        assert not is_possible_same_person(a, b)

    def test_different_dob_same_name_is_not_flagged(self):
        a = _patient("p1", dob="1955-03-01")
        b = _patient("p2", dob="1988-07-14")
        assert not is_possible_same_person(a, b)

    def test_missing_dob_never_flags_on_name_alone(self):
        a = _patient("p1", dob=None)
        b = _patient("p2", dob=None)
        assert not is_possible_same_person(a, b)


class TestBarePatient:
    def test_a_patient_with_only_resource_type_and_id_never_raises(self):
        bare = {"resourceType": "Patient", "id": "x"}
        assert ssn_of(bare) is None
        assert identity_key(bare) is None
        assert not is_possible_same_person(bare, dict(bare, id="y"))


class TestSamePersonIndex:
    def test_returns_ids_sharing_identity_key_or_real_ssn(self):
        from identity_guard import SamePersonIndex

        dup = _patient("dup", given="KATHERINE", family="SMITH")
        ssn_twin = _patient("ssn", given="Ana", family="Lee", ssn="892-39-5115")
        other = _patient("other", given="Robert", family="Jones")
        index = SamePersonIndex([dup, ssn_twin, other])

        query = _patient("q", ssn="892-39-5115")
        assert index.matching_ids(query) == {"dup", "ssn"}

    def test_unrelated_patient_matches_nothing(self):
        from identity_guard import SamePersonIndex

        index = SamePersonIndex([_patient("a")])
        assert (
            index.matching_ids(_patient("z", given="Robert", family="Jones")) == set()
        )
