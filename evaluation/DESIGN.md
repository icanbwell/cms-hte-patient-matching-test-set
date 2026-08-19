# Standardized Rule-Testing Framework for Patient Matching

**Purpose.** Given any candidate change to the matching logic — a new blocking rule, a
new scoring rule, or a threshold change — produce a **rigorous before/after comparison**
on a labeled gold-standard set, so a reviewer (e.g., Sean while Zack is out) can decide
**ship / reject / needs-more-data** from evidence, not vibes.

**Design principle: rule-agnostic.** Everything downstream treats a "rule" as a single
function, `features -> bool` (predicted match). A blocking rule, a scoring rule, and a
threshold change are all just different such functions, so they plug in the same way.
The harness never needs to know *how* a decision was made.

Code lives in [`rule_eval.py`](rule_eval.py); tests in [`test_rule_eval.py`](test_rule_eval.py);
a runnable walkthrough in [`notebooks/rule_eval_demo.ipynb`](notebooks/rule_eval_demo.ipynb).

---

## 1. Architecture

```
labeled gold set ──► stratified_split() ──► dev (30%)      : design / calibrate the rule
   (LabeledPair[])                          holdout (70%)  : PROTECTED — evaluate only

               baseline matcher ─┐
               candidate matcher ─┼─► compare(baseline, candidate, holdout) ─► ComparisonReport
                       holdout ───┘                                              │
                                                                                 ├─ point metrics (confusion)
                                                                                 ├─ Beta posteriors + 95% CrI
                                                                                 ├─ P(better) per metric
                                                                                 ├─ paired recall churn (McNemar)
                                                                                 └─ SHIP / REJECT / NEEDS-MORE-DATA
                                          report_to_dataframe() · plot_credible_intervals() · format_report()
```

Core objects (all in `rule_eval.py`):

| Object | Role |
|---|---|
| `LabeledPair(features, is_true_match, strata, pair_id)` | one gold-labeled candidate pair; `strata` carries demographic tags for slicing |
| `Matcher = Callable[[features], bool]` | the rule under test; baseline and candidate are both this type |
| `Confusion` | TP/FP/FN/TN + all point-metric properties |
| `RatePosterior` | `Beta(successes+1, failures+1)` for one rate, with `mean`, `credible_interval`, `sample` |
| `PairedRecall` | paired TP buckets + churn + Bayesian-McNemar improvement probability |
| `ComparisonReport` | the full before/after artifact + verdict |
| `compare(...)` | the one call that produces a report |
| `stratified_split`, `kfold_metric_variance` | the data protocol (§3) |
| `min_sample_size`, `detectable_delta` | the power calc (§2) |

---

## 2. Metrics & the statistical rigor layer

### 2.1 Point metrics (definitions)
For a confusion matrix on the eval set (TP/FP/FN/TN):

| Metric | Definition | Direction |
|---|---|---|
| **TPR** (sensitivity / recall) | TP / (TP + FN) | higher better |
| **FNR** | FN / (TP + FN) = 1 − TPR | lower better |
| **FPR** | FP / (FP + TN) | lower better |
| **Precision** | TP / (TP + FP) | higher better |
| **F1** | 2·P·R / (P + R) | higher better |

Here a **false positive is a wrong-patient release** — the critical, safety-relevant
error. The framework is deliberately biased to protect precision/FPR (see verdict, §5).

### 2.2 Uncertainty — every rate is a posterior, not a point
Each rate is modeled as **`Beta(successes + 1, failures + 1)`** (uniform prior). We report
the **posterior mean** and the **95% credible interval** before and after. This answers
"is the observed change real or noise?" — the whole point of the harness.

- TPR: `Beta(TP+1, FN+1)` · FNR: `Beta(FN+1, TP+1)` · FPR: `Beta(FP+1, TN+1)` · Precision: `Beta(TP+1, FP+1)`.
- **P(candidate is better)** = posterior probability the candidate's rate is better,
  *in the correct direction* (`> before` for TPR/precision/F1, `< before` for FPR/FNR),
  estimated by sampling both posteriors (`prob_improvement`). F1 is sampled from its
  component precision/recall posteriors.
- **Inconclusive** = the 95% CrIs overlap materially, i.e. `P(better)` lands in the
  indecisive middle band (default `(0.05, 0.95)`).

> **Independence caveat (documented on purpose).** Before/after come from the *same*
> eval set and are positively correlated, so treating the two Betas as *independent*
> is **conservative** — it understates confidence in a genuine change. For recall we
> therefore also report the **paired** signal (§2.3), which is the more powerful test.

### 2.3 True-positive behavior — paired, with churn
TP behavior is compared **pair-by-pair on the same eval set** over the gold true matches,
into four buckets (`PairedRecall`):

| Bucket | Meaning |
|---|---|
| **both** | caught by baseline *and* candidate |
| **lost** | baseline caught it, candidate missed it → **new false negative** |
| **gained** | candidate caught it, baseline missed it |
| **neither** | missed by both |

- **Net recall change** = (gained − lost) / (#true matches).
- **Churn** = lost + gained. *Churn matters even when net is ~0*: a rule that trades
  known-good matches for new ones changes the **risk profile**, so `lost > 0` is always
  surfaced in the report notes.
- **Pairing-aware improvement probability** (Bayesian McNemar): among the discordant
  pairs, the fraction favoring the candidate is `Beta(gained+1, lost+1)`; the candidate
  is better iff that exceeds 0.5. A frequentist exact **McNemar p-value** is also reported.

### 2.4 How much data? (`min_sample_size`, `detectable_delta`)
`min_sample_size(p0, delta, alpha=0.05, power=0.80)` returns the labels **per arm** needed
to detect a shift of `delta` from rate `p0` (two-proportion power formula — a conservative
*upper bound*, since pairing reduces the requirement). Inverse: `detectable_delta(n, p0)`.

Worked numbers (near a 0.90 rate):

| Effect to detect | labels/arm (unpaired upper bound) |
|---|---|
| 2-point shift | ~3,200 |
| 3-point shift | ~1,400 |
| 5-point shift | ~440 |

So **~1,500–2,500 labeled true-match pairs** reliably detects a **~3-point** move; a
2-point move wants more (or relies on the paired test's extra power). When labels are
scarce, report `detectable_delta` for the count you actually have — more honest than a
fixed rule of thumb.

---

## 3. Data protocol (splitting & bias control)

### 3.1 Split
`stratified_split(pairs, holdout_frac=0.70, strata_keys=[...])` →

- **Holdout (default 70%) — the protected evaluation set.** Never used to design or tune
  rules. All before/after verdicts are computed here. When labels are scarce, the holdout
  is filled **first** (rounding up per stratum) so the eval set is protected.
- **Dev (default 30%) — for rule development/calibration** (choosing a threshold, tuning a
  blocking key). Because rules here are **deterministic (no model training)**, there is no
  classic "train" set; the dev set is the training analog.

**Why 70/30.** Deterministic rules need little dev data to design, and evaluation
precision (tight credible intervals) is the binding constraint — so we bias data toward the
holdout. If you tune on dev, you must re-report on the untouched holdout.

### 3.2 Stratification (bias control)
Sample so the eval set reflects reality on two axes:

1. **Base rate** — stratify on the gold label so the true match/non-match prevalence in
   the eval set matches production. (Skewing prevalence silently distorts precision.)
2. **Demographic / data-quality strata** — pass `strata_keys` such as `age_band`,
   `name_commonality`, and **`dob_present`**. Preserving these lets you read metrics *per
   slice* and catch a rule that helps overall but degrades on a subgroup.

Keep **hard negatives overrepresented** (similar names, shared DOBs) so non-match volume
actually stresses the rules rather than padding TN with easy cases.

### 3.3 Robustness
`kfold_metric_variance(matcher, holdout, k=5)` reports a metric's mean/std across folds — a
cheap check that a result isn't driven by a lucky slice.

### 3.4 ⚠️ CMS DOB gap (must-have stratum)
CMS-sourced records frequently **lack DOB**. Any rule that relies on DOB (most of Table 2,
and the current scorer) will behave differently on those records. **The eval set must
include a `dob_present: "no"` stratum**, and reports should be read per-stratum, so a
rule's degradation on missing-DOB records is visible *before* it ships — not discovered in
production. This is called out here because it is the most likely blind spot for the CMS
migration work.

---

## 4. The comparison report (format)

`compare()` returns a `ComparisonReport`; render it three ways:

- `format_report(report)` → plain text (no extra deps — safe in any cell / log).
- `report_to_dataframe(report)` → a pandas table (one row per metric).
- `plot_credible_intervals(report)` → a matplotlib figure (before vs after mean + 95% CrI,
  annotated with P(better)).

Example (candidate = "also trust an exact-id signal", 2,801-pair holdout):

```
metric                         before    after  P(better)  verdict
TPR (recall/sensitivity)       0.6721   0.7341      1.000  improved
FPR                            0.1034   0.1034      0.502  inconclusive
FNR                            0.3279   0.2659      1.000  improved
Precision                      0.8667   0.8766      0.758  inconclusive
F1                             0.7570   0.7990      1.000

Paired recall (true matches): both=942 lost=0 gained=87 missed_by_both=372
  net recall change = +6.2%  churn = 87  P(candidate better, paired) = 1.000

>>> OVERALL VERDICT: SHIP
```

---

## 5. Handover — how to use it

### 5.1 Add a new rule to the harness
1. Express the rule as a `Matcher` — a callable `features -> bool`:
   - **Threshold change:** `candidate = lambda f: f["score"] >= 0.94`
   - **New scoring rule:** wrap your scorer, return `score(f) >= threshold`.
   - **New blocking rule:** the predicate that decides whether a pair is even considered a
     match; same signature.
2. Make sure each `LabeledPair.features` carries whatever the rule reads.
3. Call:
   ```python
   dev, holdout = stratified_split(pairs, strata_keys=["dob_present", "name_commonality"])
   report = compare(baseline, candidate, holdout,
                    candidate_name="my-rule", primary_metric="TPR (recall/sensitivity)")
   print(format_report(report))
   ```
   Set `primary_metric` to whatever the change is *meant* to improve.

### 5.2 Interpret the report
- **Per-metric `verdict`**: `improved` (P(better) ≥ 0.95), `regressed` (≤ 0.05), else
  `inconclusive` (credible intervals still overlap → not enough evidence).
- **Paired recall**: check `lost` and `churn`, not just net. Any `lost > 0` means you are
  dropping matches the old rule caught — acceptable only if the trade is deliberate.
- **Credible intervals**: wide intervals ⇒ too little data ⇒ `NEEDS MORE DATA`, regardless
  of the point estimate.

### 5.3 Ship / reject / needs-more-data (the decision rule)
`compare()` encodes a **safety-first** policy (a false positive is the critical error):

| Verdict | Condition |
|---|---|
| **REJECT** | FPR **or** Precision *decisively regresses* (`P(better) ≤ 0.05`). A wrong-patient release risk is disqualifying regardless of recall gains. |
| **SHIP** | No safety regression **and** the `primary_metric` *decisively improves* (`P(better) ≥ 0.95`). |
| **NEEDS MORE DATA** | Anything else — the improvement (or regression) is not yet decisive; credible intervals overlap. Get more labels (use `detectable_delta` to see what your current count can resolve) or run the paired test. |

Thresholds (`ship_prob`, `reject_prob`, `primary_metric`) are parameters of `compare()` —
tune them per program, but change them deliberately and document why.

### 5.4 Guardrails
- Never compute a verdict on the **dev** set — always the untouched **holdout**.
- Re-run the harness after *any* material change to matching logic, normalization, or
  thresholds (this mirrors the CMS proposal's §VI "validate before go-live and after any
  change").
- Report **precision, recall, and FPR together** — a recall win that quietly costs
  precision is not a win here.
