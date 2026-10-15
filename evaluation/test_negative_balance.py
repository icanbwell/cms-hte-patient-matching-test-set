"""Unit tests for negative_balance.py."""

from __future__ import annotations

from collections import Counter

import pytest
from audit import category_of
from export_test_dataset import LabeledCaseRecord
from negative_balance import rebalance_negatives


def _rec(case_id: str, expected: bool, rationale: str) -> LabeledCaseRecord:
    return LabeledCaseRecord(
        case_id=case_id,
        source={},
        target={},
        expected_match=expected,
        rationale=rationale,
    )


def _records(positives: dict, negatives: int):
    records = [
        _rec(f"{cat}{i}", True, f"{cat}/x")
        for cat, n in positives.items()
        for i in range(n)
    ]
    records += [_rec(f"neg{i}", False, "hard_negative") for i in range(negatives)]
    return records


def _share(records):
    return sum(1 for r in records if not r.expected_match) / len(records)


def test_subsamples_positives_to_reach_the_target_share():
    out = rebalance_negatives(
        _records({"a": 100, "b": 100}, 100), target_share=0.5, seed=0
    )
    assert _share(out) == pytest.approx(0.5)
    kept = Counter(category_of(r.rationale) for r in out if r.expected_match)
    assert kept["a"] == kept["b"] == 50


def test_never_drops_a_negative():
    records = _records({"a": 300}, 100)
    out = rebalance_negatives(records, target_share=0.5, seed=0)
    assert {r.case_id for r in out if not r.expected_match} == {
        r.case_id for r in records if not r.expected_match
    }


def test_small_categories_keep_their_floor():
    out = rebalance_negatives(
        _records({"rare": 10, "big": 500}, 100), target_share=0.5, seed=0
    )
    kept = Counter(category_of(r.rationale) for r in out if r.expected_match)
    assert kept["rare"] == 10
    assert kept["big"] == 90


def test_no_op_when_already_balanced_enough():
    records = _records({"a": 50}, 100)
    assert rebalance_negatives(records, target_share=0.5, seed=0) == records


def test_reports_a_shortfall_by_leaving_the_share_below_target_rather_than_failing():
    # 10 negatives cannot support 500 positives at 50% once floors apply.
    out = rebalance_negatives(
        _records({"a": 500, "b": 500}, 10), target_share=0.5, seed=0
    )
    assert _share(out) < 0.5
    assert sum(1 for r in out if r.expected_match) == 50  # two floors of 25


def test_is_deterministic_and_keeps_original_order():
    records = _records({"a": 200}, 50)
    first = rebalance_negatives(records, target_share=0.5, seed=3)
    second = rebalance_negatives(records, target_share=0.5, seed=3)
    assert [r.case_id for r in first] == [r.case_id for r in second]
    order = {r.case_id: i for i, r in enumerate(records)}
    assert [order[r.case_id] for r in first] == sorted(order[r.case_id] for r in first)


@pytest.mark.parametrize("bad", [0.0, 1.0, -0.1, 1.5])
def test_rejects_a_target_outside_the_open_unit_interval(bad):
    with pytest.raises(ValueError, match="target_share"):
        rebalance_negatives([], target_share=bad, seed=0)
