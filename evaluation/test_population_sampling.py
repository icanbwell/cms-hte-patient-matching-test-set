"""Unit tests for population_sampling.py (session 15, Workstream C)."""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any, Dict, Iterator, List

import pytest
from population_sampling import (
    age_of,
    band_of,
    band_quotas,
    stratified_sample,
)

AS_OF = date(2026, 1, 1)
TARGETS = {"0-17": 0.25, "18-64": 0.5, "65-84": 0.15, "85+": 0.1}
# birth year -> band at AS_OF.year 2026
YEAR_FOR_BAND = {"0-17": 2015, "18-64": 1980, "65-84": 1950, "85+": 1930}


def _patient(id_: str, band: str) -> Dict[str, Any]:
    return {"id": id_, "birthDate": f"{YEAR_FOR_BAND[band]}-06-15"}


def _population(per_band: int = 60) -> List[Dict[str, Any]]:
    return [
        _patient(f"{band}-{i}", band) for band in YEAR_FOR_BAND for i in range(per_band)
    ]


def _batches(
    patients: List[Dict[str, Any]], size: int = 50
) -> Iterator[List[Dict[str, Any]]]:
    for start in range(0, len(patients), size):
        yield patients[start : start + size]


def _band_counts(patients) -> Counter:
    return Counter(band_of(age_of(p, AS_OF)) for p in patients)


class TestAgeAndBand:
    def test_age_is_the_year_difference_as_of(self):
        assert age_of({"birthDate": "2008-12-31"}, AS_OF) == 18

    @pytest.mark.parametrize("bad", [{}, {"birthDate": ""}, {"birthDate": "unknown"}])
    def test_none_without_a_usable_birth_date(self, bad):
        assert age_of(bad, AS_OF) is None

    @pytest.mark.parametrize(
        "age,band",
        [
            (0, "0-17"),
            (17, "0-17"),
            (18, "18-64"),
            (64, "18-64"),
            (65, "65-84"),
            (84, "65-84"),
            (85, "85+"),
            (110, "85+"),
            (None, None),
            (-1, None),
        ],
    )
    def test_band_boundaries(self, age, band):
        assert band_of(age) == band


class TestBandQuotas:
    @pytest.mark.parametrize("n", [0, 1, 7, 100, 2000, 2001])
    def test_quotas_sum_to_exactly_n(self, n):
        assert sum(band_quotas(n, TARGETS).values()) == n

    def test_exact_when_shares_divide_evenly(self):
        assert band_quotas(100, TARGETS) == {
            "0-17": 25,
            "18-64": 50,
            "65-84": 15,
            "85+": 10,
        }

    def test_negative_n_is_rejected(self):
        with pytest.raises(ValueError):
            band_quotas(-1, TARGETS)


class TestStratifiedSample:
    def test_band_counts_match_the_quotas_exactly(self):
        result = stratified_sample(
            _batches(_population()), 100, targets=TARGETS, as_of=AS_OF
        )
        assert len(result.patients) == 100
        assert _band_counts(result.patients) == {
            "0-17": 25,
            "18-64": 50,
            "65-84": 15,
            "85+": 10,
        }

    def test_donors_are_disjoint_and_follow_the_same_bands(self):
        result = stratified_sample(
            _batches(_population(80)), 100, donor_n=40, targets=TARGETS, as_of=AS_OF
        )
        assert len(result.donors) == 40
        assert not {p["id"] for p in result.patients} & {p["id"] for p in result.donors}
        assert _band_counts(result.donors) == {
            "0-17": 10,
            "18-64": 20,
            "65-84": 6,
            "85+": 4,
        }

    def test_deterministic_for_a_seed_and_different_across_seeds(self):
        def ids(seed):
            r = stratified_sample(
                _batches(_population()), 100, seed=seed, targets=TARGETS, as_of=AS_OF
            )
            return [p["id"] for p in r.patients]

        assert ids(1) == ids(1)
        assert ids(1) != ids(2)

    def test_batch_size_does_not_change_the_supply_count(self):
        population = _population()
        a = stratified_sample(_batches(population, 7), 50, targets=TARGETS, as_of=AS_OF)
        b = stratified_sample(
            _batches(population, 500), 50, targets=TARGETS, as_of=AS_OF
        )
        assert a.supply == b.supply == {band: 60 for band in YEAR_FOR_BAND}

    def test_sampling_spans_batches_not_just_the_first_rows(self):
        result = stratified_sample(
            _batches(_population(), 20), 100, targets=TARGETS, as_of=AS_OF
        )
        assert any(int(p["id"].split("-")[1]) >= 40 for p in result.patients)

    def test_patients_without_a_birth_date_are_never_sampled(self):
        population = _population() + [
            {"id": "nodob"},
            {"id": "bad", "birthDate": "unknown"},
        ]
        result = stratified_sample(
            _batches(population), 100, targets=TARGETS, as_of=AS_OF
        )
        assert {"nodob", "bad"}.isdisjoint(p["id"] for p in result.patients)

    def test_a_short_band_raises_and_names_the_band_and_supply(self):
        population = [p for p in _population() if not p["id"].startswith("85+")][:200]
        population += [_patient(f"85+-{i}", "85+") for i in range(3)]
        with pytest.raises(ValueError, match=r"85\+.*need 10.*supplies 3"):
            stratified_sample(_batches(population), 100, targets=TARGETS, as_of=AS_OF)

    def test_inputs_are_not_mutated(self):
        population = _population()
        snapshot = [dict(p) for p in population]
        stratified_sample(_batches(population), 50, targets=TARGETS, as_of=AS_OF)
        assert population == snapshot

    def test_empty_input_with_zero_n_returns_empty(self):
        result = stratified_sample(iter(()), 0, targets=TARGETS, as_of=AS_OF)
        assert result.patients == [] and result.donors == []
