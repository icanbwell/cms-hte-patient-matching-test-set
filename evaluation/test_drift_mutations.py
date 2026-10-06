"""Unit tests for drift_mutations.py (session 15)."""

from __future__ import annotations

import copy
import random
from typing import Any, Dict

import pytest
from drift_mutations import (
    address_move_variant,
    email_churn_variant,
    gender_drift_variant,
    phone_churn_variant,
    surname_change_variant,
)
from identity_guard import normalize_token


def _patient(id_: str = "p1", **overrides: Any) -> Dict[str, Any]:
    patient: Dict[str, Any] = {
        "resourceType": "Patient",
        "id": id_,
        "name": [{"family": "SMITH", "given": ["KATHERINE"], "suffix": []}],
        "gender": "female",
        "birthDate": "1980-06-15",
        "telecom": [
            {"system": "phone", "value": "347-984-6839"},
            {"system": "email", "value": "KSMITH@EXAMPLE.COM"},
        ],
        "address": [
            {
                "line": ["1 MAIN ST"],
                "city": "NEW YORK",
                "state": "NY",
                "postalCode": "10001",
            }
        ],
        "identifier": [],
    }
    patient.update(overrides)
    return patient


def _donor(id_: str, family: str, phone: str, email: str, street: str, state="NY"):
    return {
        "resourceType": "Patient",
        "id": id_,
        "name": [{"family": family, "given": ["DONOR"]}],
        "telecom": [
            {"system": "phone", "value": phone},
            {"system": "email", "value": email},
        ],
        "address": [
            {"line": [street], "city": "X", "state": state, "postalCode": "20002"}
        ],
    }


DONORS = [
    _donor("d1", "OKAFOR", "212-555-0111", "DOK@EXAMPLE.COM", "9 ELM ST"),
    _donor("d2", "NGUYEN", "212-555-0122", "DNG@EXAMPLE.COM", "7 OAK AVE", state="CA"),
]


class TestSurnameChange:
    def test_new_primary_surname_is_never_one_the_source_already_carries(self):
        source = _patient()
        source["name"].append({"family": "OKAFOR", "given": ["KATHERINE"]})
        old = {normalize_token(n["family"]) for n in source["name"]}
        for seed in range(40):
            variant, _ = surname_change_variant(source, DONORS, random.Random(seed))
            assert normalize_token(variant["name"][0]["family"]) not in old
            assert "okafor" not in normalize_token(variant["name"][0]["family"])

    @pytest.mark.parametrize(
        "subtype,expected",
        [
            ("no_history", ["OKAFOR"]),
            ("prior_name_on_target", ["OKAFOR", "SMITH"]),
            ("hyphenated", ["SMITH-OKAFOR"]),
        ],
    )
    def test_each_subtype_has_its_documented_shape(self, subtype, expected):
        donors = [DONORS[0]]
        seen = {}
        for seed in range(60):
            variant, got = surname_change_variant(
                _patient(), donors, random.Random(seed)
            )
            seen.setdefault(got, [n["family"] for n in variant["name"]])
        assert seen[subtype] == expected

    def test_prior_name_entry_is_marked_maiden_and_keeps_given_names(self):
        for seed in range(60):
            variant, subtype = surname_change_variant(
                _patient(), [DONORS[0]], random.Random(seed)
            )
            if subtype == "prior_name_on_target":
                assert variant["name"][1]["use"] == "maiden"
                assert variant["name"][0]["given"] == ["KATHERINE"]
                return
        pytest.fail("prior_name_on_target never drawn")

    def test_none_without_a_usable_donor_or_a_surname(self):
        assert surname_change_variant(_patient(), [], random.Random(0)) is None
        same = _donor("d", "smith", "1", "a@b.c", "1 X ST")
        assert surname_change_variant(_patient(), [same], random.Random(0)) is None
        nameless = {"resourceType": "Patient", "id": "x"}
        assert surname_change_variant(nameless, DONORS, random.Random(0)) is None

    def test_does_not_mutate_inputs(self):
        source, donors = _patient(), copy.deepcopy(DONORS)
        snapshot = copy.deepcopy(source)
        surname_change_variant(source, donors, random.Random(0))
        assert source == snapshot and donors == DONORS


class TestAddressMove:
    def test_target_gets_a_different_donor_street(self):
        variant, _ = address_move_variant(_patient(), DONORS, random.Random(0))
        assert variant["address"][0]["line"][0] in {"9 ELM ST", "7 OAK AVE"}

    def test_prefers_a_same_state_donor(self):
        for seed in range(30):
            variant, _ = address_move_variant(_patient(), DONORS, random.Random(seed))
            assert variant["address"][0]["state"] == "NY"

    def test_history_subtype_keeps_the_old_address_as_old_and_invents_no_dates(self):
        for seed in range(60):
            variant, subtype = address_move_variant(
                _patient(), DONORS, random.Random(seed)
            )
            if subtype == "history_on_one_side":
                assert [a["use"] for a in variant["address"]] == ["home", "old"]
                assert variant["address"][1]["line"] == ["1 MAIN ST"]
                assert all("period" not in a for a in variant["address"])
                return
        pytest.fail("history_on_one_side never drawn")

    def test_current_vs_prior_replaces_the_address(self):
        for seed in range(60):
            variant, subtype = address_move_variant(
                _patient(), DONORS, random.Random(seed)
            )
            if subtype == "current_vs_prior":
                assert len(variant["address"]) == 1
                return
        pytest.fail("current_vs_prior never drawn")

    def test_none_when_no_address_no_donor_or_donor_is_same_street(self):
        assert (
            address_move_variant(_patient(address=[]), DONORS, random.Random(0)) is None
        )
        assert address_move_variant(_patient(), [], random.Random(0)) is None
        same = _donor("d", "X", "1", "a@b.c", "1 Main St.")
        same["address"][0]["postalCode"] = "10001"
        assert address_move_variant(_patient(), [same], random.Random(0)) is None


class TestContactChurn:
    def test_phone_replaced_uses_a_donor_number_not_already_held(self):
        for seed in range(60):
            variant, subtype = phone_churn_variant(
                _patient(), DONORS, random.Random(seed)
            )
            if subtype == "replaced":
                phones = [
                    t["value"] for t in variant["telecom"] if t["system"] == "phone"
                ]
                assert phones[0] in {"212-555-0111", "212-555-0122"}
                assert any(t["system"] == "email" for t in variant["telecom"])
                return
        pytest.fail("replaced never drawn")

    def test_phone_dropped_removes_only_the_first_phone(self):
        for seed in range(60):
            variant, subtype = phone_churn_variant(
                _patient(), DONORS, random.Random(seed)
            )
            if subtype == "dropped":
                assert [t["system"] for t in variant["telecom"]] == ["email"]
                return
        pytest.fail("dropped never drawn")

    def test_phone_added_when_the_patient_has_none(self):
        bare = _patient(telecom=[])
        variant, subtype = phone_churn_variant(bare, DONORS, random.Random(0))
        assert subtype == "added"
        assert variant["telecom"][0]["system"] == "phone"

    def test_phone_replaced_never_reuses_a_number_the_patient_already_has(self):
        donor = _donor("d", "X", "(347) 984-6839", "a@b.c", "5 ELM ST")
        for seed in range(30):
            result = phone_churn_variant(_patient(), [donor], random.Random(seed))
            assert result is None or result[1] == "dropped"

    def test_email_churn_mirrors_phone_churn(self):
        for seed in range(60):
            variant, subtype = email_churn_variant(
                _patient(), DONORS, random.Random(seed)
            )
            if subtype == "replaced":
                emails = [
                    t["value"] for t in variant["telecom"] if t["system"] == "email"
                ]
                assert emails[0] in {"DOK@EXAMPLE.COM", "DNG@EXAMPLE.COM"}
                return
        pytest.fail("replaced never drawn")

    def test_added_without_donors_is_none(self):
        assert phone_churn_variant(_patient(telecom=[]), [], random.Random(0)) is None

    def test_does_not_mutate_inputs(self):
        source = _patient()
        snapshot = copy.deepcopy(source)
        phone_churn_variant(source, DONORS, random.Random(0))
        assert source == snapshot


class TestGenderDrift:
    def test_gender_changes_to_a_different_value_and_another_field_also_differs(self):
        differs_elsewhere = 0
        for seed in range(40):
            variant, subtype = gender_drift_variant(_patient(), random.Random(seed))
            assert variant["gender"] != "female"
            assert subtype == f"female_to_{variant['gender']}"
            differs_elsewhere += {**variant, "gender": "female"} != _patient()
        assert differs_elsewhere > 0

    def test_none_for_a_gender_value_it_does_not_know(self):
        assert gender_drift_variant(_patient(gender="other"), random.Random(0)) is None

    def test_missing_gender_is_treated_as_unknown(self):
        patient = _patient()
        del patient["gender"]
        variant, subtype = gender_drift_variant(patient, random.Random(0))
        assert subtype.startswith("unknown_to_")
        assert variant["gender"] in {"male", "female"}
