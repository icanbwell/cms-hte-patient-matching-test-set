"""Unit tests for placeholders.py (session 15)."""

from __future__ import annotations

import random
from typing import Any, Dict

import pytest
from identity_guard import SSN_SYSTEM, is_possible_same_person
from placeholders import (
    CATALOG,
    COLLISION_FIELDS,
    POSITIVE_FIELDS,
    apply_placeholder,
    construct_placeholder_collision_negatives,
    placeholder_variant,
)


def _patient(
    id_: str,
    family: str = "Smith",
    given: str = "Katherine",
    ssn: str | None = "892-39-5115",
    phone: str | None = "347-984-6839",
    dob: str | None = "1980-06-15",
) -> Dict[str, Any]:
    patient: Dict[str, Any] = {
        "resourceType": "Patient",
        "id": id_,
        "name": [{"family": family, "given": [given, "Ann"]}],
        "telecom": [{"system": "phone", "value": phone}] if phone else [],
        "address": [
            {"line": ["1 Main St"], "city": "NY", "state": "NY", "postalCode": "10001"}
        ],
        "identifier": [{"system": SSN_SYSTEM, "value": ssn}] if ssn else [],
    }
    if dob:
        patient["birthDate"] = dob
    return patient


class TestApplyPlaceholder:
    @pytest.mark.parametrize(
        "field,check",
        [
            ("ssn", lambda p: p["identifier"][0]["value"]),
            ("phone", lambda p: p["telecom"][0]["value"]),
            ("given", lambda p: p["name"][0]["given"][0]),
            ("address", lambda p: p["address"][0]["line"][0]),
            ("dob", lambda p: p["birthDate"]),
        ],
    )
    def test_sets_the_named_field_without_touching_the_input(self, field, check):
        original = _patient("p1")
        result = apply_placeholder(original, field, "PLACEHOLDER")
        assert check(result) == "PLACEHOLDER"
        assert check(original) != "PLACEHOLDER"

    def test_given_keeps_the_other_given_names(self):
        result = apply_placeholder(_patient("p1"), "given", "UNKNOWN")
        assert result["name"][0]["given"] == ["UNKNOWN", "Ann"]

    def test_missing_field_is_left_unchanged_unless_creating(self):
        bare = _patient("p1", ssn=None, phone=None, dob=None)
        for field in ("ssn", "phone", "dob"):
            assert apply_placeholder(bare, field, "X") == bare
        created = apply_placeholder(bare, "ssn", "999-99-9999", create_missing=True)
        assert created["identifier"][0]["value"] == "999-99-9999"

    def test_bare_patient_is_returned_unchanged_for_every_field(self):
        bare = {"resourceType": "Patient", "id": "x"}
        for field in CATALOG:
            assert apply_placeholder(bare, field, "X") == bare

    def test_unknown_field_raises(self):
        with pytest.raises(ValueError):
            apply_placeholder(_patient("p1"), "shoe_size", "X")


class TestPlaceholderVariant:
    def test_never_uses_a_dob_placeholder(self):
        assert "dob" not in POSITIVE_FIELDS
        for seed in range(30):
            result = placeholder_variant(_patient("p1"), rng=random.Random(seed))
            assert result is not None
            variant, field = result
            assert field in POSITIVE_FIELDS
            assert variant["birthDate"] == "1980-06-15"

    def test_changes_exactly_one_field_to_a_catalog_value(self):
        variant, field = placeholder_variant(_patient("p1"), rng=random.Random(0))
        assert variant != _patient("p1")
        values = {
            "ssn": variant["identifier"][0]["value"],
            "phone": variant["telecom"][0]["value"],
            "given": variant["name"][0]["given"][0],
            "address": variant["address"][0]["line"][0],
        }
        assert values[field] in CATALOG[field]

    def test_only_offers_fields_the_patient_has(self):
        only_phone = _patient("p1", ssn=None)
        only_phone["address"] = []
        only_phone["name"] = [{"family": "Smith"}]
        for seed in range(20):
            _, field = placeholder_variant(only_phone, rng=random.Random(seed))
            assert field == "phone"

    def test_none_when_nothing_applies(self):
        bare = {"resourceType": "Patient", "id": "x"}
        assert placeholder_variant(bare, rng=random.Random(0)) is None

    def test_deterministic_for_a_seed(self):
        a = placeholder_variant(_patient("p1"), rng=random.Random(5))
        b = placeholder_variant(_patient("p1"), rng=random.Random(5))
        assert a == b


class TestPlaceholderCollisions:
    def _people(self):
        return [
            _patient("a", family="Smith", given="Ana", ssn="111-22-3333"),
            _patient("b", family="Jones", given="Luis", ssn="444-55-6666"),
            _patient("c", family="Lee", given="Mei", ssn="777-88-9999"),
            _patient("d", family="Okafor", given="Chidi", ssn="222-33-4444"),
        ]

    @pytest.mark.parametrize("field", COLLISION_FIELDS)
    def test_both_sides_carry_the_same_placeholder(self, field):
        pairs = construct_placeholder_collision_negatives(
            self._people(), field, rng=random.Random(0)
        )
        assert len(pairs) == 2
        for pair in pairs:
            value = pair.shared_fields["placeholder_value"]
            assert value in CATALOG[field]
            assert pair.shared_fields["case"] == field
            got = {
                "ssn": lambda p: p["identifier"][0]["value"],
                "phone": lambda p: p["telecom"][0]["value"],
                "dob": lambda p: p["birthDate"],
            }[field]
            assert got(pair.query) == got(pair.candidate) == value

    def test_pairs_are_distinct_people_and_each_patient_used_once(self):
        pairs = construct_placeholder_collision_negatives(
            self._people(), "ssn", rng=random.Random(0)
        )
        ids = [p.query["id"] for p in pairs] + [p.candidate["id"] for p in pairs]
        assert len(ids) == len(set(ids))
        for pair in pairs:
            assert not is_possible_same_person(pair.query, pair.candidate)
            assert (
                pair.query["name"][0]["family"] != pair.candidate["name"][0]["family"]
            )

    def test_never_pairs_two_people_with_the_same_family_name(self):
        people = [_patient("a"), _patient("b", given="Ana")]
        assert (
            construct_placeholder_collision_negatives(
                people, "ssn", rng=random.Random(0)
            )
            == []
        )

    def test_does_not_mutate_inputs_and_respects_max_pairs(self):
        people = self._people()
        snapshot = [dict(p) for p in people]
        pairs = construct_placeholder_collision_negatives(
            people, "phone", max_pairs=1, rng=random.Random(0)
        )
        assert len(pairs) == 1
        assert people == snapshot
        assert (
            construct_placeholder_collision_negatives(
                people, "phone", max_pairs=0, rng=random.Random(0)
            )
            == []
        )

    def test_rejects_a_field_that_is_not_a_collision_field(self):
        with pytest.raises(ValueError):
            construct_placeholder_collision_negatives(
                self._people(), "given", rng=random.Random(0)
            )
