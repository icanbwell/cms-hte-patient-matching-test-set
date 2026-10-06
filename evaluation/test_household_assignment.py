"""Unit tests for household_assignment.py (session 15, Workstream C)."""

from __future__ import annotations

import copy
import random
from collections import Counter
from datetime import date
from typing import Any, Dict, List

import pytest
from drift_profile import DriftProfile
from household_assignment import (
    _multi_person_weights,
    assign_households,
    household_sizes,
    shared_contact_case,
)
from identity_guard import SSN_SYSTEM, ssn_of
from population_sampling import age_of

AS_OF = date(2026, 1, 1)
FAMILIES = ["Smith", "Jones", "Lee", "Okafor", "Garcia", "Chen", "Ito", "Moreau"]


def _person(i: int, birth_year: int, family: str | None = None) -> Dict[str, Any]:
    return {
        "resourceType": "Patient",
        "id": f"p{i}",
        "name": [{"family": family or f"Fam{i}", "given": [f"Given{i}"]}],
        "gender": "female",
        "birthDate": f"{birth_year}-06-15",
        "telecom": [
            {"system": "phone", "value": f"347-555-{i:04d}"},
            {"system": "email", "value": f"p{i}@example.com"},
        ],
        "address": [
            {
                "line": [f"{i} Main St"],
                "city": "NY",
                "state": "NY",
                "postalCode": "10001",
            }
        ],
        "identifier": [{"system": SSN_SYSTEM, "value": f"900-00-{i:04d}"}],
    }


def _population(n_adults: int = 300, n_minors: int = 100) -> List[Dict[str, Any]]:
    adults = [_person(i, 1960 + i % 40) for i in range(n_adults)]
    minors = [_person(n_adults + i, 2010 + i % 15) for i in range(n_minors)]
    return adults + minors


def _by_id(patients):
    return {p["id"]: p for p in patients}


def _street(p):
    return p["address"][0]["line"][0]


class TestHouseholdSizes:
    def test_sizes_sum_to_the_population_and_are_in_range(self):
        sizes = household_sizes(
            1000, single_share=0.29, mean_size=2.5, rng=random.Random(0)
        )
        assert sum(sizes) == 1000
        assert min(sizes) >= 1 and max(sizes) <= 6

    def test_one_person_share_and_mean_track_the_targets(self):
        sizes = household_sizes(
            40000, single_share=0.29, mean_size=2.5, rng=random.Random(1)
        )
        assert sum(s == 1 for s in sizes) / len(sizes) == pytest.approx(0.29, abs=0.02)
        assert sum(sizes) / len(sizes) == pytest.approx(2.5, abs=0.05)

    def test_multi_person_weights_hit_the_requested_mean(self):
        weights = _multi_person_weights(3.1)
        assert sum(weights) == pytest.approx(1.0)
        assert sum(s * w for s, w in zip(range(2, 7), weights)) == pytest.approx(
            3.1, abs=1e-6
        )

    @pytest.mark.parametrize("mean_size", [0.9, 1.0, 6.5])
    def test_an_impossible_mean_is_rejected(self, mean_size):
        with pytest.raises(ValueError):
            household_sizes(
                100, single_share=0.29, mean_size=mean_size, rng=random.Random(0)
            )

    def test_zero_patients_gives_no_households(self):
        assert (
            household_sizes(0, single_share=0.29, mean_size=2.5, rng=random.Random(0))
            == []
        )


class TestAssignHouseholds:
    def test_every_patient_lands_in_exactly_one_household(self):
        result = assign_households(_population(), seed=0, as_of=AS_OF)
        placed = [pid for household in result.households for pid in household]
        assert sorted(placed) == sorted(p["id"] for p in result.patients)

    def test_members_share_the_anchors_address_and_patients_per_address_hits_the_target(
        self,
    ):
        result = assign_households(_population(), seed=0, as_of=AS_OF)
        people = _by_id(result.patients)
        for household in result.households:
            assert len({_street(people[pid]) for pid in household}) == 1
        streets = Counter(_street(p) for p in result.patients)
        assert len(result.patients) / len(streets) == pytest.approx(2.5, abs=0.25)

    def test_every_household_with_a_minor_also_has_an_adult(self):
        result = assign_households(_population(), seed=0, as_of=AS_OF)
        people = _by_id(result.patients)
        for household in result.households:
            ages = [age_of(people[pid], AS_OF) or 0 for pid in household]
            assert max(ages) >= 18

    def test_children_under_13_take_the_anchor_adults_phone_and_email(self):
        result = assign_households(_population(), seed=0, as_of=AS_OF)
        people = _by_id(result.patients)
        checked = 0
        for household in result.households:
            anchor = people[household[0]]
            for pid in household[1:]:
                if (age_of(people[pid], AS_OF) or 99) < 13:
                    child = people[pid]
                    assert child["telecom"] == anchor["telecom"]
                    checked += 1
        assert checked > 0

    @staticmethod
    def _contactless_adults(keep_phone: bool = False, keep_email: bool = False):
        people = _population()
        for person in people:
            if (age_of(person, AS_OF) or 0) >= 18:
                person["telecom"] = [
                    t
                    for t in person["telecom"]
                    if (t["system"] == "phone" and keep_phone)
                    or (t["system"] == "email" and keep_email)
                ]
        return people

    @staticmethod
    def _members(result, predicate):
        people = _by_id(result.patients)
        for household in result.households:
            anchor = people[household[0]]
            for pid in household[1:]:
                if predicate(age_of(people[pid], AS_OF) or 99):
                    yield anchor, people[pid]

    def test_children_under_13_have_no_contacts_when_the_anchor_has_none(self):
        result = assign_households(self._contactless_adults(), seed=0, as_of=AS_OF)
        pairs = list(self._members(result, lambda a: a < 13))
        assert pairs
        for _, child in pairs:
            assert child["telecom"] == []

    def test_children_under_13_take_the_anchors_phone_and_drop_their_own_email(self):
        result = assign_households(
            self._contactless_adults(keep_phone=True), seed=0, as_of=AS_OF
        )
        pairs = list(self._members(result, lambda a: a < 13))
        assert pairs
        for anchor, child in pairs:
            assert child["telecom"] == anchor["telecom"]
            assert not [t for t in child["telecom"] if t["system"] == "email"]

    def test_members_aged_13_and_over_keep_their_contacts_when_the_anchor_has_none(
        self,
    ):
        population = self._contactless_adults()
        before = _by_id(population)
        result = assign_households(
            population,
            profile=DriftProfile(
                rates={
                    **DriftProfile().rates,
                    "household_shared_phone": 1.0,
                    "household_shared_email": 1.0,
                }
            ),
            seed=0,
            as_of=AS_OF,
        )
        pairs = list(self._members(result, lambda a: a >= 13))
        assert pairs
        for _, member in pairs:
            assert member["telecom"] == before[member["id"]]["telecom"]

    def test_identities_are_never_changed(self):
        original = _population()
        result = assign_households(original, seed=0, as_of=AS_OF)
        for before, after in zip(original, result.patients):
            for key in ("id", "name", "birthDate", "gender", "resourceType"):
                assert before[key] == after[key]

    def test_only_children_under_13_lose_their_ssn(self):
        profile = DriftProfile(rates={"minor_ssn_absent": 1.0})
        original = _population()
        result = assign_households(original, profile=profile, seed=0, as_of=AS_OF)
        for before, after in zip(original, result.patients):
            age = age_of(before, AS_OF) or 0
            if age < 13:
                assert ssn_of(after) is None
            else:
                assert ssn_of(after) == ssn_of(before)

    def test_zero_rates_share_no_contacts_beyond_the_children_under_13(self):
        profile = DriftProfile(
            rates={
                "household_shared_phone": 0.0,
                "household_shared_email": 0.0,
                "minor_ssn_absent": 0.0,
            }
        )
        result = assign_households(_population(), profile=profile, seed=0, as_of=AS_OF)
        people = _by_id(result.patients)
        for household in result.households:
            anchor = people[household[0]]
            for pid in household[1:]:
                if (age_of(people[pid], AS_OF) or 99) >= 13:
                    assert people[pid]["telecom"] != anchor["telecom"]

    def test_full_rates_share_the_anchors_phone_with_every_member(self):
        profile = DriftProfile(
            rates={"household_shared_phone": 1.0, "household_shared_email": 1.0}
        )
        result = assign_households(_population(), profile=profile, seed=0, as_of=AS_OF)
        people = _by_id(result.patients)
        for household in result.households:
            anchor_phone = [
                t for t in people[household[0]]["telecom"] if t["system"] == "phone"
            ]
            for pid in household[1:]:
                assert [
                    t for t in people[pid]["telecom"] if t["system"] == "phone"
                ] == anchor_phone

    def test_prefers_a_same_surname_parent_for_a_child(self):
        adults = [_person(i, 1960, FAMILIES[i % 8]) for i in range(40)]
        minors = [_person(100 + i, 2015, FAMILIES[i % 8]) for i in range(16)]
        result = assign_households(adults + minors, seed=0, as_of=AS_OF)
        assert result.report.n_same_surname_minors > 0
        people = _by_id(result.patients)
        for household in result.households:
            anchor_family = people[household[0]]["name"][0]["family"]
            for pid in household[1:]:
                if (
                    int(pid[1:]) >= 100
                    and people[pid]["name"][0]["family"] == anchor_family
                ):
                    assert (age_of(people[household[0]], AS_OF) or 0) - (
                        age_of(people[pid], AS_OF) or 0
                    ) >= 18

    def test_deterministic_for_a_seed_and_not_mutating_the_input(self):
        original = _population()
        snapshot = copy.deepcopy(original)
        a = assign_households(original, seed=3, as_of=AS_OF)
        b = assign_households(original, seed=3, as_of=AS_OF)
        assert a.households == b.households and a.patients == b.patients
        assert original == snapshot
        assert (
            assign_households(original, seed=4, as_of=AS_OF).households != a.households
        )

    def test_too_many_minors_for_the_households_is_rejected(self):
        with pytest.raises(ValueError, match="cannot house"):
            assign_households(
                _population(n_adults=5, n_minors=100), seed=0, as_of=AS_OF
            )

    def test_patients_without_address_or_contacts_do_not_raise(self):
        bare = [
            {"resourceType": "Patient", "id": f"b{i}", "birthDate": "1980-01-01"}
            for i in range(50)
        ]
        result = assign_households(bare, seed=0, as_of=AS_OF)
        assert len(result.patients) == 50

    def test_report_counts(self):
        result = assign_households(_population(), seed=0, as_of=AS_OF)
        assert result.report.n_households == len(result.households)
        assert result.report.n_minors == 100
        assert result.report.mean_size == pytest.approx(
            400 / result.report.n_households
        )


class TestSharedContactCase:
    def test_a_common_phone_or_email_is_shared_contact(self):
        a, b = _person(1, 1980), _person(2, 1982)
        b["telecom"] = [{"system": "phone", "value": "(347) 555-0001"}]
        assert shared_contact_case(a, b) == "shared_contact"
        c = _person(3, 1982)
        c["telecom"] = [{"system": "email", "value": "P1@EXAMPLE.COM "}]
        assert shared_contact_case(a, c) == "shared_contact"

    def test_otherwise_it_is_same_address(self):
        assert shared_contact_case(_person(1, 1980), _person(2, 1982)) == "same_address"

    def test_records_without_contacts_are_same_address(self):
        bare = {"resourceType": "Patient", "id": "x"}
        assert shared_contact_case(bare, dict(bare, id="y")) == "same_address"
