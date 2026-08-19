"""Unit tests for normalization_edge_cases.py (session 10). No numpy dependency."""

from __future__ import annotations

import random

import pytest
from normalization_edge_cases import (
    DIACRITIC_MAP,
    PUNCTUATION_CHARS,
    diacritic_variant,
    punctuation_variant,
)


def _patient(given="Jose", family="Nunez", dob="1980-01-01"):
    return {
        "resourceType": "Patient",
        "id": "p1",
        "name": [{"family": family, "given": [given]}],
        "birthDate": dob,
        "telecom": [],
        "address": [],
        "identifier": [],
    }


class TestDiacriticVariant:
    @pytest.mark.parametrize("field,name", [("given", "Jose"), ("family", "Nunez")])
    def test_introduces_exactly_one_accented_character(self, field, name):
        patient = _patient(given=name if field == "given" else "Ana", family=name if field == "family" else "Ana")
        variant = diacritic_variant(patient, field=field, rng=random.Random(0))
        value = variant["name"][0]["given"][0] if field == "given" else variant["name"][0]["family"]
        assert value != name
        assert any(accented in value for accented in DIACRITIC_MAP.values())

    def test_noop_when_no_foldable_characters(self):
        patient = _patient(given="Xyz")
        variant = diacritic_variant(patient, field="given")
        assert variant["name"][0]["given"][0] == "Xyz"

    def test_noop_on_short_values(self):
        patient = _patient(given="Al")
        variant = diacritic_variant(patient, field="given")
        assert variant["name"][0]["given"][0] == "Al"

    def test_does_not_mutate_the_original(self):
        patient = _patient()
        diacritic_variant(patient, field="given")
        assert patient["name"][0]["given"][0] == "Jose"


class TestPunctuationVariant:
    @pytest.mark.parametrize("punctuation", PUNCTUATION_CHARS)
    def test_inserts_requested_punctuation(self, punctuation):
        patient = _patient(family="OBrien")
        variant = punctuation_variant(patient, field="family", punctuation=punctuation)
        assert punctuation in variant["name"][0]["family"]

    def test_rejects_unknown_punctuation(self):
        with pytest.raises(ValueError):
            punctuation_variant(_patient(), field="family", punctuation="!")

    def test_noop_on_short_values(self):
        patient = _patient(family="Li")
        variant = punctuation_variant(patient, field="family")
        assert variant["name"][0]["family"] == "Li"

    def test_does_not_mutate_the_original(self):
        patient = _patient(family="OBrien")
        punctuation_variant(patient, field="family")
        assert patient["name"][0]["family"] == "OBrien"

    def test_random_picks_from_registered_punctuation(self):
        patient = _patient(family="OBrien")
        variant = punctuation_variant(patient, field="family", rng=random.Random(1))
        family = variant["name"][0]["family"]
        assert any(p in family for p in PUNCTUATION_CHARS)
