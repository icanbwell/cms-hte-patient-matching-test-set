"""Unit tests for rule_eval, using synthetic labeled data.

The evaluation harness depends on numpy (and, for rendering, pandas/matplotlib),
which are intentionally NOT part of the shippable ``patient_matching`` package. These
tests therefore ``importorskip("numpy")`` so a numpy-less environment (e.g. the default
service CI image) skips them cleanly rather than failing. Install the harness deps with
``pip install numpy scipy pandas matplotlib`` (see evaluation/DESIGN.md) to run them.
"""

from __future__ import annotations

from typing import List

import pytest

pytest.importorskip("numpy")

import numpy as np
import rule_eval as re


# --------------------------------------------------------------------------------------
# Synthetic labeled data
# --------------------------------------------------------------------------------------
def make_synthetic(seed: int = 7) -> List[re.LabeledPair]:
    """Build a gold-standard set with a `score` feature and an `exact_id` signal.

    - True matches: score in [0.3, 1.0]; 120 of them are deliberately placed below the
      0.5 baseline threshold AND flagged exact_id=True (so a candidate that also trusts
      exact_id will *gain* them with no new false positives).
    - Non-matches: score in [0.0, 0.55]; never exact_id.
    """
    rng = np.random.default_rng(seed)
    pairs: List[re.LabeledPair] = []
    strata_choices = {
        "age_band": ["0-17", "18-64", "65+"],
        "name_commonality": ["common", "rare"],
        "dob_present": ["yes", "no"],
    }

    def rand_strata():
        return {k: str(rng.choice(v)) for k, v in strata_choices.items()}

    for i in range(2000):  # true matches
        score = float(rng.uniform(0.3, 1.0))
        pairs.append(
            re.LabeledPair(
                features={"score": score, "exact_id": False},
                is_true_match=True,
                strata=rand_strata(),
                pair_id=f"T{i}",
            )
        )
    for i in range(120):  # true matches placed below threshold w/ an exact_id signal
        pairs[i] = re.LabeledPair(
            features={"score": float(rng.uniform(0.30, 0.49)), "exact_id": True},
            is_true_match=True,
            strata=rand_strata(),
            pair_id=f"Tgain{i}",
        )
    for i in range(2000):  # non-matches (hard negatives clustered near the boundary)
        score = float(rng.uniform(0.0, 0.55))
        pairs.append(
            re.LabeledPair(
                features={"score": score, "exact_id": False},
                is_true_match=False,
                strata=rand_strata(),
                pair_id=f"N{i}",
            )
        )
    rng.shuffle(pairs)
    return pairs


def threshold_matcher(t: float) -> re.Matcher:
    return lambda f: f["score"] >= t


def strict_better_matcher(t: float) -> re.Matcher:
    return lambda f: (f["score"] >= t) or bool(f.get("exact_id"))


# --------------------------------------------------------------------------------------
# Metrics math
# --------------------------------------------------------------------------------------
def test_confusion_metrics_math():
    c = re.Confusion(tp=90, fp=10, fn=10, tn=90)
    assert c.n == 200
    assert c.tpr == pytest.approx(0.9)
    assert c.fnr == pytest.approx(0.1)
    assert c.fpr == pytest.approx(0.1)
    assert c.precision == pytest.approx(0.9)
    assert c.f1 == pytest.approx(0.9)


def test_evaluate_counts_add_up():
    pairs = make_synthetic()
    c = re.evaluate(threshold_matcher(0.5), pairs)
    assert c.n == len(pairs)
    assert c.n_true == sum(p.is_true_match for p in pairs)


# --------------------------------------------------------------------------------------
# Beta posteriors
# --------------------------------------------------------------------------------------
def test_rate_posterior_mean_and_ci():
    p = re.RatePosterior("x", successes=90, failures=10, higher_is_better=True)
    assert p.mean == pytest.approx((90 + 1) / (100 + 2))
    lo, hi = p.credible_interval()
    assert 0 <= lo < p.mean < hi <= 1


def test_prob_improvement_direction():
    rng = np.random.default_rng(0)
    same = re.RatePosterior("x", 90, 10, True)
    assert re.prob_improvement(same, same, rng=rng) == pytest.approx(0.5, abs=0.03)
    better = re.RatePosterior("x", 97, 3, True)
    assert re.prob_improvement(same, better, rng=rng) > 0.95
    fpr_base = re.RatePosterior("FPR", 20, 80, False)
    fpr_new = re.RatePosterior("FPR", 5, 95, False)
    assert re.prob_improvement(fpr_base, fpr_new, rng=rng) > 0.95


# --------------------------------------------------------------------------------------
# Paired recall / churn
# --------------------------------------------------------------------------------------
def test_paired_recall_buckets_and_churn():
    pairs = make_synthetic()
    pr = re.paired_recall(threshold_matcher(0.5), strict_better_matcher(0.5), pairs)
    assert pr.n_true == sum(p.is_true_match for p in pairs)
    assert pr.lost == 0
    assert pr.gained >= 100
    assert pr.churn == pr.gained
    assert pr.net_change > 0
    assert pr.prob_candidate_better() > 0.99
    assert pr.mcnemar_p_value() < 0.001


# --------------------------------------------------------------------------------------
# End-to-end compare() + verdicts
# --------------------------------------------------------------------------------------
def test_compare_strict_better_ships():
    pairs = make_synthetic()
    rep = re.compare(
        threshold_matcher(0.5),
        strict_better_matcher(0.5),
        pairs,
        candidate_name="trust-exact-id",
    )
    by = {m.name: m for m in rep.metrics}
    assert by["TPR (recall/sensitivity)"].verdict == "improved"
    assert by["FPR"].verdict != "regressed"
    assert rep.overall_verdict == "SHIP"


def test_compare_lenient_threshold_rejects_on_safety():
    pairs = make_synthetic()
    rep = re.compare(
        threshold_matcher(0.5),
        threshold_matcher(0.40),
        pairs,
        candidate_name="threshold-0.40",
    )
    by = {m.name: m for m in rep.metrics}
    assert by["TPR (recall/sensitivity)"].verdict == "improved"
    assert by["FPR"].verdict == "regressed"
    assert rep.overall_verdict == "REJECT"


def test_compare_identical_is_inconclusive():
    pairs = make_synthetic()
    rep = re.compare(threshold_matcher(0.5), threshold_matcher(0.5), pairs)
    for m in rep.metrics:
        assert m.verdict == "inconclusive"
    assert rep.overall_verdict == "NEEDS MORE DATA"


def test_format_report_runs():
    pairs = make_synthetic()
    rep = re.compare(threshold_matcher(0.5), strict_better_matcher(0.5), pairs)
    text = re.format_report(rep)
    assert "OVERALL VERDICT" in text


# --------------------------------------------------------------------------------------
# Sample size / power
# --------------------------------------------------------------------------------------
def test_min_sample_size_monotonic_in_effect():
    n_small_effect = re.min_sample_size(0.90, 0.02)
    n_big_effect = re.min_sample_size(0.90, 0.10)
    assert n_small_effect > n_big_effect
    assert 200 < n_small_effect < 20000


def test_detectable_delta_inverse():
    n = re.min_sample_size(0.90, 0.03)
    d = re.detectable_delta(n, 0.90)
    assert d == pytest.approx(0.03, abs=0.01)


# --------------------------------------------------------------------------------------
# Stratified split
# --------------------------------------------------------------------------------------
def test_stratified_split_sizes_disjoint_and_base_rate_preserved():
    pairs = make_synthetic()
    dev, hold = re.stratified_split(
        pairs, holdout_frac=0.70, strata_keys=["dob_present"], seed=1
    )
    assert len(dev) + len(hold) == len(pairs)
    assert 0.68 <= len(hold) / len(pairs) <= 0.74
    dev_ids = {p.pair_id for p in dev}
    hold_ids = {p.pair_id for p in hold}
    assert dev_ids.isdisjoint(hold_ids)
    base = np.mean([p.is_true_match for p in pairs])
    assert np.mean([p.is_true_match for p in hold]) == pytest.approx(base, abs=0.03)
    frac_missing_all = np.mean([p.strata["dob_present"] == "no" for p in pairs])
    frac_missing_hold = np.mean([p.strata["dob_present"] == "no" for p in hold])
    assert frac_missing_hold == pytest.approx(frac_missing_all, abs=0.04)


def test_kfold_metric_variance():
    pairs = make_synthetic()
    res = re.kfold_metric_variance(threshold_matcher(0.5), pairs, metric="tpr", k=5)
    assert len(res["folds"]) == 5
    assert 0 <= res["mean"] <= 1
    assert res["std"] >= 0
