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
    count_changed_fields,
    dob_swap_applicable,
    drop_letters,
    generate_compound_variant,
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


class TestDobSwapApplicable:
    @pytest.mark.parametrize(
        "birth_date,expected",
        [
            ("2000-03-07", True),  # day 7 <= 12 and != month 3
            ("2000-03-12", True),  # boundary: day 12 is still a valid month
            ("2000-03-13", False),  # day 13 cannot be a month
            ("1990-06-20", False),
            ("2000-07-07", False),  # day == month: swap changes nothing
            ("2000-12-12", False),
        ],
    )
    def test_boundaries(self, birth_date: str, expected: bool) -> None:
        assert dob_swap_applicable(_patient(birthDate=birth_date)) is expected

    def test_missing_birth_date_is_not_applicable(self) -> None:
        patient = _patient()
        del patient["birthDate"]
        assert dob_swap_applicable(patient) is False


class TestRandomFuzzyVariantNeverEmitsNoopSwap:
    """A pair labeled `dob_swap` must actually transpose the date."""

    @pytest.mark.parametrize("birth_date", ["1990-06-20", "2000-07-07", "1975-11-28"])
    def test_ineligible_patient_never_gets_a_dob_swap_label(
        self, birth_date: str
    ) -> None:
        patient = _patient(birthDate=birth_date)
        for seed in range(300):
            _, mutation_type = generate_fuzzy_variant(patient, rng=random.Random(seed))
            assert mutation_type != "dob_swap", f"seed {seed}"

    def test_eligible_patient_still_gets_real_swaps(self) -> None:
        patient = _patient(birthDate="2000-03-07")
        swaps = []
        for seed in range(300):
            variant, mutation_type = generate_fuzzy_variant(
                patient, rng=random.Random(seed)
            )
            if mutation_type == "dob_swap":
                swaps.append(variant["birthDate"])
        assert swaps, "dob_swap was never drawn for an eligible patient"
        assert set(swaps) == {"2000-07-03"}

    def test_explicit_dob_swap_request_is_still_honoured_as_a_noop(self) -> None:
        """Only the random draw is gated; an explicit request keeps its contract."""
        patient = _patient(birthDate="1990-06-20")
        variant, mutation_type = generate_fuzzy_variant(
            patient, "dob_swap", rng=random.Random(0)
        )
        assert mutation_type == "dob_swap"
        assert variant["birthDate"] == "1990-06-20"


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

    def test_collapses_to_a_single_name_entry_not_a_duplicated_surname(self) -> None:
        # Keeping both entries after overwriting name[0] with name[1]'s family
        # would leave the variant with the same surname twice ("Jones", "Jones")
        # - a shape no real record has, and one that leaks the maiden surname
        # onto both sides of the pair via name[1] as well as name[0].
        patient = _patient(
            name=[
                {"family": "Smith", "given": ["Katherine"]},
                {"family": "Jones", "given": ["Katherine"]},
            ]
        )
        donor = _patient(id="donor", address=[])
        result = marriage_variant(patient, donor)
        assert result["name"] == [{"family": "Jones", "given": ["Katherine"]}]

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

    def test_identical_second_phone_value_is_a_noop(self) -> None:
        # A real, common ONC data shape: PHONE2 duplicates PHONE verbatim.
        # "Swapping" to an identical value must not be treated as a change -
        # and must not silently shrink the telecom list from 2 entries to 1
        # while claiming nothing changed (that WOULD differ from the
        # original by list length, defeating the wiring's no-op skip).
        patient = _patient(
            telecom=[
                {"system": "phone", "value": "555-000-1111"},
                {"system": "phone", "value": "555-000-1111"},
            ]
        )
        result = phone_variant(patient)
        assert result["telecom"] == patient["telecom"]


class TestGenerateCompoundVariant:
    def test_returns_n_mutations_applied(self) -> None:
        patient = _patient()
        rng = random.Random(0)
        _, mutation_types = generate_compound_variant(patient, n_mutations=3, rng=rng)
        assert len(mutation_types) == 3
        assert all(m in MUTATIONS for m in mutation_types)

    def test_default_n_mutations_is_two(self) -> None:
        patient = _patient()
        _, mutation_types = generate_compound_variant(patient, rng=random.Random(0))
        assert len(mutation_types) == 2

    def test_n_mutations_below_two_raises(self) -> None:
        with pytest.raises(ValueError):
            generate_compound_variant(_patient(), n_mutations=1, rng=random.Random(0))

    def test_does_not_mutate_input_patient(self) -> None:
        patient = _patient()
        original_family = patient["name"][0]["family"]
        generate_compound_variant(patient, n_mutations=3, rng=random.Random(0))
        assert patient["name"][0]["family"] == original_family

    def test_variant_differs_from_original(self) -> None:
        patient = _patient()
        rng = random.Random(0)
        variant, _ = generate_compound_variant(patient, n_mutations=2, rng=rng)
        assert variant != patient

    def test_always_changes_at_least_n_mutations_distinct_fields(self) -> None:
        # A batch of 200 realistic, fully-mutable records (long enough family/
        # given names, a nickname-eligible given name, a present birthDate) -
        # every draw must change >=2 distinct top-level fields, not just make
        # >=2 mutator calls that might no-op or collide on the same field.
        rng = random.Random(0)
        for i in range(200):
            patient = _patient(
                id=f"p{i}",
                name=[{"family": "Montgomery", "given": ["Katherine"]}],
            )
            variant, mutation_types = generate_compound_variant(
                patient, n_mutations=2, rng=rng
            )
            assert count_changed_fields(patient, variant) >= 2, (
                mutation_types,
                patient,
                variant,
            )

    def test_n_mutations_above_field_group_count_raises(self) -> None:
        # Only 3 distinct fields (birthDate/family/given) can ever be composed -
        # asking for more must raise, not silently repeat a field.
        with pytest.raises(ValueError):
            generate_compound_variant(_patient(), n_mutations=4, rng=random.Random(0))


class TestCountChangedFields:
    def test_counts_each_changed_top_level_field_once(self) -> None:
        original = _patient(
            name=[{"family": "Smith", "given": ["Katherine"]}], birthDate="1980-06-15"
        )
        variant = _patient(
            name=[{"family": "Smyth", "given": ["Kate"]}], birthDate="1980-06-16"
        )
        assert count_changed_fields(original, variant) == 3

    def test_identical_patients_count_zero(self) -> None:
        patient = _patient()
        assert count_changed_fields(patient, patient) == 0

    def test_missing_given_name_on_both_sides_does_not_count_as_changed(self) -> None:
        # Empty-string given names on both sides (a common real-ONC shape) must
        # not be counted as "changed" just because a mutator was tried and
        # no-op'd - the field genuinely didn't change.
        original = _patient(name=[{"family": "Smith", "given": [""]}])
        variant = _patient(name=[{"family": "Smyth", "given": [""]}])
        assert count_changed_fields(original, variant) == 1
