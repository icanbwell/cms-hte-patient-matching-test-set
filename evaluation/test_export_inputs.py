"""Unit tests for export_inputs.py (session 15)."""

from __future__ import annotations

import json

from drift_profile import DriftProfile
from export_inputs import load_profile, load_sample_and_donors


class TestLoadSampleAndDonors:
    def test_donors_follow_the_sample_and_never_overlap_it(self):
        sample, donors = load_sample_and_donors(20, 10)
        assert len(sample) == 20 and len(donors) == 10
        assert not {p["id"] for p in sample} & {p["id"] for p in donors}

    def test_zero_donors_is_allowed(self):
        sample, donors = load_sample_and_donors(5, 0)
        assert len(sample) == 5 and donors == []


class TestLoadProfile:
    def test_default_without_the_env_var(self, monkeypatch):
        monkeypatch.delenv("DRIFT_PROFILE_PATH", raising=False)
        assert load_profile().rates == DriftProfile().rates

    def test_reads_the_json_named_by_the_env_var(self, monkeypatch, tmp_path):
        path = tmp_path / "profile.json"
        path.write_text(json.dumps({"rates": {"phone_churn": 0.3}}))
        monkeypatch.setenv("DRIFT_PROFILE_PATH", str(path))
        assert load_profile().rate("phone_churn") == 0.3
