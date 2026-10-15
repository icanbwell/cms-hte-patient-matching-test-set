"""Unit tests for dob_shift.py (BAI-1161)."""

from __future__ import annotations

import pytest
from dob_shift import shift_birth_date, shift_birth_date_value
from population_sampling import age_of
from population_targets import AS_OF, DOB_SHIFT_YEARS, ONC_AS_OF


class TestShiftBirthDateValue:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("1980-06-15", "1989-06-15"),
            ("2016-12-31", "2025-12-31"),
            ("1950-01-01", "1959-01-01"),
        ],
    )
    def test_moves_the_year_and_keeps_month_and_day(self, value, expected):
        assert shift_birth_date_value(value, 9) == expected

    def test_a_leap_day_moves_to_28_february_in_a_non_leap_year(self):
        assert shift_birth_date_value("2016-02-29", 9) == "2025-02-28"

    def test_a_leap_day_stays_when_the_target_year_is_a_leap_year(self):
        assert shift_birth_date_value("2016-02-29", 8) == "2024-02-29"

    @pytest.mark.parametrize("value", ["", "1980", "1980/06/15", "abcd-ef-gh"])
    def test_anything_that_is_not_an_iso_date_is_unchanged(self, value):
        assert shift_birth_date_value(value, 9) == value


class TestShiftBirthDate:
    def test_returns_a_copy_and_leaves_the_input_alone(self):
        patient = {"id": "p", "birthDate": "1980-06-15", "name": [{"family": "X"}]}
        shifted = shift_birth_date(patient, 9)
        assert shifted["birthDate"] == "1989-06-15"
        assert patient["birthDate"] == "1980-06-15"
        assert shifted["id"] == "p" and shifted["name"] == patient["name"]

    def test_a_patient_without_a_birth_date_is_returned_as_is(self):
        patient = {"id": "p"}
        assert shift_birth_date(patient, 9) is patient


def test_shifting_by_the_vintage_gap_keeps_every_age():
    assert DOB_SHIFT_YEARS == AS_OF.year - ONC_AS_OF.year
    for year in (1920, 1950, 1999, 2016):
        original = {"birthDate": f"{year}-03-04"}
        shifted = shift_birth_date(original, DOB_SHIFT_YEARS)
        assert age_of(original, ONC_AS_OF) == age_of(shifted, AS_OF)


def test_onc_youngest_records_become_infants_at_the_release_vintage():
    youngest = shift_birth_date({"birthDate": "2016-07-01"}, DOB_SHIFT_YEARS)
    assert age_of(youngest, AS_OF) == 1
