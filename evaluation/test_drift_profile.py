"""Unit tests for drift_profile.py (session 15)."""

from __future__ import annotations

import json

import pytest
from drift_profile import LEGACY_RATES, PLACEHOLDER_RATES, DriftProfile


class TestDriftProfile:
    def test_defaults_keep_legacy_scenarios_at_full_rate(self):
        profile = DriftProfile()
        assert all(profile.rate(name) == 1.0 for name in LEGACY_RATES)

    def test_placeholder_rates_are_valid_and_gender_drift_is_off(self):
        profile = DriftProfile()
        assert profile.rate("gender_drift") == 0.0
        assert all(0.0 <= profile.rate(n) <= 1.0 for n in PLACEHOLDER_RATES)

    def test_unknown_scenario_is_off(self):
        assert DriftProfile().rate("not_a_scenario") == 0.0

    @pytest.mark.parametrize("bad", [-0.1, 1.5])
    def test_rejects_rates_outside_unit_interval(self, bad):
        with pytest.raises(ValueError, match="phone_churn"):
            DriftProfile(rates={"phone_churn": bad})

    def test_without_switches_named_scenarios_off_and_keeps_the_rest(self):
        profile = DriftProfile().without("ssn_dropped", "phone_churn")
        assert profile.rate("ssn_dropped") == 0.0
        assert profile.rate("phone_churn") == 0.0
        assert profile.rate("marriage_variant") == 1.0

    def test_from_json_reads_rates_and_source(self, tmp_path):
        path = tmp_path / "profile.json"
        path.write_text(
            json.dumps({"source": "workgroup 2026-10", "rates": {"phone_churn": 0.4}})
        )
        profile = DriftProfile.from_json(path)
        assert profile.rate("phone_churn") == 0.4
        assert profile.rate("surname_change") == 0.0
        assert profile.source == "workgroup 2026-10"
