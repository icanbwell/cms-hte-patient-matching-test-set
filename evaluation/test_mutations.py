"""Unit tests for mutations.py (session 9).

No numpy dependency here (unlike test_rule_eval.py/test_onc_baseline.py) -
mutations.py only uses stdlib random/datetime plus `nicknames`, which is a
core patient_matching dependency, so these tests always run.
"""

from __future__ import annotations

import random
from datetime import date

import pytest
from mutations import (
    DOB_ERROR_TYPES,
    MUTATIONS,
    abbreviate,
    drop_letters,
    generate_fuzzy_variant,
    mutate_dob,
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
