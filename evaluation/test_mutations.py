"""Unit tests for mutations.py (session 9).

No numpy dependency here (unlike test_rule_eval.py/test_labeled_pairs.py) -
mutations.py only uses stdlib random/datetime plus `nicknames`, a core
dependency of this repo's own pyproject.toml, so these tests always run.
"""

from __future__ import annotations

import random
from datetime import date

import pytest
from mutations import (
    DOB_ERROR_TYPES,
    MUTATIONS,
    SSN_SYSTEM,
    abbreviate,
    drop_letters,
    generate_fuzzy_variant,
    marriage_variant,
    mutate_dob,
    phone_variant,
    ssn_dropped_variant,
    substitute_nickname,
    transpose_characters,
    typo_edit,
)


def _patient(**overrides):
    base = {
        "resourceType": "Patient",
        "id": "p1",
        "name": [{"family": "Smith", "given": ["Katherine"]}],
        "birthDate": "1980-06-15",
        "telecom": [],
        "address": [],
        "identifier": [],
    }
    base.update(overrides)
    return base


class TestMutateDob:
    @pytest.mark.parametrize("error_type", DOB_ERROR_TYPES)
    def test_changes_birth_date_deterministically(self, error_type: str) -> None:
        rng = random.Random(0)
        patient = _patient()
        result = mutate_dob(patient, error_type, rng=rng)
        # "swap" is a legitimate no-op when day/month can't be transposed, and
        # "typo" is a legitimate no-op when the random digit substitution lands
        # on an invalid calendar date (see mutate_dob's docstring) - every other
        # error_type always changes the date.
        if error_type not in ("swap", "typo"):
            assert result["birthDate"] != patient["birthDate"]
        # Result must still be a valid ISO date either way.
        date.fromisoformat(result["birthDate"])

    def test_does_not_mutate_input_patient(self) -> None:
        patient = _patient()
        original = dict(patient)
        mutate_dob(patient, "day", rng=random.Random(0))
        assert patient["birthDate"] == original["birthDate"]

    def test_missing_birth_date_is_a_noop(self) -> None:
        patient = _patient()
        del patient["birthDate"]
        result = mutate_dob(patient, "day", rng=random.Random(0))
        assert "birthDate" not in result

    def test_unknown_error_type_raises(self) -> None:
        with pytest.raises(ValueError):
            mutate_dob(_patient(), "not_a_real_type", rng=random.Random(0))

    def test_day_mutation_stays_within_plus_minus_three_days(self) -> None:
        rng = random.Random(0)
        for _ in range(50):
            patient = _patient()
            result = mutate_dob(patient, "day", rng=rng)
            delta = (
                date.fromisoformat(result["birthDate"])
                - date.fromisoformat(patient["birthDate"])
            ).days
            assert 1 <= abs(delta) <= 3

    def test_swap_transposes_month_and_day_when_both_valid_as_the_other(self) -> None:
        patient = _patient(birthDate="1980-03-07")
        result = mutate_dob(patient, "swap", rng=random.Random(0))
        assert result["birthDate"] == "1980-07-03"


class TestNameMutations:
    def test_typo_edit_changes_family_name_by_default(self) -> None:
        patient = _patient()
        result = typo_edit(patient, "family", rng=random.Random(1))
        assert result["name"][0]["family"] != "Smith"

    def test_typo_edit_short_name_is_a_noop(self) -> None:
        patient = _patient(name=[{"family": "Li", "given": ["Jo"]}])
        result = typo_edit(patient, "family", rng=random.Random(0))
        assert result["name"][0]["family"] == "Li"

    def test_transpose_characters_swaps_adjacent_pair(self) -> None:
        patient = _patient(name=[{"family": "abcd", "given": ["A"]}])
        result = transpose_characters(patient, "family", rng=random.Random(0))
        family = result["name"][0]["family"]
        assert sorted(family) == sorted("abcd")
        assert family != "abcd"

    def test_drop_letters_reduces_length(self) -> None:
        patient = _patient()
        result = drop_letters(patient, "family", drop_ratio=0.4, rng=random.Random(0))
        assert len(result["name"][0]["family"]) < len("Smith")

    def test_abbreviate_reduces_given_name_to_initial(self) -> None:
        patient = _patient()
        result = abbreviate(patient, "given")
        assert result["name"][0]["given"][0] == "K."

    def test_substitute_nickname_replaces_known_name(self) -> None:
        patient = _patient()  # "Katherine" has well-known nicknames (e.g. "Kate")
        result = substitute_nickname(patient, rng=random.Random(0))
        assert result["name"][0]["given"][0] != "Katherine"

    def test_substitute_nickname_noop_for_unrecognized_name(self) -> None:
        patient = _patient(name=[{"family": "Smith", "given": ["Xyzzyplugh"]}])
        result = substitute_nickname(patient, rng=random.Random(0))
        assert result["name"][0]["given"][0] == "Xyzzyplugh"


class TestGenerateFuzzyVariant:
    def test_random_picks_from_registered_mutations(self) -> None:
        _, mutation_type = generate_fuzzy_variant(_patient(), rng=random.Random(0))
        assert mutation_type in MUTATIONS

    def test_explicit_mutation_type_is_applied(self) -> None:
        variant, mutation_type = generate_fuzzy_variant(
            _patient(), "given_abbreviate", rng=random.Random(0)
        )
        assert mutation_type == "given_abbreviate"
        assert variant["name"][0]["given"][0] == "K."

    def test_unknown_mutation_type_raises(self) -> None:
        with pytest.raises(ValueError):
            generate_fuzzy_variant(_patient(), "not_a_mutation", rng=random.Random(0))


class TestSsnDroppedVariant:
    def test_removes_the_ssn_identifier(self) -> None:
        patient = _patient(identifier=[{"system": SSN_SYSTEM, "value": "123-45-6789"}])
        result = ssn_dropped_variant(patient)
        assert result["identifier"] == []

    def test_leaves_non_ssn_identifiers_untouched(self) -> None:
        other = {"system": "http://example.org/mrn", "value": "M1"}
        patient = _patient(identifier=[{"system": SSN_SYSTEM, "value": "1"}, other])
        result = ssn_dropped_variant(patient)
        assert result["identifier"] == [other]

    def test_missing_ssn_is_a_noop(self) -> None:
        patient = _patient(identifier=[])
        result = ssn_dropped_variant(patient)
        assert result["identifier"] == []

    def test_does_not_mutate_input_patient(self) -> None:
        patient = _patient(identifier=[{"system": SSN_SYSTEM, "value": "1"}])
        ssn_dropped_variant(patient)
        assert patient["identifier"] == [{"system": SSN_SYSTEM, "value": "1"}]


class TestMarriageVariant:
    def test_replaces_family_name_with_mothers_maiden_name(self) -> None:
        patient = _patient(
            name=[
                {"family": "Smith", "given": ["Katherine"]},
                {"family": "Jones", "given": ["Katherine"]},  # maiden-name proxy entry
            ]
        )
        donor = _patient(
            id="donor",
            address=[
                {"line": ["9 Elm St"], "city": "X", "state": "Y", "postalCode": "99999"}
            ],
        )
        result = marriage_variant(patient, donor)
        assert result["name"][0]["family"] == "Jones"

    def test_replaces_address_with_donors_address(self) -> None:
        patient = _patient(
            address=[
                {
                    "line": ["1 Main St"],
                    "city": "A",
                    "state": "B",
                    "postalCode": "11111",
                }
            ]
        )
        donor = _patient(
            id="donor",
            address=[
                {"line": ["9 Elm St"], "city": "X", "state": "Y", "postalCode": "99999"}
            ],
        )
        result = marriage_variant(patient, donor)
        assert result["address"] == donor["address"]

    def test_no_maiden_name_entry_leaves_family_name_unchanged(self) -> None:
        patient = _patient(name=[{"family": "Smith", "given": ["Katherine"]}])
        donor = _patient(id="donor", address=[])
        result = marriage_variant(patient, donor)
        assert result["name"][0]["family"] == "Smith"

    def test_does_not_mutate_input_patient_or_donor(self) -> None:
        patient = _patient(
            name=[
                {"family": "Smith", "given": ["K"]},
                {"family": "Jones", "given": ["K"]},
            ],
            address=[
                {
                    "line": ["1 Main St"],
                    "city": "A",
                    "state": "B",
                    "postalCode": "11111",
                }
            ],
        )
        donor = _patient(
            id="donor",
            address=[
                {"line": ["9 Elm St"], "city": "X", "state": "Y", "postalCode": "99999"}
            ],
        )
        original_patient_address = [dict(a) for a in patient["address"]]
        marriage_variant(patient, donor)
        assert patient["address"] == original_patient_address
        assert patient["name"][0]["family"] == "Smith"


class TestPhoneVariant:
    def test_swaps_to_second_phone_number(self) -> None:
        patient = _patient(
            telecom=[
                {"system": "phone", "value": "555-000-1111"},
                {"system": "phone", "value": "555-222-3333"},
            ]
        )
        result = phone_variant(patient)
        phone_values = [t["value"] for t in result["telecom"] if t["system"] == "phone"]
        assert phone_values == ["555-222-3333"]

    def test_preserves_non_phone_telecom_entries(self) -> None:
        patient = _patient(
            telecom=[
                {"system": "phone", "value": "555-000-1111"},
                {"system": "phone", "value": "555-222-3333"},
                {"system": "email", "value": "jane@example.com"},
            ]
        )
        result = phone_variant(patient)
        assert {"system": "email", "value": "jane@example.com"} in result["telecom"]

    def test_single_phone_number_is_a_noop(self) -> None:
        patient = _patient(telecom=[{"system": "phone", "value": "555-000-1111"}])
        result = phone_variant(patient)
        assert result["telecom"] == patient["telecom"]

    def test_no_phone_number_is_a_noop(self) -> None:
        patient = _patient(telecom=[])
        result = phone_variant(patient)
        assert result["telecom"] == []
