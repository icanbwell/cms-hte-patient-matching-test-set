"""Unit tests for identity_guard.py (session 15)."""

from __future__ import annotations

from typing import Any, Dict

import pytest
from identity_guard import (
    SSN_SYSTEM,
    ProbableDuplicateIndex,
    identity_key,
    is_possible_same_person,
    is_probable_duplicate,
    is_twin_pair,
    looks_like_same_person,
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


def test_is_placeholder_ssn_rejects_unissuable_values():
    from identity_guard import is_placeholder_ssn

    for bad in (
        "222222222",
        "000123456",
        "666123456",
        "912345678",
        "123004567",
        "123450000",
        "078051120",
        "12345",
    ):
        assert is_placeholder_ssn(bad), bad
    assert not is_placeholder_ssn("123456780")


def _with_phone(patient, phone):
    patient["telecom"] = [{"system": "phone", "value": phone}]
    return patient


class TestIsProbableDuplicate:
    def test_ssn_one_digit_off_is_a_duplicate_even_with_different_names_and_dobs(self):
        a = _patient("a", "Eugene", "Benally", "1971-01-01", ssn="892-39-5115")
        b = _patient("b", "Maria", "Lopez", "1999-09-09", ssn="892-39-5116")
        assert is_probable_duplicate(a, b)

    def test_ssns_two_digits_apart_are_not_a_duplicate(self):
        a = _patient("a", "Eugene", "Benally", "1971-01-01", ssn="892-39-5115")
        b = _patient("b", "Maria", "Lopez", "1999-09-09", ssn="892-39-5126")
        assert not is_probable_duplicate(a, b)

    def test_placeholder_ssns_never_count(self):
        a = _patient("a", "Eugene", "Benally", "1971-01-01", ssn="123-45-6789")
        b = _patient("b", "Maria", "Lopez", "1999-09-09", ssn="123-45-6788")
        assert not is_probable_duplicate(a, b)

    def test_shared_phone_with_dob_one_digit_apart_is_a_duplicate(self):
        a = _with_phone(
            _patient("a", "Harris", "Greene", "1980-06-15"), "(347) 984-6839"
        )
        b = _with_phone(_patient("b", "Jim", "Other", "1980-06-16"), "347-984-6839")
        assert is_probable_duplicate(a, b)

    def test_shared_phone_with_identical_dob_is_a_duplicate(self):
        a = _with_phone(_patient("a", "Harris", "Greene", "1980-06-15"), "3479846839")
        b = _with_phone(_patient("b", "Jim", "Other", "1980-06-15"), "3479846839")
        assert is_probable_duplicate(a, b)

    def test_shared_phone_with_a_month_day_swapped_dob_is_a_duplicate(self):
        a = _with_phone(_patient("a", dob="1980-03-11"), "3479846839")
        b = _with_phone(_patient("b", "Jim", "Other", "1980-11-03"), "3479846839")
        assert is_probable_duplicate(a, b)

    def test_shared_phone_with_a_clearly_different_dob_is_not_a_duplicate(self):
        a = _with_phone(_patient("a", dob="1950-06-15"), "3479846839")
        b = _with_phone(_patient("b", "Jim", "Other", "1971-06-15"), "3479846839")
        assert not is_probable_duplicate(a, b)

    def test_name_typo_with_dob_one_digit_apart_is_a_duplicate(self):
        a = _patient("a", "Gerald", "Gutschow", "1980-11-05")
        b = _patient("b", "Gerald", "Gutachow", "1980-12-05")
        assert is_probable_duplicate(a, b)

    def test_identical_name_with_dob_one_digit_apart_is_a_duplicate(self):
        a = _patient("a", "Rosalind", "Vandermeer", "1980-06-15")
        b = _patient("b", "Rosalind", "Vandermeer", "1980-06-25")
        assert is_probable_duplicate(a, b)

    def test_name_match_with_a_clearly_different_dob_is_a_legitimate_hard_negative(
        self,
    ):
        a = _patient("a", "Rosalind", "Vandermeer", "1950-06-15")
        b = _patient("b", "Rosalind", "Vandermeer", "1971-06-15")
        assert not is_probable_duplicate(a, b)

    def test_names_two_edits_apart_are_not_a_duplicate(self):
        a = _patient("a", "Rosalind", "Vandermeer", "1980-06-15")
        b = _patient("b", "Rosalind", "Vandermoor", "1980-06-15")
        assert not is_probable_duplicate(a, b)

    def test_missing_birth_dates_never_trigger_the_name_or_phone_rules(self):
        a = _with_phone(_patient("a", dob=None), "3479846839")
        b = _with_phone(_patient("b", dob=None), "3479846839")
        assert not is_probable_duplicate(a, b)


class TestLooksLikeSamePerson:
    def test_true_for_an_exact_match(self):
        assert looks_like_same_person(_patient("a"), _patient("b"))

    def test_true_for_a_typo_duplicate_the_exact_check_misses(self):
        a = _patient("a", "Eugene", "Benally", "1971-01-01", ssn="892-39-5115")
        b = _patient("b", "Maria", "Lopez", "1999-09-09", ssn="892-39-5116")
        assert not is_possible_same_person(a, b)
        assert looks_like_same_person(a, b)

    def test_false_for_different_people(self):
        other = _patient("b", "Maria", "Lopez", "1999-09-09")
        assert not looks_like_same_person(_patient("a"), other)


class TestProbableDuplicateIndex:
    def _people(self):
        return [
            _patient("a", "Eugene", "Benally", "1971-01-01", ssn="892-39-5115"),
            _patient(
                "b", "Maria", "Lopez", "1999-09-09", ssn="892-39-5116"
            ),  # SSN typo of a
            _patient("c", "Eugene", "Benally", "1971-01-02"),  # name + DOB typo of a
            _patient("d", "Eugene", "Benally", "1971-02-01"),  # month/day swap of a
            _patient("e", "Ana", "Rivera", "1985-05-05"),
            _patient("f", "Omar", "Haddad", "1962-12-25"),
        ]

    def test_agrees_with_comparing_every_pair(self):
        people = self._people()
        index = ProbableDuplicateIndex(people)
        for patient in people:
            expected = {
                o["id"]
                for o in people
                if o["id"] != patient["id"] and is_probable_duplicate(patient, o)
            }
            assert index.matching_ids(patient) == expected

    def test_finds_the_ssn_typo_the_name_check_would_miss(self):
        index = ProbableDuplicateIndex(self._people())
        assert "b" in index.matching_ids(self._people()[0])

    def test_unrelated_records_match_nothing(self):
        people = self._people()
        assert ProbableDuplicateIndex(people).matching_ids(people[4]) == set()


class TestIsTwinPair:
    def _twins(self):
        a = _patient("a", "Ana", "Rivera", "2010-03-04", ssn="892-39-5115")
        b = _patient("b", "Beatriz", "Rivera", "2010-03-04", ssn="601-22-7788")
        for p in (a, b):
            p["telecom"] = [{"system": "phone", "value": "212-555-0101"}]
        return a, b

    def test_same_surname_and_birth_date_with_different_first_names(self):
        a, b = self._twins()
        assert is_twin_pair(a, b)

    def test_a_shared_phone_is_what_the_duplicate_guard_would_have_rejected(self):
        a, b = self._twins()
        assert is_probable_duplicate(a, b)
        assert is_twin_pair(a, b)

    def test_a_shared_address_without_a_shared_phone_is_enough(self):
        a, b = self._twins()
        address = [
            {"line": ["1 Main St"], "city": "NY", "state": "NY", "postalCode": "10001"}
        ]
        for p in (a, b):
            p["telecom"] = []
            p["address"] = [dict(address[0])]
        assert is_twin_pair(a, b)

    def test_sharing_neither_phone_nor_address_is_a_coincidence_not_a_twin(self):
        a, b = self._twins()
        a["telecom"] = [{"system": "phone", "value": "212-555-0101"}]
        b["telecom"] = [{"system": "phone", "value": "212-555-0199"}]
        assert not is_twin_pair(a, b)

    def test_a_first_name_typo_is_not_a_twin(self):
        a = _patient("a", "Katherine", "Smith", "1980-06-15")
        assert not is_twin_pair(a, _patient("b", "Katharine", "Smith", "1980-06-15"))

    def test_a_different_birth_date_or_surname_is_not_a_twin(self):
        a, _ = self._twins()
        assert not is_twin_pair(a, _patient("b", "Beatriz", "Rivera", "2010-03-05"))
        assert not is_twin_pair(a, _patient("b", "Beatriz", "Lopez", "2010-03-04"))

    def test_a_matching_or_near_identical_ssn_is_not_a_twin(self):
        a = _patient("a", "Ana", "Rivera", "2010-03-04", ssn="892-39-5115")
        same = _patient("b", "Beatriz", "Rivera", "2010-03-04", ssn="892-39-5115")
        typo = _patient("c", "Beatriz", "Rivera", "2010-03-04", ssn="892-39-5116")
        assert not is_twin_pair(a, same)
        assert not is_twin_pair(a, typo)

    def test_missing_names_or_dates_are_not_twins(self):
        a, b = self._twins()
        b["name"] = []
        assert not is_twin_pair(a, b)
