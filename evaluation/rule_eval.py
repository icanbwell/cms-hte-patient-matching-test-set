"""rule_eval — a rule-agnostic before/after evaluation harness for patient matching.

Given a *labeled gold-standard* set of match / non-match pairs, a **baseline**
matcher, and a **candidate** matcher (any blocking rule, scoring rule, or threshold
change — they all plug in the same way, as a ``features -> bool`` decision), this
module produces a before/after comparison of the standard record-linkage metrics
with a Bayesian uncertainty layer:

  * point metrics: TPR (sensitivity/recall), FPR, FNR, precision, F1
  * a Beta posterior per rate: ``Beta(successes + 1, failures + 1)`` with posterior
    mean and 95% credible interval, before and after
  * ``P(candidate is better)`` for each metric via posterior sampling
  * a **paired** analysis of true-positive behaviour on the *same* eval set
    (caught-by-both / lost / gained / missed-by-both), net TPR change, churn, and a
    pairing-aware improvement probability (Bayesian McNemar)
  * a ship / reject / needs-more-data verdict driven by the safety-first stance that
    a false positive (wrong-patient release) is the critical error

It has **no hard dependency on scipy/pandas/matplotlib** — those are imported lazily
only where used, so the core runs anywhere (incl. a bare Databricks Python cell).
numpy is required.

Design note (paired vs. independent posteriors): modelling TPR_before and TPR_after
as *independent* Betas is deliberately conservative — the two measurements come from
the same eval set and are positively correlated, so the independent-Beta
``P(better)`` understates confidence in a real change. For the recall comparison we
therefore also report the **paired** (Bayesian McNemar) probability, which uses only
the discordant pairs and is the more powerful, more appropriate signal.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Sequence, Tuple

import numpy as np

# A matcher is any callable that decides "is this pair a match?" from its features.
# A blocking rule, a scoring rule, or a threshold change is expressed as one of these.
Matcher = Callable[[Mapping[str, Any]], bool]


# --------------------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class LabeledPair:
    """One gold-standard labeled candidate pair.

    Attributes:
        features: Whatever the matcher needs to decide (scores, field values, flags).
        is_true_match: The gold label — True if the pair is genuinely the same person.
        strata: Categorical tags for stratified sampling / slice analysis, e.g.
            ``{"age_band": "0-17", "name_commonality": "common", "dob_present": "no"}``.
        pair_id: Optional stable identifier (useful for auditing churn).
    """

    features: Mapping[str, Any]
    is_true_match: bool
    strata: Mapping[str, str] = field(default_factory=dict)
    pair_id: str | None = None


def predict_all(matcher: Matcher, pairs: Sequence[LabeledPair]) -> np.ndarray:
    """Run a matcher over every pair, returning a boolean prediction array."""
    return np.array([bool(matcher(p.features)) for p in pairs], dtype=bool)


def gold_labels(pairs: Sequence[LabeledPair]) -> np.ndarray:
    return np.array([p.is_true_match for p in pairs], dtype=bool)


# --------------------------------------------------------------------------------------
# Confusion matrix + point metrics
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Confusion:
    tp: int
    fp: int
    fn: int
    tn: int

    @property
    def n(self) -> int:
        return self.tp + self.fp + self.fn + self.tn

    @property
    def n_true(self) -> int:  # gold true matches
        return self.tp + self.fn

    @property
    def n_false(self) -> int:  # gold non-matches
        return self.fp + self.tn

    def _safe(self, num: int, den: int) -> float:
        return num / den if den else float("nan")

    @property
    def tpr(self) -> float:  # sensitivity / recall
        return self._safe(self.tp, self.n_true)

    @property
    def fnr(self) -> float:
        return self._safe(self.fn, self.n_true)

    @property
    def fpr(self) -> float:
        return self._safe(self.fp, self.n_false)

    @property
    def precision(self) -> float:
        return self._safe(self.tp, self.tp + self.fp)

    @property
    def f1(self) -> float:
        p, r = self.precision, self.tpr
        if math.isnan(p) or math.isnan(r) or (p + r) == 0:
            return float("nan")
        return 2 * p * r / (p + r) if (p + r) else float("nan")


def confusion_from(preds: np.ndarray, labels: np.ndarray) -> Confusion:
    tp = int(np.sum(preds & labels))
    fp = int(np.sum(preds & ~labels))
    fn = int(np.sum(~preds & labels))
    tn = int(np.sum(~preds & ~labels))
    return Confusion(tp=tp, fp=fp, fn=fn, tn=tn)


def evaluate(matcher: Matcher, pairs: Sequence[LabeledPair]) -> Confusion:
    """Confusion matrix for one matcher over one eval set."""
    return confusion_from(predict_all(matcher, pairs), gold_labels(pairs))


# --------------------------------------------------------------------------------------
# Beta posteriors on a rate
# --------------------------------------------------------------------------------------
def _beta_ppf(q: float, a: float, b: float, rng: np.random.Generator) -> float:
    """Beta quantile. Uses scipy if available, else a large-sample numpy fallback."""
    try:
        from scipy.stats import beta as _sbeta  # type: ignore

        return float(_sbeta.ppf(q, a, b))
    except Exception:  # noqa: BLE001 - deliberately broad: scipy missing, or any
        # numerical failure from ppf on extreme (a, b) - both fall back the same way.
        return float(np.quantile(rng.beta(a, b, 200_000), q))


@dataclass
class RatePosterior:
    """Beta(successes + 1, failures + 1) posterior for a binomial rate.

    ``higher_is_better`` records the direction so improvement is unambiguous:
    True for TPR/precision/F1, False for FPR/FNR.
    """

    name: str
    successes: int
    failures: int
    higher_is_better: bool

    @property
    def alpha(self) -> float:
        return self.successes + 1.0

    @property
    def beta(self) -> float:
        return self.failures + 1.0

    @property
    def n(self) -> int:
        return self.successes + self.failures

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    def credible_interval(
        self, level: float = 0.95, rng: np.random.Generator | None = None
    ) -> Tuple[float, float]:
        rng = rng or np.random.default_rng(0)
        lo, hi = (1 - level) / 2, 1 - (1 - level) / 2
        return _beta_ppf(lo, self.alpha, self.beta, rng), _beta_ppf(
            hi, self.alpha, self.beta, rng
        )

    def sample(self, size: int, rng: np.random.Generator) -> np.ndarray:
        return rng.beta(self.alpha, self.beta, size)


def prob_improvement(
    before: RatePosterior,
    after: RatePosterior,
    *,
    n_samples: int = 50_000,
    rng: np.random.Generator | None = None,
) -> float:
    """P(candidate metric is *better* than baseline), respecting direction.

    Independent-posterior estimate (conservative — see module docstring)."""
    rng = rng or np.random.default_rng(0)
    a = after.sample(n_samples, rng)
    b = before.sample(n_samples, rng)
    assert before.higher_is_better == after.higher_is_better
    return float(np.mean(a > b) if before.higher_is_better else np.mean(a < b))


def ci_overlap(a: Tuple[float, float], b: Tuple[float, float]) -> bool:
    """Do two intervals overlap at all?"""
    return not (a[1] < b[0] or b[1] < a[0])


# --------------------------------------------------------------------------------------
# Paired true-positive behaviour (the churn view)
# --------------------------------------------------------------------------------------
@dataclass
class PairedRecall:
    """Paired TP behaviour over the gold *true-match* pairs only.

    Buckets: caught by both, lost (baseline caught, candidate missed = new FN),
    gained (candidate caught, baseline missed), missed by both.
    """

    both: int
    lost: int
    gained: int
    neither: int

    @property
    def n_true(self) -> int:
        return self.both + self.lost + self.gained + self.neither

    @property
    def net_change(self) -> float:
        """Change in recall = (gained - lost) / (# gold true matches)."""
        return (self.gained - self.lost) / self.n_true if self.n_true else float("nan")

    @property
    def churn(self) -> int:
        """Total known-good matches that changed status (losses + gains).

        Churn matters even when net is ~0: trading known-good matches for new ones
        shifts the risk profile."""
        return self.lost + self.gained

    def prob_candidate_better(
        self, *, n_samples: int = 50_000, rng: np.random.Generator | None = None
    ) -> float:
        """Pairing-aware P(candidate recall > baseline recall) — Bayesian McNemar.

        Among the discordant pairs (lost + gained), the fraction favouring the
        candidate has a Beta(gained + 1, lost + 1) posterior; the candidate is better
        iff that fraction exceeds 0.5."""
        rng = rng or np.random.default_rng(0)
        draws = rng.beta(self.gained + 1, self.lost + 1, n_samples)
        return float(np.mean(draws > 0.5))

    def mcnemar_p_value(self) -> float:
        """Two-sided exact McNemar p-value on the discordant counts (b=lost, c=gained)."""
        b, c = self.lost, self.gained
        n = b + c
        if n == 0:
            return 1.0
        k = min(b, c)
        # two-sided exact binomial(n, 0.5)
        tail = sum(math.comb(n, i) for i in range(k + 1)) / (2**n)
        return min(1.0, 2 * tail)


def paired_recall(
    baseline: Matcher, candidate: Matcher, pairs: Sequence[LabeledPair]
) -> PairedRecall:
    labels = gold_labels(pairs)
    bp = predict_all(baseline, pairs)
    cp = predict_all(candidate, pairs)
    t = labels  # gold true matches
    both = int(np.sum(t & bp & cp))
    lost = int(np.sum(t & bp & ~cp))
    gained = int(np.sum(t & ~bp & cp))
    neither = int(np.sum(t & ~bp & ~cp))
    return PairedRecall(both=both, lost=lost, gained=gained, neither=neither)


# --------------------------------------------------------------------------------------
# Before/after comparison report
# --------------------------------------------------------------------------------------
_METRICS = [
    # (name, higher_is_better, successes_attr, failures_attr)
    ("TPR (recall/sensitivity)", True, "tp", "fn"),
    ("FPR", False, "fp", "tn"),
    ("FNR", False, "fn", "tp"),
    ("Precision", True, "tp", "fp"),
]


@dataclass
class MetricComparison:
    name: str
    higher_is_better: bool
    before: float
    after: float
    before_ci: Tuple[float, float]
    after_ci: Tuple[float, float]
    prob_improvement: float
    verdict: str  # "improved" | "regressed" | "inconclusive"


@dataclass
class ComparisonReport:
    baseline_name: str
    candidate_name: str
    n_pairs: int
    base_rate: float  # gold true-match prevalence in the eval set
    before_confusion: Confusion
    after_confusion: Confusion
    metrics: List[MetricComparison]
    f1_before: float
    f1_after: float
    f1_prob_improvement: float
    paired: PairedRecall
    paired_prob_better: float
    overall_verdict: str  # "SHIP" | "REJECT" | "NEEDS MORE DATA"
    notes: List[str] = field(default_factory=list)


def _metric_verdict(prob_improve: float, ship_p: float, reject_p: float) -> str:
    if prob_improve >= ship_p:
        return "improved"
    if prob_improve <= reject_p:
        return "regressed"
    return "inconclusive"


def compare(
    baseline: Matcher,
    candidate: Matcher,
    pairs: Sequence[LabeledPair],
    *,
    baseline_name: str = "baseline",
    candidate_name: str = "candidate",
    primary_metric: str = "TPR (recall/sensitivity)",
    ship_prob: float = 0.95,
    reject_prob: float = 0.05,
    n_samples: int = 50_000,
    seed: int = 0,
) -> ComparisonReport:
    """Produce the full before/after comparison with uncertainty and a verdict.

    Verdict policy (safety-first — a false positive is the critical error):
      * REJECT if FPR or Precision *decisively regresses* (prob-improvement <= reject_prob).
      * SHIP if no safety regression AND the ``primary_metric`` decisively improves
        (prob-improvement >= ship_prob).
      * NEEDS MORE DATA otherwise (credible intervals still overlap materially).
    """
    rng = np.random.default_rng(seed)
    before = evaluate(baseline, pairs)
    after = evaluate(candidate, pairs)
    labels = gold_labels(pairs)
    n = len(pairs)
    base_rate = float(np.mean(labels)) if n else float("nan")

    comparisons: List[MetricComparison] = []
    for name, hib, s_attr, f_attr in _METRICS:
        bp = RatePosterior(name, getattr(before, s_attr), getattr(before, f_attr), hib)
        ap = RatePosterior(name, getattr(after, s_attr), getattr(after, f_attr), hib)
        p_imp = prob_improvement(bp, ap, n_samples=n_samples, rng=rng)
        comparisons.append(
            MetricComparison(
                name=name,
                higher_is_better=hib,
                before=bp.mean,
                after=ap.mean,
                before_ci=bp.credible_interval(rng=rng),
                after_ci=ap.credible_interval(rng=rng),
                prob_improvement=p_imp,
                verdict=_metric_verdict(p_imp, ship_prob, reject_prob),
            )
        )

    # F1 via sampling from its component (precision, recall) posteriors.
    def _f1_samples(c: Confusion) -> np.ndarray:
        r = rng.beta(c.tp + 1, c.fn + 1, n_samples)
        p = rng.beta(c.tp + 1, c.fp + 1, n_samples)
        denom = r + p
        return np.where(denom > 0, 2 * r * p / denom, 0.0)

    f1_b, f1_a = _f1_samples(before), _f1_samples(after)
    f1_prob = float(np.mean(f1_a > f1_b))

    paired = paired_recall(baseline, candidate, pairs)
    paired_p = paired.prob_candidate_better(n_samples=n_samples, rng=rng)

    # ---- overall verdict ----
    by_name = {m.name: m for m in comparisons}
    safety = [by_name["FPR"], by_name["Precision"]]
    notes: List[str] = []
    if any(m.verdict == "regressed" for m in safety):
        overall = "REJECT"
        notes.append("A safety metric (FPR or Precision) decisively regressed.")
    else:
        primary = by_name[primary_metric]
        if primary.verdict == "improved":
            overall = "SHIP"
        else:
            overall = "NEEDS MORE DATA"
    if paired.churn and paired.lost:
        notes.append(
            f"Churn: {paired.gained} known-good matches gained, {paired.lost} lost "
            f"(net {paired.net_change:+.1%}). Losses change the risk profile even if net is flat."
        )

    return ComparisonReport(
        baseline_name=baseline_name,
        candidate_name=candidate_name,
        n_pairs=n,
        base_rate=base_rate,
        before_confusion=before,
        after_confusion=after,
        metrics=comparisons,
        f1_before=float(np.mean(f1_b)),
        f1_after=float(np.mean(f1_a)),
        f1_prob_improvement=f1_prob,
        paired=paired,
        paired_prob_better=paired_p,
        overall_verdict=overall,
        notes=notes,
    )


# --------------------------------------------------------------------------------------
# Sample-size / power
# --------------------------------------------------------------------------------------
def _z(p: float) -> float:
    """Inverse standard-normal CDF (stdlib, no scipy)."""
    return statistics.NormalDist().inv_cdf(p)


def min_sample_size(
    p0: float,
    delta: float,
    *,
    alpha: float = 0.05,
    power: float = 0.80,
    two_sided: bool = True,
) -> int:
    """Minimum labeled pairs *per arm* to detect a shift of ``delta`` from rate ``p0``.

    Standard two-proportion power formula. For a paired/same-set comparison this is a
    conservative upper bound (pairing reduces the requirement). Example: detecting a
    2-point FNR change near 0.10 → ``min_sample_size(0.10, 0.02)``.
    """
    if not 0 < p0 < 1:
        raise ValueError("p0 must be in (0, 1)")
    p1 = min(max(p0 + delta, 1e-6), 1 - 1e-6)
    z_a = _z(1 - alpha / 2) if two_sided else _z(1 - alpha)
    z_b = _z(power)
    num = (
        z_a * math.sqrt(2 * _pbar(p0, p1) * (1 - _pbar(p0, p1)))
        + z_b * math.sqrt(p0 * (1 - p0) + p1 * (1 - p1))
    ) ** 2
    return math.ceil(num / (delta**2))


def _pbar(p0: float, p1: float) -> float:
    return (p0 + p1) / 2


def detectable_delta(
    n_per_arm: int, p0: float, *, alpha: float = 0.05, power: float = 0.80
) -> float:
    """Smallest effect size detectable with ``n_per_arm`` labels (bisection on min_sample_size)."""
    lo, hi = 1e-4, 1 - p0 - 1e-4
    for _ in range(60):
        mid = (lo + hi) / 2
        if min_sample_size(p0, mid, alpha=alpha, power=power) <= n_per_arm:
            hi = mid
        else:
            lo = mid
    return hi


# --------------------------------------------------------------------------------------
# Stratified splitting + k-fold
# --------------------------------------------------------------------------------------
def stratified_split(
    pairs: Sequence[LabeledPair],
    *,
    holdout_frac: float = 0.70,
    strata_keys: Sequence[str] | None = None,
    seed: int = 0,
) -> Tuple[List[LabeledPair], List[LabeledPair]]:
    """Split into (dev, holdout), stratified by gold label + demographic strata.

    The **holdout** is the protected evaluation set (default 70%) that must never be
    used to design or tune rules; **dev** (default 30%) is for rule development. When
    labels are scarce the holdout is filled first (it gets the rounding-up), per the
    "protect the holdout" principle. Stratifying on the gold label preserves the true
    match/non-match base rate; stratifying on ``strata_keys`` (e.g. ``dob_present``)
    preserves demographic slices so a rule's degradation on, say, missing-DOB records
    is measurable.
    """
    rng = np.random.default_rng(seed)
    groups: Dict[Tuple, List[int]] = {}
    for i, p in enumerate(pairs):
        key = (p.is_true_match,) + tuple(
            p.strata.get(k, "?") for k in (strata_keys or ())
        )
        groups.setdefault(key, []).append(i)

    dev_idx: List[int] = []
    hold_idx: List[int] = []
    for key, idxs in groups.items():
        idxs = list(idxs)
        rng.shuffle(idxs)
        n_hold = math.ceil(len(idxs) * holdout_frac)  # protect holdout: round up
        hold_idx.extend(idxs[:n_hold])
        dev_idx.extend(idxs[n_hold:])
    dev = [pairs[i] for i in sorted(dev_idx)]
    hold = [pairs[i] for i in sorted(hold_idx)]
    return dev, hold


def kfold_metric_variance(
    matcher: Matcher,
    pairs: Sequence[LabeledPair],
    *,
    metric: str = "tpr",
    k: int = 5,
    seed: int = 0,
) -> Dict[str, Any]:
    """Report a metric's mean/std across k folds of the holdout (cheap robustness check)."""
    rng = np.random.default_rng(seed)
    idx = np.arange(len(pairs))
    rng.shuffle(idx)
    folds = np.array_split(idx, k)
    vals: List[float] = []
    for f in folds:
        subset = [pairs[int(i)] for i in f]
        c = evaluate(matcher, subset)
        vals.append(getattr(c, metric))
    clean = [v for v in vals if not math.isnan(v)]  # drop nan folds
    return {
        "metric": metric,
        "folds": vals,
        "mean": statistics.fmean(clean) if clean else float("nan"),
        "std": statistics.pstdev(clean) if len(clean) > 1 else 0.0,
    }


# --------------------------------------------------------------------------------------
# Rendering: table + credible-interval plot (lazy pandas/matplotlib)
# --------------------------------------------------------------------------------------
def report_to_dataframe(report: ComparisonReport):
    """Render the comparison as a pandas DataFrame (one row per metric)."""
    import pandas as pd

    rows = []
    for m in report.metrics:
        rows.append(
            {
                "metric": m.name,
                "before": round(m.before, 4),
                "after": round(m.after, 4),
                "before_95CrI": f"[{m.before_ci[0]:.3f}, {m.before_ci[1]:.3f}]",
                "after_95CrI": f"[{m.after_ci[0]:.3f}, {m.after_ci[1]:.3f}]",
                "P(better)": round(m.prob_improvement, 3),
                "verdict": m.verdict,
            }
        )
    rows.append(
        {
            "metric": "F1",
            "before": round(report.f1_before, 4),
            "after": round(report.f1_after, 4),
            "before_95CrI": "-",
            "after_95CrI": "-",
            "P(better)": round(report.f1_prob_improvement, 3),
            "verdict": _metric_verdict(report.f1_prob_improvement, 0.95, 0.05),
        }
    )
    return pd.DataFrame(rows)


def plot_credible_intervals(report: ComparisonReport):
    """Return a matplotlib Figure with before/after posterior means + 95% CrIs."""
    import matplotlib.pyplot as plt

    metrics = report.metrics
    fig, ax = plt.subplots(figsize=(9, 0.9 * len(metrics) + 1.5))
    y = np.arange(len(metrics))
    for i, m in enumerate(metrics):
        ax.plot(
            [m.before_ci[0], m.before_ci[1]],
            [i + 0.12, i + 0.12],
            color="#90a4ae",
            lw=3,
            solid_capstyle="round",
        )
        ax.plot(
            m.before,
            i + 0.12,
            "o",
            color="#455a64",
            label="baseline" if i == 0 else None,
        )
        ax.plot(
            [m.after_ci[0], m.after_ci[1]],
            [i - 0.12, i - 0.12],
            color="#80cbc4",
            lw=3,
            solid_capstyle="round",
        )
        ax.plot(
            m.after,
            i - 0.12,
            "o",
            color="#00897b",
            label="candidate" if i == 0 else None,
        )
        ax.text(
            1.01,
            i,
            f"P(better)={m.prob_improvement:.2f}",
            va="center",
            fontsize=9,
            transform=ax.get_yaxis_transform(),
        )
    ax.set_yticks(y)
    ax.set_yticklabels([m.name for m in metrics])
    ax.set_xlim(0, 1)
    ax.set_xlabel("rate (posterior mean, 95% credible interval)")
    ax.set_title(
        f"{report.candidate_name} vs {report.baseline_name}  —  verdict: {report.overall_verdict}"
    )
    ax.legend(loc="lower right")
    ax.invert_yaxis()
    fig.tight_layout()
    return fig


def format_report(report: ComparisonReport) -> str:
    """Plain-text summary (works with no pandas/matplotlib)."""
    lines = [
        f"=== {report.candidate_name} vs {report.baseline_name} ===",
        f"eval pairs: {report.n_pairs}  |  base rate (true matches): {report.base_rate:.3f}",
        "",
        f"{'metric':28s} {'before':>8s} {'after':>8s} {'P(better)':>10s}  verdict",
    ]
    for m in report.metrics:
        lines.append(
            f"{m.name:28s} {m.before:8.4f} {m.after:8.4f} {m.prob_improvement:10.3f}  {m.verdict}"
        )
    lines.append(
        f"{'F1':28s} {report.f1_before:8.4f} {report.f1_after:8.4f} {report.f1_prob_improvement:10.3f}"
    )
    lines += [
        "",
        (
            f"Paired recall (true matches): both={report.paired.both} lost={report.paired.lost} "
            f"gained={report.paired.gained} missed_by_both={report.paired.neither}"
        ),
        (
            f"  net recall change = {report.paired.net_change:+.1%}  churn = {report.paired.churn}  "
            f"P(candidate better, paired) = {report.paired_prob_better:.3f}"
        ),
        "",
        f">>> OVERALL VERDICT: {report.overall_verdict}",
    ]
    for note in report.notes:
        lines.append(f"    - {note}")
    return "\n".join(lines)
