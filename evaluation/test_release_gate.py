"""Unit tests for release_gate.py (session 15), plus the gate over the committed files."""

from __future__ import annotations

import pytest
from audit import build_report
from release_gate import check, failures, load_thresholds, metric_value

REPORT = {
    "same_person_negatives": ["a", "b"],
    "tier_parity_gap": [],
    "best_single_field_f1": 0.98,
    "multi_field_margin": 0.01,
}


class TestCheck:
    def test_list_metrics_gate_on_length(self):
        assert metric_value(REPORT, "same_person_negatives") == 2.0

    def test_max_and_min_bounds(self):
        thresholds = {
            "same_person_negatives": {"max": 0, "status": "enforced"},
            "tier_parity_gap": {"max": 0, "status": "enforced"},
            "multi_field_margin": {"min": 0.05, "status": "enforced"},
        }
        by_name = {r.name: r.passed for r in check(REPORT, thresholds)}
        assert by_name == {
            "same_person_negatives": False,
            "tier_parity_gap": True,
            "multi_field_margin": False,
        }

    def test_tracked_violations_do_not_fail_the_gate(self):
        thresholds = {"same_person_negatives": {"max": 0, "status": "tracked"}}
        assert failures(check(REPORT, thresholds)) == []

    def test_enforced_violations_fail_the_gate(self):
        thresholds = {"same_person_negatives": {"max": 0, "status": "enforced"}}
        assert [r.name for r in failures(check(REPORT, thresholds))] == [
            "same_person_negatives"
        ]

    def test_rejects_a_metric_the_report_does_not_contain(self):
        with pytest.raises(ValueError, match="unknown metric"):
            check(REPORT, {"not_a_metric": {"max": 0, "status": "tracked"}})

    def test_rejects_unknown_status(self):
        with pytest.raises(ValueError):
            check(REPORT, {"tier_parity_gap": {"max": 0, "status": "maybe"}})


class TestCommittedDataset:
    def test_enforced_thresholds_hold_on_the_committed_files(self):
        results = check(build_report(), load_thresholds())
        assert failures(results) == []


def test_check_rejects_rule_without_bounds():
    import pytest
    from release_gate import check

    with pytest.raises(ValueError, match="min or max"):
        check({"m": 1.0}, {"m": {"status": "enforced"}})


def test_check_rejects_unknown_rule_key():
    import pytest
    from release_gate import check

    with pytest.raises(ValueError, match="unknown rule keys"):
        check({"m": 1.0}, {"m": {"mx": 1, "status": "tracked"}})


def test_check_rejects_non_scalar_metric():
    import pytest
    from release_gate import check

    with pytest.raises(TypeError, match="not a scalar"):
        check({"m": {"a": 1}}, {"m": {"max": 1, "status": "tracked"}})
