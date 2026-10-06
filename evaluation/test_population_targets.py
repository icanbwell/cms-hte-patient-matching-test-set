"""Unit tests for population_targets.py (session 15, Workstream C)."""

from __future__ import annotations

from itertools import pairwise

import pytest
from population_targets import (
    AGE_BAND_TARGETS,
    AGE_BANDS,
    AS_OF,
    MEAN_HOUSEHOLD_SIZE,
    SINGLE_PERSON_HOUSEHOLD_SHARE,
    age_band_targets,
)


class TestAgeBandTargets:
    def test_shares_sum_to_one(self):
        assert sum(age_band_targets().values()) == pytest.approx(1.0)

    def test_every_band_has_a_target_and_a_source(self):
        assert list(age_band_targets()) == [name for name, _, _ in AGE_BANDS]
        assert all(t.source for t in AGE_BAND_TARGETS.values())

    def test_bands_are_contiguous_and_cover_all_ages(self):
        assert AGE_BANDS[0][1] == 0
        for (_, _, hi), (_, lo, _) in pairwise(AGE_BANDS):
            assert hi == lo
        assert AGE_BANDS[-1][2] > 120

    def test_cited_tail_bands(self):
        targets = age_band_targets()
        assert targets["0-17"] == 0.215
        assert targets["85+"] == pytest.approx(0.0195)
        assert targets["65-84"] + targets["85+"] == pytest.approx(0.173)

    def test_as_of_is_a_fixed_date(self):
        assert (AS_OF.year, AS_OF.month, AS_OF.day) == (2017, 1, 1)


class TestHouseholdTargets:
    def test_cited_household_figures(self):
        assert SINGLE_PERSON_HOUSEHOLD_SHARE.value == 0.29
        assert MEAN_HOUSEHOLD_SIZE.value == 2.5
        assert SINGLE_PERSON_HOUSEHOLD_SHARE.source and MEAN_HOUSEHOLD_SIZE.source
