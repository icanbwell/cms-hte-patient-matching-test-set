# How to test a patient-matching algorithm against this dataset

`sample_labeled_pairs.jsonl` (and any file generated the same way via
`evaluation/export_test_dataset.py`) is a portable, algorithm-agnostic test-case manifest, per
the cross-org workgroup Google Doc's (["Proposal: A Shared Test Dataset for CMS v3.3.0 Patient
Matching Compliance"](https://docs.google.com/document/d/1N6IQkaLkKPdQKVxPSWZYDaLbTCx0EYEgwBcCCPk-6pk))
Section 3 format and Design Principle 1: every test case is a pair of standard FHIR `Patient`
resources plus an expected outcome — nothing about the format assumes any particular matching
implementation. This means **any** matching algorithm (this repo's, or a completely different
organization's) can be tested against it, not just `patient-matching`'s own engine.

## The file format

One JSON object per line (JSON Lines / `.jsonl`):

```json
{
  "case_id": "14065387::family_transpose",
  "source": { "resourceType": "Patient", "...": "..." },
  "target": { "resourceType": "Patient", "...": "..." },
  "expected_match": true,
  "rationale": "fuzzy_variant/family_transpose"
}
```

| Field | Meaning |
|---|---|
| `case_id` | Stable identifier for this case. |
| `source` | The "Outside Record" / query FHIR `Patient` resource. |
| `target` | The "Internal Record" / candidate FHIR `Patient` resource. |
| `expected_match` | The gold label — `true` if `source` and `target` represent the same person. |
| `rationale` | Which category/provenance this case traces to (e.g. `fuzzy_variant/dob_day`, `hard_negative`, `special_population/shelter`, `normalization_edge_case/diacritic`) — per Design Principle 2, every case traces to a specific reason, not a black box. See `SYNTHETIC_DATA_COMPARISON.md`'s "Coverage against the Doc's §2 ground-truth pair categories" for what each `rationale` prefix means. |
| `frequency` | A relative real-world-prevalence weight for this case's category — **currently `1.0` for every case** (uniform), meaning no real-world weighting has been applied yet. See "Frequency and real-world representativeness" below before using this field or the file's raw per-category case counts to infer anything about real-world prevalence. |

**Data provenance, read before trusting a result:** every `source`/`target` pair here is either a
real ONC 2017 Patient Matching Algorithm Challenge record (a public, synthetic, non-PHI dataset —
see `evaluation/fixtures/onc/`) or a same-record mutation of one. `special_population`
institutional-category pairs additionally carry a **fabricated address**, deliberately marked as
synthetic (`"SYNTHETIC TEST ADDRESS"` in the address line, a reserved `000xx` ZIP block) — see
`evaluation/special_populations.py`'s module docstring for exactly which fields are real vs.
constructed, per case category.

## Frequency and real-world representativeness

**The number of cases in each `rationale` category is an artifact of how this file was
generated, not a signal about how often that scenario occurs in the real world.** For example,
`normalization_edge_case` cases are 64% of this file because the generator emits exactly one
diacritic and one punctuation variant per source patient — not because accented or hyphenated
names are that common. Conversely, `hard_negative` has only 4 cases because that's how many
coincidental ZIP+DOB collisions happened to occur in a 2,000-patient sample — not because that
scenario is rare in reality. **Do not compute an aggregate "expected real-world accuracy" number
by weighting categories according to their raw counts in this file.**

The workgroup Doc itself flags this as an open, unresolved methodology question (§1: "Maintain
frequency of use cases per real world datasets," "Make sure the test dataset follows the real
world frequency so metrics are relevant to distribution"), and separately (§5) warns against the
naive fix of just reshaping the curated dataset to mirror real-world prevalence — doing so would
make rare-but-high-risk categories (e.g., shared institutional addresses) nearly disappear from
the test set, undermining the whole point of testing them deliberately.

This repo's approach: keep the file's raw case counts driven by what's needed for statistical
power per category (see the discussion above), and carry real-world prevalence as **separate
metadata** — the `frequency` field — that a consumer can use to compute a prevalence-weighted
aggregate metric without needing the file itself to mirror real-world proportions.

**Current state: `evaluation/prevalence_estimates.py` supplies real, publicly-sourced estimates
for some categories — pending Imran's review, not yet treated as final.** The committed
`sample_labeled_pairs.jsonl` was regenerated using these estimates (via
`export_test_dataset.py`'s `__main__`, `frequency_lookup=researched_frequency`). Pass
`frequency_lookup=uniform_frequency` (or call `build_test_case_records()` with no
`frequency_lookup` argument) if you want every case weighted equally instead.

Every entry in `prevalence_estimates.PREVALENCE_ESTIMATES` is either a real, cited public-source
estimate, or an explicit `has_public_estimate=False` placeholder pinned to `1.0` — never a
guessed number standing in for real data. Sources are exclusively public (U.S. Census Bureau,
CDC/NCHS, Pew Research Center, peer-reviewed record-linkage literature) — no b.well/WellSense
client data, per this backlog's Option A+B-only scoping.

| Category | `frequency` | Source | Direct measurement? |
|---|---:|---|:---:|
| `special_population/shelter` | 0.0006 | U.S. Census Bureau, "The Emergency and Transitional Shelter Population: 2020" (2024) | Yes |
| `special_population/nursing_facility` | 0.0049 | U.S. Census Bureau, 2020 Census Group Quarters release (2021) | Yes |
| `special_population/correctional_institution` | 0.0059 | U.S. Census Bureau, 2020 Census Group Quarters release (2021) | Yes |
| `special_population/dormitory` | 0.0084 | U.S. Census Bureau, 2020 Census Group Quarters release (2021) | Yes |
| `special_population/multi_generational_household` | 0.18 | Pew Research Center, "The Demographics of Multigenerational Households" (2022) | Yes |
| `normalization_edge_case/diacritic` | 0.20 | U.S. Census Bureau population estimates (2024) — Hispanic/Latino population share | **No — proxy** |
| `normalization_edge_case/punctuation` | 0.06 | Gooding & Kreider (U.S. Census Bureau), "Women's Marital Naming Choices in a Nationally Representative Sample" | **No — proxy, married women only** |
| `special_population/hotel_short_term_housing`, `halfway_house`, `group_home`, `migrant_camp` | 1.0 (placeholder) | U.S. Census Bureau, 2020 Census Group Quarters release (2021) | **No public split exists** — bundled into an undifferentiated ~0.35%-of-population catch-all with no further breakdown |
| `fuzzy_variant/*` (all 10 mutation types) | 1.0 (placeholder) | Zech et al. 2016; Pew Charitable Trusts 2018 | **No public per-edit-type rate exists** — only coarser, downstream match-failure rates are published |
| `hard_negative` | 1.0 (placeholder) | N/A | Not a demographic prevalence question — governed by this repo's own P(collision) framework instead |

**Read `prevalence_estimates.py`'s per-entry `notes` before trusting any of these** — several
carry real caveats (the diacritic and punctuation estimates are proxies for a related-but-not-
identical population, not direct measurements of the thing being tested) that matter for how
much weight to put on them.

## Option A: bring your own algorithm (any language, any organization)

Per the Doc's Section 6, the only thing your algorithm needs to satisfy is a minimal adapter
contract: given two FHIR `Patient` documents, decide match or no-match. You do not need to adopt
Python, this repo's data model, or any of its tooling.

1. Read the file one line at a time (don't load the whole thing into memory unless you know it's
   small — this sample is 6,289 lines / ~6MB, but a larger export could be much bigger).
2. For each line, parse the JSON and hand `source`/`target` to your algorithm exactly as you
   would any two records from your own system.
3. Compare your algorithm's answer to `expected_match` and tally into the four buckets below.
4. Compute metrics from the tallies (not per-case, and not by averaging per-case percentages).

```python
import json

tp = fp = tn = fn = 0
with open("evaluation/cases/sample_labeled_pairs.jsonl") as f:
    for line in f:
        case = json.loads(line)
        predicted_match = my_algorithm(case["source"], case["target"])  # <- your code here
        actual_match = case["expected_match"]
        if predicted_match and actual_match:
            tp += 1
        elif predicted_match and not actual_match:
            fp += 1
        elif not predicted_match and actual_match:
            fn += 1
        else:
            tn += 1

precision = tp / (tp + fp) if (tp + fp) else float("nan")
recall = tp / (tp + fn) if (tp + fn) else float("nan")
fpr = fp / (fp + tn) if (fp + tn) else float("nan")
print(f"precision={precision:.4f} recall={recall:.4f} fpr={fpr:.4f}  (n={tp+fp+tn+fn})")
```

**Report broken out by `rationale`, not just as one aggregate number** — per the Doc's Section 5:
this dataset is a curated set of specific spec provisions and edge cases, not a random sample of
real-world pairs, so a single blended accuracy/precision number across the whole file conflates
categories your algorithm handles well with categories it doesn't. Group by the `rationale`
prefix (before the `/`) at minimum, ideally by the full `rationale` string:

```python
from collections import defaultdict

buckets = defaultdict(lambda: {"tp": 0, "fp": 0, "tn": 0, "fn": 0})
# ... inside the loop above, additionally:
category = case["rationale"].split("/")[0].split(" ")[0]  # e.g. "fuzzy_variant", "hard_negative"
bucket = buckets[category]
bucket["tp" if predicted_match and actual_match else
       "fp" if predicted_match and not actual_match else
       "fn" if not predicted_match and actual_match else
       "tn"] += 1
```

Also report **how many cases your algorithm could actually evaluate vs. skipped as
not-applicable** (e.g. it requires a field a given `Patient` doesn't have populated) — per the
Doc's Section 5, this is mandatory, not optional: an algorithm that silently skips its hardest
cases and reports metrics only over what it did attempt can look stronger than one that honestly
attempted everything.

## Option B: testing this repo's own `MatchingEngine` against the dataset

Since `patient-matching`'s engine already speaks the same FHIR `Patient` shape, you can run it
against this dataset directly without writing an adapter:

```python
import json

from patient_matching.matching.field_extractor import FieldExtractor
from patient_matching.matching.matching_engine import MatchingEngine
from patient_matching.matching.backend import MatchingBackend
from patient_matching.normalization.manager import NormalizationManager


class _NoopBackend(MatchingBackend):
    """evaluate_pair() below doesn't use backend search - only needed to
    satisfy MatchingEngine's constructor."""

    def search(self, criteria):
        return []


normalizer = NormalizationManager()
extractor = FieldExtractor()
engine = MatchingEngine(backend=_NoopBackend())

tp = fp = tn = fn = 0
with open("evaluation/cases/sample_labeled_pairs.jsonl") as f:
    for line in f:
        case = json.loads(line)
        source_fields = extractor.extract(normalizer.normalize(case["source"]))
        target_fields = extractor.extract(normalizer.normalize(case["target"]))
        predicted_match = engine.evaluate_pair(source_fields, target_fields)
        actual_match = case["expected_match"]
        if predicted_match and actual_match:
            tp += 1
        elif predicted_match and not actual_match:
            fp += 1
        elif not predicted_match and actual_match:
            fn += 1
        else:
            tn += 1

print(f"TP={tp} FP={fp} TN={tn} FN={fn}")
```

`MatchingEngine.evaluate_pair()` is the pairwise decision function (no backend search, no
uniqueness check) — the same one `evaluation/onc_baseline.py` uses for its own self-match
baseline. This is a reasonable smoke test that the engine's current rule set handles this
dataset sanely, but it is **not** a substitute for `evaluation/rule_eval.py`'s
`compare()`/`ComparisonReport` machinery (Beta-posterior credible intervals, stratified
before/after comparison) — use `rule_eval.py` directly for anything that needs statistical rigor
(e.g. deciding whether a rule change is safe), per `docs/sessions/conventions.md`'s statistical
rigor gate.

## What this dataset does *not* tell you

- **Real-world collision probability.** This file tests whether your algorithm classifies
  specific, curated pairs correctly. It says nothing about how often two genuinely distinct
  people share a given field combination in a real population — that's the Doc's Section 4
  empirical collision-rate validation, a different exercise entirely (tracked as a candidate
  future session in `docs/sessions/index.md`, not yet built).
- **Administrative-restriction or insurance-identifier coverage.** Those categories aren't in
  this sample yet — see `docs/sessions/pending/session_11.md` (blocked on session_6).
- **Literal-twin behavior.** Deliberately excluded — see `special_populations.py`'s module
  docstring and `session_10.md`'s "Out of scope".

## Regenerating or extending this file

```
PYTHONPATH=. python evaluation/export_test_dataset.py
```

Same `SAMPLE_SIZE`/`OUTPUT_PATH` env-var overrides as `evaluation/labeled_pairs.py` — read
`SYNTHETIC_DATA_SETUP.md`'s "Memory & scale" section before raising `SAMPLE_SIZE` or passing more
than one ONC shard's worth of patients.
