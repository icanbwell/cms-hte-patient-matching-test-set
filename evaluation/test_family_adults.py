"""Unit tests for family_adults.py (BAI-1160)."""

from __future__ import annotations

import pytest
from family_adults import (
    add_family_adults,
    find_adult_candidates,
)
from population_sampling import age_of
from population_targets import ONC_AS_OF


def _p(id_: str, family: str, birth_year: int) -> dict:
    return {
        "resourceType": "Patient",
        "id": id_,
        "name": [{"family": family, "given": [f"G{id_}"]}],
        "birthDate": f"{birth_year}-06-15",
        "address": [{"line": [f"{id_} Main St"], "postalCode": "10001"}],
    }


def _age(patient) -> int:
    return age_of(patient, ONC_AS_OF) or 0


def _covered(patients) -> int:
    adults: dict[str, list[int]] = {}
    for p in patients:
        if _age(p) >= 18:
            adults.setdefault(p["name"][0]["family"], []).append(_age(p))
    return sum(
        1
        for p in patients
        if _age(p) < 18
        and any(a - _age(p) >= 18 for a in adults.get(p["name"][0]["family"], []))
    )


def _sample():
    minors = [_p(f"m{i}", f"Fam{i}", 2008) for i in range(10)]  # age 9
    adults = [_p(f"a{i}", f"Other{i}", 1970) for i in range(30)]  # age 47
    return minors + adults


def _shard():
    return [[_p(f"s{i}", f"Fam{i}", 1975) for i in range(10)]]


class TestFindAdultCandidates:
    def test_keeps_adults_of_a_needed_surname_old_enough_to_be_a_parent(self):
        batch = [
            _p("old", "Fam0", 1975),  # age 42, minor age 9 -> gap 33
            _p("young", "Fam0", 2000),  # age 17: not an adult
            _p("near", "Fam0", 1995),  # age 22, gap 13 < 18
            _p("ancient", "Fam0", 1930),  # age 87, gap 78 > 50
            _p("other", "Zzz", 1975),
        ]
        found = find_adult_candidates(
            [batch], {"fam0": [9]}, exclude_ids=set(), per_surname_cap=5, seed=0
        )
        assert [c["id"] for c in found["fam0"]] == ["old"]

    def test_a_candidate_must_be_a_plausible_parent_of_some_uncovered_child(self):
        batch = [
            _p("p42", "Fam0", 1975),  # age 42: gap 33 to the 9-year-old
            _p("p62", "Fam0", 1955),  # age 62: gap 53 to the 9-year-old, 45 to the 17
        ]
        found = find_adult_candidates(
            [batch], {"fam0": [9, 17]}, exclude_ids=set(), per_surname_cap=5, seed=0
        )
        assert {c["id"] for c in found["fam0"]} == {"p42", "p62"}
        found = find_adult_candidates(
            [batch], {"fam0": [9]}, exclude_ids=set(), per_surname_cap=5, seed=0
        )
        assert [c["id"] for c in found["fam0"]] == ["p42"]

    def test_never_returns_an_excluded_id_and_respects_the_cap(self):
        batch = [_p(f"c{i}", "Fam0", 1975) for i in range(10)]
        found = find_adult_candidates(
            [batch],
            {"fam0": [9]},
            exclude_ids={"c0", "c1"},
            per_surname_cap=3,
            seed=0,
        )
        ids = {c["id"] for c in found["fam0"]}
        assert len(ids) == 3 and not ids & {"c0", "c1"}


class TestAddFamilyAdults:
    def test_reaches_the_target_by_adding_real_same_surname_adults(self):
        sample = _sample()
        result = add_family_adults(
            sample, _shard, target_share=1.0, exclude_ids=set(), seed=0
        )
        assert result.n_covered_before == 0
        assert result.n_covered_after == result.n_minors == 10
        assert result.n_added == 10
        assert _covered(result.patients) == 10

    def test_keeps_the_sample_size_and_every_age_band_count(self):
        sample = _sample()
        result = add_family_adults(
            sample, _shard, target_share=1.0, exclude_ids=set(), seed=0
        )

        def bands(patients):
            return sorted(
                "minor" if _age(p) < 18 else ("65+" if _age(p) >= 65 else "adult")
                for p in patients
            )

        assert len(result.patients) == len(sample)
        assert bands(result.patients) == bands(sample)

    def test_does_nothing_when_the_target_is_already_met(self):
        sample = _sample() + [_p("mom", "Fam0", 1970)]
        result = add_family_adults(
            sample, _shard, target_share=0.1, exclude_ids=set(), seed=0
        )
        assert result.n_added == 0
        assert result.patients == sample

    def test_never_removes_a_child_or_a_same_surname_adult(self):
        sample = _sample() + [_p("mom", "Fam3", 1970)]
        result = add_family_adults(
            sample, _shard, target_share=1.0, exclude_ids=set(), seed=0
        )
        ids = {p["id"] for p in result.patients}
        assert {f"m{i}" for i in range(10)} <= ids
        assert "mom" in ids

    def test_never_swaps_out_an_adult_who_already_covers_a_child(self):
        # Two children are already covered by their own mothers; four are not and
        # only one other adult can be swapped out, so at most one is added. The
        # first version protected only adults sharing a surname with an UNcovered
        # child, so a covering mother could be the one swapped out.
        minors = [_p(f"m{i}", f"Fam{i}", 2008) for i in range(6)]  # age 9
        moms = [_p(f"mom{i}", f"Fam{i}", 1975) for i in range(2)]  # covers m0, m1
        spare = [_p("spare", "Other", 1975)]
        shard = [[_p(f"s{i}", f"Fam{i}", 1975) for i in range(2, 6)]]
        result = add_family_adults(
            minors + moms + spare,
            lambda: shard,
            target_share=1.0,
            exclude_ids=set(),
            seed=0,
        )
        ids = {p["id"] for p in result.patients}
        assert {"mom0", "mom1"} <= ids
        assert "spare" not in ids
        assert result.n_added == 1
        assert _covered(result.patients) == 3

    def test_an_added_adult_must_have_an_address_a_child_can_share(self):
        shard = [[_p(f"s{i}", f"Fam{i}", 1975) for i in range(10)]]
        for batch in shard:
            for adult in batch:
                del adult["address"]
        result = add_family_adults(
            _sample(), lambda: shard, target_share=1.0, exclude_ids=set(), seed=0
        )
        assert result.n_added == 0

    def test_a_same_surname_adult_without_an_address_does_not_cover_a_child(self):
        sample = _sample() + [_p("mom", "Fam3", 1970)]
        del sample[-1]["address"]
        result = add_family_adults(
            sample, _shard, target_share=0.1, exclude_ids=set(), seed=0
        )
        assert result.n_covered_before == 0
        assert result.n_added == 1

    def test_adults_too_much_older_than_the_child_are_never_added(self):
        shard = [[_p(f"s{i}", f"Fam{i}", 1930) for i in range(10)]]  # age 87
        result = add_family_adults(
            _sample(), lambda: shard, target_share=1.0, exclude_ids=set(), seed=0
        )
        assert result.n_added == 0
        assert result.n_covered_after == result.n_covered_before == 0
        assert result.patients == _sample() or len(result.patients) == 40

    def test_every_added_parent_is_18_to_50_years_older_than_the_child(self):
        shard = [
            [_p(f"y{i}", f"Fam{i}", 1995) for i in range(10)]  # age 22: gap 13 < 18
            + [_p(f"o{i}", f"Fam{i}", 1950) for i in range(10)]  # age 67: gap 58 > 50
            + [_p(f"g{i}", f"Fam{i}", 1970) for i in range(10)]  # age 47: gap 38
        ]
        result = add_family_adults(
            _sample(), lambda: shard, target_share=1.0, exclude_ids=set(), seed=0
        )
        assert result.n_added == 10
        assert set(result.added_parent_age_gaps) == {38}
        assert {p["id"][0] for p in result.patients if p["id"][0] in "yog"} == {"g"}

    def test_added_adults_are_not_duplicated_or_taken_from_the_exclusions(self):
        result = add_family_adults(
            _sample(), _shard, target_share=1.0, exclude_ids={"s0"}, seed=0
        )
        ids = [p["id"] for p in result.patients]
        assert len(ids) == len(set(ids))
        assert "s0" not in ids

    def test_is_deterministic_and_does_not_mutate_the_input(self):
        sample = _sample()
        before = [dict(p) for p in sample]
        a = add_family_adults(
            sample, _shard, target_share=0.5, exclude_ids=set(), seed=1
        )
        b = add_family_adults(
            sample, _shard, target_share=0.5, exclude_ids=set(), seed=1
        )
        assert [p["id"] for p in a.patients] == [p["id"] for p in b.patients]
        assert sample == before

    def test_a_target_outside_zero_to_one_is_rejected(self):
        with pytest.raises(ValueError):
            add_family_adults(
                _sample(), _shard, target_share=1.5, exclude_ids=set(), seed=0
            )
