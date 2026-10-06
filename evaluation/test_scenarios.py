"""Unit tests for scenarios.py (session 15)."""

from __future__ import annotations

import copy
import json
from typing import Any, Dict

import pytest
from drift_profile import DriftProfile
from identity_guard import SSN_SYSTEM
from scenarios import REGISTRY, generate_scenario_variants


def _patient(id_: str, family: str = "SMITH", **overrides: Any) -> Dict[str, Any]:
    patient: Dict[str, Any] = {
        "resourceType": "Patient",
        "id": id_,
        "name": [
            {"family": family, "given": ["KATHERINE"]},
            {"family": "JONES", "given": ["KATHERINE"]},
        ],
        "gender": "female",
        "birthDate": "1980-06-15",
        "telecom": [
            {"system": "phone", "value": "347-984-6839"},
            {"system": "phone", "value": "718-555-0001"},
            {"system": "email", "value": "K@EXAMPLE.COM"},
        ],
        "address": [
            {"line": ["1 MAIN ST"], "city": "NY", "state": "NY", "postalCode": "10001"}
        ],
        "identifier": [{"system": SSN_SYSTEM, "value": "892-39-5115"}],
    }
    patient.update(overrides)
    return patient


DONORS = [
    {
        "resourceType": "Patient",
        "id": "d1",
        "name": [{"family": "OKAFOR", "given": ["DONOR"]}],
        "telecom": [
            {"system": "phone", "value": "212-555-0111"},
            {"system": "email", "value": "DOK@EXAMPLE.COM"},
        ],
        "address": [
            {"line": ["9 ELM ST"], "city": "X", "state": "NY", "postalCode": "20002"}
        ],
    }
]


def _variants(patient, profile, *, donors=DONORS, seed=0, next_patient=None):
    return {
        s.name: r
        for s, r in generate_scenario_variants(
            patient,
            next_patient=next_patient or _patient("n1", family="LEE"),
            donors=donors,
            profile=profile,
            seed=seed,
        )
    }


class TestRegistry:
    def test_names_match_pair_types_and_are_unique(self):
        assert [s.name for s in REGISTRY.values()] == list(REGISTRY)
        assert all(s.pair_type == s.name for s in REGISTRY.values())

    def test_session_14_scenarios_keep_their_original_relative_order(self):
        names = list(REGISTRY)
        assert names[:3] == ["ssn_dropped", "marriage_variant", "phone_variant"]


class TestGenerateScenarioVariants:
    def test_default_profile_emits_legacy_and_new_scenarios_but_not_gender(self):
        everything = DriftProfile(rates={n: 1.0 for n in REGISTRY})
        got = _variants(_patient("p1"), everything)
        assert set(got) == set(REGISTRY)
        default = _variants(_patient("p1"), DriftProfile())
        assert "gender_drift" not in default

    def test_legacy_suffixes_are_unchanged(self):
        got = _variants(_patient("p1"), DriftProfile(rates={n: 1.0 for n in REGISTRY}))
        assert got["ssn_dropped"].suffix == "ssn_dropped"
        assert got["marriage_variant"].suffix == "marriage_variant"
        assert got["phone_variant"].suffix == "phone_variant"
        assert dict(got["ssn_dropped"].strata) == {}

    def test_new_scenarios_carry_their_subtype_in_the_case_stratum(self):
        got = _variants(_patient("p1"), DriftProfile(rates={n: 1.0 for n in REGISTRY}))
        for name in ("surname_change", "address_move", "phone_churn", "placeholder"):
            assert got[name].suffix == name
            assert got[name].strata["case"]

    def test_rate_zero_is_off_and_missing_rate_is_off(self):
        assert _variants(_patient("p1"), DriftProfile(rates={})) == {}
        assert _variants(_patient("p1"), DriftProfile(rates={"phone_churn": 0.0})) == {}

    def test_fractional_rate_selects_a_matching_share_of_patients(self):
        profile = DriftProfile(rates={"phone_churn": 0.5})
        hits = sum(bool(_variants(_patient(f"p{i}"), profile)) for i in range(400))
        assert 150 < hits < 250

    def test_deterministic_for_a_seed_and_patient_independent_of_other_patients(self):
        profile = DriftProfile(rates={n: 1.0 for n in REGISTRY})
        a = _variants(_patient("p1"), profile, seed=3)
        _variants(_patient("other"), profile, seed=3)
        b = _variants(_patient("p1"), profile, seed=3)
        assert {k: v.variant for k, v in a.items()} == {
            k: v.variant for k, v in b.items()
        }

    def test_a_different_seed_changes_random_scenarios(self):
        profile = DriftProfile(rates={"placeholder": 1.0})
        results = {
            json.dumps(
                _variants(_patient("p1"), profile, seed=s)["placeholder"].variant,
                sort_keys=True,
            )
            for s in range(10)
        }
        assert len(results) > 1

    def test_without_donors_donor_scenarios_yield_nothing_but_placeholder_still_does(
        self,
    ):
        profile = DriftProfile(rates={n: 1.0 for n in REGISTRY})
        got = _variants(_patient("p1"), profile, donors=[])
        assert "surname_change" not in got and "address_move" not in got
        assert "placeholder" in got

    def test_scenarios_that_leave_the_patient_unchanged_are_skipped(self):
        profile = DriftProfile(rates={"ssn_dropped": 1.0})
        no_ssn = _patient("p1", identifier=[])
        assert _variants(no_ssn, profile) == {}

    def test_marriage_variant_needs_a_next_patient(self):
        profile = DriftProfile(rates={"marriage_variant": 1.0})
        got = list(
            generate_scenario_variants(
                _patient("p1"), next_patient=None, donors=[], profile=profile, seed=0
            )
        )
        assert got == []

    def test_bare_patient_never_raises(self):
        bare = {"resourceType": "Patient", "id": "x"}
        profile = DriftProfile(rates={n: 1.0 for n in REGISTRY})
        _variants(bare, profile)

    def test_inputs_are_not_mutated(self):
        patient = _patient("p1")
        snapshot = copy.deepcopy(patient)
        _variants(patient, DriftProfile(rates={n: 1.0 for n in REGISTRY}))
        assert patient == snapshot


@pytest.mark.parametrize("name", ["phone_churn", "email_churn"])
def test_contact_churn_is_not_gated_on_a_second_phone(name):
    one_phone = _patient("p1", telecom=[{"system": "phone", "value": "347-984-6839"}])
    got = _variants(one_phone, DriftProfile(rates={name: 1.0}))
    assert name in got
