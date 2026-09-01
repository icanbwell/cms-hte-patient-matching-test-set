"""Unit tests for prevalence_estimates.py (session 10, Task 9).

No numpy dependency (session 13 dropped labeled_pairs.py's rule_eval usage
entirely), so these always run.
"""

from __future__ import annotations

import dataclasses

import pytest
from labeled_pairs import generate_raw_pairs
from mutations import MUTATIONS
from prevalence_estimates import (
    NEUTRAL_FREQUENCY,
    PREVALENCE_ESTIMATES,
    PrevalenceEstimate,
    researched_frequency,
)
from special_populations import INSTITUTION_TYPES


def _patient(
    id_: str, family: str = "Smith", given: str = "Katherine", zip_code: str = "10001"
):
    return {
        "resourceType": "Patient",
        "id": id_,
        "name": [{"family": family, "given": [given]}],
        "birthDate": "1980-06-15",
        "telecom": [],
        "address": [
            {"line": ["1 Main St"], "city": "NY", "state": "NY", "postalCode": zip_code}
        ],
        "identifier": [],
    }


class TestPrevalenceEstimatesCompleteness:
    """Every rationale key this repo's generators can actually produce must
    have an entry - either a real public estimate or an explicit
    has_public_estimate=False placeholder - never silently missing."""

    def test_every_fuzzy_mutation_type_has_an_entry(self):
        for mutation in MUTATIONS:
            key = f"fuzzy_variant/{mutation}"
            assert key in PREVALENCE_ESTIMATES, f"missing entry for {key}"

    def test_every_institution_type_has_an_entry(self):
        for institution_type in INSTITUTION_TYPES:
            key = f"special_population/{institution_type}"
            assert key in PREVALENCE_ESTIMATES, f"missing entry for {key}"

    @pytest.mark.parametrize(
        "key",
        [
            "normalization_edge_case/diacritic",
            "normalization_edge_case/punctuation",
            "hard_negative",
            "special_population/multi_generational_household",
        ],
    )
    def test_other_known_categories_have_an_entry(self, key):
        assert key in PREVALENCE_ESTIMATES, f"missing entry for {key}"


class TestPrevalenceEstimateInvariants:
    """Every entry must be internally consistent - real estimates carry a
    real citation and a value between 0 and 1; placeholders are explicit
    about being placeholders, not silently indistinguishable from a real
    small estimate."""

    @pytest.mark.parametrize("key,estimate", list(PREVALENCE_ESTIMATES.items()))
    def test_value_is_a_valid_proportion(self, key, estimate):
        assert 0.0 <= estimate.value <= 1.0, (
            f"{key}: value {estimate.value} out of [0, 1]"
        )

    @pytest.mark.parametrize("key,estimate", list(PREVALENCE_ESTIMATES.items()))
    def test_every_entry_has_a_nonempty_source_and_notes(self, key, estimate):
        assert estimate.source, f"{key}: missing source"
        assert estimate.notes, f"{key}: missing notes"

    @pytest.mark.parametrize("key,estimate", list(PREVALENCE_ESTIMATES.items()))
    def test_no_public_estimate_entries_use_the_neutral_value(self, key, estimate):
        if not estimate.has_public_estimate:
            assert estimate.value == NEUTRAL_FREQUENCY, (
                f"{key}: has_public_estimate=False but value != NEUTRAL_FREQUENCY - "
                "a placeholder must not silently double as a real estimate"
            )

    @pytest.mark.parametrize("key,estimate", list(PREVALENCE_ESTIMATES.items()))
    def test_is_direct_measurement_only_meaningful_with_a_public_estimate(
        self, key, estimate
    ):
        if not estimate.has_public_estimate:
            assert estimate.is_direct_measurement is False, (
                f"{key}: is_direct_measurement should be False when there's no public "
                "estimate at all - True would misleadingly imply a real direct measurement"
            )


class TestResearchedFrequency:
    def test_looks_up_bare_key_directly(self):
        result = researched_frequency("normalization_edge_case/diacritic")
        assert result == PREVALENCE_ESTIMATES["normalization_edge_case/diacritic"].value

    def test_strips_parenthetical_context_before_lookup(self):
        """hard_negative and multi_generational_household rationales carry
        extra "(key=value, ...)" context from format_rationale() - the
        lookup must match on the base category, not the full string."""
        result = researched_frequency(
            "hard_negative (birthDate=1980-01-01, postalCode=10001)"
        )
        assert result == PREVALENCE_ESTIMATES["hard_negative"].value

    def test_household_rationale_with_context_resolves_correctly(self):
        result = researched_frequency(
            "special_population/multi_generational_household "
            "(age_gap_years=20, family_name=RIVERA, postalCode=10001)"
        )
        assert (
            result
            == PREVALENCE_ESTIMATES[
                "special_population/multi_generational_household"
            ].value
        )

    def test_unknown_rationale_falls_back_to_neutral(self):
        assert (
            researched_frequency("some_future_category/not_yet_estimated")
            == NEUTRAL_FREQUENCY
        )

    def test_every_fuzzy_variant_type_resolves_without_error(self):
        for mutation in MUTATIONS:
            researched_frequency(f"fuzzy_variant/{mutation}")  # must not raise

    def test_every_institution_type_resolves_without_error(self):
        for institution_type in INSTITUTION_TYPES:
            researched_frequency(
                f"special_population/{institution_type}"
            )  # must not raise


class TestResearchedFrequencyAgainstRealGeneration:
    """End-to-end: every rationale generate_raw_pairs() actually produces
    resolves to a valid PrevalenceEstimate lookup, not a KeyError or
    silently-wrong value - using the same small synthetic patient set the
    rest of this suite uses (not real ONC fixtures, to stay consistent with
    every other test in this module and avoid a fragile fixture-path
    dependency)."""

    def test_generated_rationales_all_resolve(self):
        from export_test_dataset import format_rationale

        patients = [
            _patient("p1", family="Rivera", given="Ana", zip_code="10001"),
            _patient("p2", family="Rivera", given="Luis", zip_code="10001"),
            _patient("p3", family="Smith", zip_code="10001"),
            _patient("p4", family="Jones", zip_code="10001"),
            _patient("p5", family="Lee", zip_code="10001"),
        ]
        seen_keys = set()
        for raw in generate_raw_pairs(patients, seed=0):
            rationale = format_rationale(dict(raw.strata))
            freq = researched_frequency(rationale)
            assert isinstance(freq, float)
            seen_keys.add(rationale.split(" (")[0])
        assert seen_keys  # sanity: the sample actually produced some cases


class TestPrevalenceEstimateDataclass:
    def test_frozen_and_constructible(self):
        estimate = PrevalenceEstimate(
            value=0.5,
            has_public_estimate=True,
            is_direct_measurement=True,
            source="Test Source (2026)",
            notes="a test estimate",
        )
        assert estimate.value == 0.5
        with pytest.raises(dataclasses.FrozenInstanceError):
            estimate.value = 0.9  # type: ignore[misc]
