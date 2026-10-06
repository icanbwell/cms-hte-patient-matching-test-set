"""Unit tests for naive_baselines.py (session 15)."""

from __future__ import annotations

from identity_guard import SSN_SYSTEM
from naive_baselines import BASELINES, SINGLE_FIELD_BASELINES, pair_features


def _patient(id_: str, **overrides):
    patient = {
        "resourceType": "Patient",
        "id": id_,
        "name": [{"family": "Smith", "given": ["Katherine"]}],
        "birthDate": "1980-06-15",
        "telecom": [{"system": "phone", "value": "347-984-6839"}],
        "address": [
            {
                "line": ["1 Main St"],
                "city": "NY",
                "state": "NY",
                "postalCode": "10001",
            }
        ],
        "identifier": [{"system": SSN_SYSTEM, "value": "892-39-5115"}],
    }
    patient.update(overrides)
    return patient


class TestPairFeatures:
    def test_identical_records_agree_on_every_field_except_email(self):
        f = pair_features(_patient("p1"), _patient("p2"))
        assert f == {
            "phone": True,
            "email": False,
            "ssn": True,
            "dob": True,
            "name_dob": True,
            "family": True,
            "given": True,
            "address": True,
        }

    def test_phone_compares_digits_not_formatting(self):
        other = _patient("p2", telecom=[{"system": "phone", "value": "(347) 984-6839"}])
        assert pair_features(_patient("p1"), other)["phone"] is True

    def test_missing_field_never_counts_as_agreement(self):
        a = _patient("p1", telecom=[], address=[], identifier=[])
        b = _patient("p2", telecom=[], address=[], identifier=[])
        f = pair_features(a, b)
        assert not (f["phone"] or f["email"] or f["ssn"] or f["address"])

    def test_placeholder_ssn_is_not_agreement(self):
        ident = [{"system": SSN_SYSTEM, "value": "999-99-9999"}]
        f = pair_features(
            _patient("p1", identifier=ident), _patient("p2", identifier=ident)
        )
        assert f["ssn"] is False


class TestBaselines:
    def test_single_field_baseline_names_are_registered(self):
        assert set(SINGLE_FIELD_BASELINES) <= set(BASELINES)
        assert "multi_field" in BASELINES

    def test_phone_only_matches_a_stranger_who_shares_a_phone(self):
        stranger = _patient(
            "p2",
            name=[{"family": "Jones", "given": ["Robert"]}],
            birthDate="1955-01-01",
            identifier=[],
        )
        f = pair_features(_patient("p1"), stranger)
        assert BASELINES["phone_only"](f) is True
        assert BASELINES["multi_field"](f) is False

    def test_multi_field_matches_same_person_with_changed_phone(self):
        moved = _patient("p2", telecom=[{"system": "phone", "value": "212-555-0100"}])
        f = pair_features(_patient("p1"), moved)
        assert BASELINES["phone_only"](f) is False
        assert BASELINES["multi_field"](f) is True


class TestEdgeCases:
    def test_bare_patients_agree_on_nothing(self):
        bare = {"resourceType": "Patient", "id": "x"}
        assert not any(pair_features(bare, dict(bare, id="y")).values())

    def test_phone_with_country_code_matches_the_bare_ten_digits(self):
        other = _patient(
            "p2", telecom=[{"system": "phone", "value": "+1 347 984 6839"}]
        )
        assert pair_features(_patient("p1"), other)["phone"] is True
