# How to test a patient-matching algorithm against this dataset

This repo's generation code was originally built against the cross-org workgroup's draft
proposal, ["Proposal: A Shared Test Dataset for CMS v3.3.0 Patient Matching
Compliance"](https://docs.google.com/document/d/1N6IQkaLkKPdQKVxPSWZYDaLbTCx0EYEgwBcCCPk-6pk)
(**the draft Doc**, retained here for traceability — several session docs cite its section
numbers directly). The workgroup has since finalized its methodology as ["A Shared Test Dataset
for CMS Patient Matching Compliance —
(current)"](https://docs.google.com/document/d/1A96--dAjIwID5RCDr9qZeqDnk6snOqNcQOg1ZBy3FWw)
(**the current Doc**), which supersedes it — see
`SYNTHETIC_DATA_COMPARISON.md`'s "What changed between the draft and the finalized proposal" and
`docs/sessions/completed/session_12.md` for the full diff. Guidance below follows the current Doc.

**Provenance / synthesis-method disclosure** (the current Doc requires each contributed segment
to record how it was produced): every record in both tiers of this repo's data derives from the
public ONC 2017 Patient Matching Algorithm Challenge dataset, transformed by this repo's own
programmatic mutation/mining/construction code (`mutations.py`, `hard_negatives.py`,
`special_populations.py`, `normalization_edge_cases.py`, `population_cases.py`). No real
member-organization or client data, and no de-identification step, is involved anywhere in this
pipeline — there is nothing here to de-identify, since ONC's source data is already public and
synthetic. This repo currently has exactly one segment; if a second segment (e.g., synthetic
records derived from a member organization's real data, per the current Doc's contribution
options) is ever added here, it needs its own disclosure — a single repo-level note like this one
stops being sufficient at that point.

## How this test data was generated

### Source population

The ONC 2017 Patient Matching Algorithm Challenge dataset: 9 alphabetically-sharded CSVs,
~1,000,000 records total, public and already synthetic (`evaluation/fixtures/onc/`).
`onc_loader.py` maps its flat CSV columns to FHIR `Patient` dicts:

| ONC CSV column(s) | FHIR `Patient` field | Notes |
|---|---|---|
| `EnterpriseID` | `id` | The stable identifier every generated `case_id`/`candidate_id` is built from |
| `FIRST`, `MIDDLE`, `ALIAS` | `name[0].given` | Appended in that order, each only if present |
| `LAST` | `name[0].family` | |
| `MOTHERS_MAIDEN_NAME` | a second `name[]` entry's `family` | Not mapped by the reference matching engine's own transform — added here so normalization/matching sees prior/maiden names |
| `SUFFIX` | `name[0].suffix` | |
| `DOB` | `birthDate` | SAS-style day-offset from `1900-01-01` minus 2; decoded to an ISO date. Only set if the column is non-empty — the dataset's "Null" shard has intentionally-missing fields for incomplete-data testing, mirrored rather than raising |
| `GENDER` | `gender` | `M`/`MALE`→`male`, `F`/`FEMALE`→`female`, anything else→`unknown` |
| `PHONE`, `EMAIL` | `telecom[]` | |
| `ADDRESS1`, `ADDRESS2`, `CITY`, `STATE`, `ZIP` | `address[0]` | `ADDRESS2` appended to `line` only if present |
| `SSN` | `identifier[]` | `system: http://hl7.org/fhir/sid/us-ssn` |

Values are copied through as-is — this repo's generation pipeline does not normalize
case/punctuation. **Verified (session 12): every `EnterpriseID` across all 9 shards is unique** —
this specific vendored copy has no native duplicate-person clusters. Every true-match cluster
below is built by this repo's own generators, not looked up from ONC.

### True-match pairs — fuzzy-tolerance variants (`mutations.py`)

Single-character-edit variants of a real record — one edit per generated case, matching the CMS
spec's own definition of the fuzzy tolerance it allows (insertion, deletion, substitution,
transposition). 10 registered mutation types:

| Mutation | What it does |
|---|---|
| `dob_day` / `dob_month` / `dob_year` | Shifts the DOB component by a small random offset (±1-3 days, ±1-2 months, ±1-2 years) |
| `dob_swap` | Transposes month/day (e.g. `03/07` → `07/03`), only when both are valid as the other |
| `dob_typo` | Substitutes one digit of the `YYYYMMDD` string, re-parsed to a valid calendar date |
| `family_typo` | One random insert/delete/substitute edit on the family name |
| `family_transpose` | Swaps one adjacent character pair in the family name |
| `family_drop_letters` | Drops ~20% of the family name's letters |
| `given_nickname` | Substitutes the given name with a known nickname/diminutive (e.g. "Katherine" → "Kate", via the `nicknames` library) |
| `given_abbreviate` | Reduces the given name to its first initial (e.g. "William" → "W.") |

### True-match pairs — normalization edge cases (`normalization_edge_cases.py`)

Two more true-match variant generators, but exercising a different requirement: CMS SS V.A
requires normalization to fold these into a byte-identical match, not just fuzzy-tolerance-close.

- **`diacritic_variant`** — replaces a foldable Latin letter with its accented form (a→á, e→é,
  i→í, o→ó, u→ú, n→ñ, c→ç), e.g. "Nunez" → "Nuñez".
- **`punctuation_variant`** — inserts one hyphen/apostrophe/period/doubled-space into a name, e.g.
  "OBrien" → "O'Brien".

(A third edge case, placeholder/out-of-range DOB, is a single-patient normalization behavior, not
a pair, so it isn't represented in this dataset's pair/pool format.)

### True-non-match pairs — mined hard negatives (`hard_negatives.py`, `special_populations.py`)

Never generated by mutating a record — that would only test a matcher's own fuzzy tolerance, not
reality. Always two genuinely distinct real ONC records instead:

- **General hard negatives** — distinct-ID pairs sharing postal code + DOB but a *different*
  family name (a coincidental collision, blocked by `(postalCode, birthDate)` for O(n) mining).
- **Multi-generational households** — distinct-ID pairs sharing postal code + family name, with
  birth years ≥15 years apart (a parent/child pattern, not the same person or twins).
- **Institutional negatives** (8 categories: shelter, nursing facility, correctional institution,
  hotel/short-term housing, halfway house, dormitory, group home, migrant camp) — ONC has no
  column marking institutional residency, so these are *constructed*: 3 already-mutually-distinct
  real ONC identities (different family name, different ID — never fabricated) have only their
  address overwritten with one of 8 fixed synthetic addresses per type; every pairwise combination
  becomes a true-non-match case. Each fabricated address carries an unambiguous "SYNTHETIC TEST
  ADDRESS" line and a reserved `00001`–`00008` ZIP block, so it's recognizable at a glance.
- **Literal twins are deliberately never constructed** — CMS spec §IV.G itself acknowledges this
  case can't be resolved through field matching alone, so it isn't a valid "should not match" test
  case.

### Assembly, export, and reproducibility

- **`labeled_pairs.py`**'s `generate_raw_pairs()` combines all of the above into
  `(source, target, is_true_match)` triples — the shared generation core everything else builds
  on. It runs on **one shared `random.Random(seed)` instance** (default `seed=0`), consumed in a
  fixed order (fuzzy variants → normalization edge cases → hard negatives → households →
  institutional pairs per type), so a given `seed` always reproduces the same output byte-for-byte
  given the same input patients.
- **Every case gets a stable, self-describing id**, built from the ONC `EnterpriseID`(s)
  involved: `{id}::{mutation_type}` for a fuzzy variant (e.g. `14065387::family_transpose`),
  `{id}::diacritic` / `{id}::punctuation` for normalization edge cases, `{query_id}::{candidate_id}`
  for a mined hard negative, `{query_id}::{candidate_id}::household` for a mined household pair,
  and `{query_id}::{candidate_id}::{institution_type}` for a constructed institutional pair.
- **Every case gets a `rationale` string** built by `format_rationale()`: the pair's category plus
  its most specific subtype as `<pair_type>/<subtype>` (e.g. `fuzzy_variant/dob_day`,
  `special_population/shelter`), with any remaining context (e.g. `postalCode=...,
  birthDate=...` for a hard negative) appended as `key=value` pairs, sorted for determinism.
- **`export_test_dataset.py`** materializes these as the per-provision pairs manifest
  (`sample_labeled_pairs.jsonl`), pairing each `case_id`/`rationale` with an optional real-world
  frequency weight (see below).
- **`population_cases.py`**'s `build_population_dataset()` regroups the same underlying generation
  logic into the population-query shape, using two independent RNGs so topping up a pool with
  random distractors never perturbs the same random stream used to generate variants: a
  query's **known-match cluster** is its own fuzzy-variant/normalization-edge-case candidates
  (added to its pool first, so trimming logic below can never drop them); its **decoy pool** is
  its mined hard-negative/household/institutional candidates, deduplicated against a per-query
  "already in this pool" set. If the pool is still under `pool_size` (default 40) after that, it's
  topped up with randomly-shuffled distractors from the rest of the sample; if it's over, only
  decoys are trimmed — true matches are never dropped to make room. Institutional decoys are
  namespaced as `{candidate_id}::institutional::{institution_type}` in the shared candidate
  registry specifically so they don't collide with that same person's plain, address-intact record
  if it's also used as a distractor elsewhere. **`export_population_dataset.py`** writes the result
  as `population_queries.jsonl`/`population_candidates.jsonl`.
- Every export defaults to **one ONC shard, sampled down to `SAMPLE_SIZE`** (2,000 patients) —
  loading and transforming the full ~1,000,000-record dataset at once has crashed a cluster
  before; see `SYNTHETIC_DATA_SETUP.md`'s "Memory & scale" section before raising this.
- Fully reproducible given the same seed/inputs — regenerate any committed file with the commands
  in "Regenerating or extending this file" below.

### Frequency weighting (`prevalence_estimates.py`)

`build_test_case_records()` takes a `frequency_lookup(rationale) -> float` callable and stamps its
result onto each record's `frequency` field. Two lookups exist: `uniform_frequency()` (the
neutral default — every case weighted `1.0`, i.e. no real-world weighting) and
`researched_frequency()`, which maps each `rationale` prefix to a real, cited public-source
prevalence estimate — e.g. shelter residency (~0.06% of the population, U.S. Census Bureau) vs.
nursing-facility residency (~0.49%) — or an explicit "no public estimate found" placeholder pinned
to a neutral value, never a guessed number. **The committed `sample_labeled_pairs.jsonl` was
generated with `researched_frequency()`** (pending maintainer review, not yet treated as final);
pass `frequency_lookup=uniform_frequency` to `build_test_case_records()` if you want every case
weighted equally instead. See "Frequency and real-world representativeness" below for how (and
how not) to use this field.

`sample_labeled_pairs.jsonl` (and any file generated the same way via
`evaluation/export_test_dataset.py`) is a portable, algorithm-agnostic test-case manifest, per
the current Doc's per-provision pair format and the draft Doc's Design Principle 1 (unchanged by
finalization): every test case is a pair of standard FHIR `Patient` resources plus an expected
outcome — nothing about the format assumes any particular matching implementation. This means
**any** matching algorithm can be tested against it — as of session 13, this repo doesn't depend
on or test any specific matching engine itself; it only produces the data.

**Case/punctuation, read before comparing exact strings:** field values carry whatever case and
punctuation the ONC CSVs used (session 13 dropped this repo's own normalization step from
generation - see session_13.md). Apply your own normalization convention before comparing fields,
the same way you would for any other input.

## Two test tiers

The current Doc names two distinct test kinds, and this repo now builds both:

| Tier | Files | Shape | Valid metrics |
|---|---|---|---|
| **Per-provision pairs** | `sample_labeled_pairs.jsonl` (`evaluation/export_test_dataset.py`) | One `(source, target)` pair per spec provision, deliberately over-sampling rare/high-risk categories for statistical power. | Recall, FPR. **Not** precision, FDR, F1, or accuracy — see "Frequency and real-world representativeness" below. |
| **Population query** | `population_queries.jsonl` + `population_candidates.jsonl` (`evaluation/export_population_dataset.py`) | One query patient per row, against a candidate pool (default 40), with an `expected_match_ids` set — possibly empty, possibly several. Naturally representative: each pool mixes a query's real duplicate cluster with a broad, mostly-random sample of the rest of the population, not a curated rare-case selection. | Precision, recall, FPR, FDR, F1, accuracy. |

Pairs answer "does this algorithm correctly implement this specific spec provision" — the
per-provision suite is *supposed* to be unrealistic (over-sampling twins, shelters, and other
rare high-risk categories on purpose) so that rare-but-critical cases get enough statistical
power. Population queries answer "when this algorithm searches a real-shaped population, does it
return the right people" — the harder, more realistic FHIR `Patient/$match` shape the current Doc
calls out: *"the genuinely hard failure is picking a plausible wrong candidate out of forty
near-misses. Pairs can express neither."*

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

## Population-query file format

Two JSON Lines files, split so a candidate shared across multiple queries' pools isn't repeated:

`population_candidates.jsonl` — one row per unique candidate:

```json
{"id": "14065387::family_transpose", "patient": { "resourceType": "Patient", "...": "..." }}
```

`population_queries.jsonl` — one row per query:

```json
{
  "query_id": "14065387",
  "query": { "resourceType": "Patient", "...": "..." },
  "candidate_ids": ["14065387::family_transpose", "14065387::diacritic", "12311897", "..."],
  "expected_match_ids": ["14065387::family_transpose", "14065387::diacritic"],
  "rationale": "population/fuzzy_variant+normalization_edge_case"
}
```

| Field | Meaning |
|---|---|
| `query_id` | The query patient's id. |
| `query` | The query/"Outside Record" FHIR `Patient` resource. |
| `candidate_ids` | Every candidate in this query's pool (default up to 40) — resolve each against `population_candidates.jsonl`. |
| `expected_match_ids` | The subset of `candidate_ids` that are the same person as the query — **possibly empty** (a query with no known duplicate in the pool is a real, intentional case, not a bug). |
| `rationale` | Which generation categories contributed to this pool. |

A candidate id with no `::` suffix is a real, unmodified ONC record (either the query's own
population co-member, used as a distractor, or a mined hard-negative/household decoy). A `::`
suffix marks a generated variant (`::family_transpose`, `::diacritic`, `::punctuation`, one of
`mutations.MUTATIONS`' keys) or a constructed special-population candidate
(`::institutional::<type>`, whose `address` is a fabricated, unambiguously-synthetic institutional
address per `special_populations.py` — the underlying identity is still a real, distinct ONC
record). **Known simplification, read before treating this tier as equivalent to
`labeled_pairs.py`'s institutional pairs:** `special_populations.construct_institutional_negatives()`
fabricates the same address on *both* sides of a pair; this tier only injects the fabricated side
into the decoy pool, so the query here keeps its real address. See `population_cases.py`'s module
docstring for why.

## Frequency and real-world representativeness

**The number of cases in each `rationale` category is an artifact of how this file was
generated, not a signal about how often that scenario occurs in the real world.** For example,
`normalization_edge_case` cases are 64% of this file because the generator emits exactly one
diacritic and one punctuation variant per source patient — not because accented or hyphenated
names are that common. Conversely, `hard_negative` has only 4 cases because that's how many
coincidental ZIP+DOB collisions happened to occur in a 2,000-patient sample — not because that
scenario is rare in reality. **Do not compute an aggregate "expected real-world accuracy" number
by weighting categories according to their raw counts in this file.**

The draft Doc flagged this as an open, unresolved methodology question (§1: "Maintain frequency
of use cases per real world datasets") and separately (§5) warned against the naive fix of just
reshaping the curated dataset to mirror real-world prevalence — doing so would make
rare-but-high-risk categories (e.g., shared institutional addresses) nearly disappear from the
test set, undermining the whole point of testing them deliberately. **The current Doc resolves
this differently than this repo originally did:** rather than reweighting the curated suite via a
per-category frequency multiplier, compute precision, recall, FDR, and FPR "only over the
realistic population" — i.e., over a second, naturally-representative tier, not the curated one.
That's exactly what the population-query tier above is for.

**Practical guidance, current as of session 12:**

- **Recall and FPR** are valid on `sample_labeled_pairs.jsonl` as-is — over-sampling rare
  categories doesn't distort them, since both are computed within the true-match or
  true-non-match population respectively, not across the mixed base rate.
- **Precision, FDR, F1, and accuracy** — compute these over `population_queries.jsonl`/
  `population_candidates.jsonl` instead. Computing them over the curated per-provision suite
  produces a number with no real-world interpretation, because the suite's should-match /
  should-not-match ratio is a generation-parameter artifact, not a real base rate.
- The `frequency` field below remains useful **documentation/analysis metadata** (e.g., "how rare
  is this scenario really") — it is not, and was never meant to be, a substitute for computing
  precision-family metrics over an actually-representative sample. Don't use it to compute a
  weighted precision estimate from the curated suite; use the population tier instead.

**Current state: `evaluation/prevalence_estimates.py` supplies real, publicly-sourced estimates
for some categories — pending maintainer review, not yet treated as final.** The committed
`sample_labeled_pairs.jsonl` was regenerated using these estimates (via
`export_test_dataset.py`'s `__main__`, `frequency_lookup=researched_frequency`). Pass
`frequency_lookup=uniform_frequency` (or call `build_test_case_records()` with no
`frequency_lookup` argument) if you want every case weighted equally instead.

Every entry in `prevalence_estimates.PREVALENCE_ESTIMATES` is either a real, cited public-source
estimate, or an explicit `has_public_estimate=False` placeholder pinned to `1.0` — never a
guessed number standing in for real data. Sources are exclusively public (U.S. Census Bureau,
CDC/NCHS, Pew Research Center, peer-reviewed record-linkage literature) — no member-organization
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
fdr = fp / (fp + tp) if (fp + tp) else float("nan")
print(f"precision={precision:.4f} recall={recall:.4f} fpr={fpr:.4f} fdr={fdr:.4f}  (n={tp+fp+tn+fn})")
```

**On this file specifically, only trust `recall` and `fpr` from the numbers above** — `precision`
and `fdr` are shown for completeness of the formula, but computing them over this curated,
rare-case-oversampling suite has no real-world interpretation (see "Frequency and real-world
representativeness" above). Compute `precision`/`fdr` over `population_queries.jsonl` instead
(see "Option B" below).

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

## Option B: computing precision/FDR/F1/accuracy over the population tier

This is where the metrics `sample_labeled_pairs.jsonl` can't validly produce actually come from.
Load the candidate registry once, then score each query against its own pool:

```python
import json

candidates = {}
with open("evaluation/cases/population_candidates.jsonl") as f:
    for line in f:
        row = json.loads(line)
        candidates[row["id"]] = row["patient"]

tp = fp = tn = fn = 0
with open("evaluation/cases/population_queries.jsonl") as f:
    for line in f:
        query_case = json.loads(line)
        expected = set(query_case["expected_match_ids"])
        for candidate_id in query_case["candidate_ids"]:
            predicted_match = my_algorithm(query_case["query"], candidates[candidate_id])
            actual_match = candidate_id in expected
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
fdr = fp / (fp + tp) if (fp + tp) else float("nan")
accuracy = (tp + tn) / (tp + fp + tn + fn) if (tp + fp + tn + fn) else float("nan")
print(f"precision={precision:.4f} recall={recall:.4f} fpr={fpr:.4f} fdr={fdr:.4f} accuracy={accuracy:.4f}")
```

This flattens every (query, candidate) evaluation in every pool into the same four buckets as
Option A/B — the population tier's realism comes from *how the pools were built* (mostly random
distractors, not curated rare cases), not from a different scoring shape. The same not-applicable
disclosure requirement applies here too: report how many (query, candidate) evaluations your
algorithm could actually attempt vs. skipped.

## What this dataset does *not* tell you

- **Real-world collision probability at population scale.** Even the population tier's pools
  (default 40 candidates) are far short of the current/draft Doc's ≥1,000,000-record empirical
  collision-rate validation — a different, larger exercise entirely (tracked as a candidate future
  session, not yet built). The population tier tells you whether your algorithm picks the right
  candidate out of a realistic-sized pool, not the population-wide collision probability of a
  field combination.
- **Administrative-restriction or insurance-identifier coverage.** Those categories aren't in
  either tier yet — see `docs/sessions/pending/session_11.md` (blocked on session_6).
- **Literal-twin behavior.** Deliberately excluded — see `special_populations.py`'s module
  docstring and `session_10.md`'s "Out of scope".

## Regenerating or extending this file

```
PYTHONPATH=. python evaluation/export_test_dataset.py
PYTHONPATH=. python evaluation/export_population_dataset.py
```

Same `SAMPLE_SIZE`/`OUTPUT_PATH` env-var overrides as `evaluation/labeled_pairs.py` — read
`SYNTHETIC_DATA_SETUP.md`'s "Memory & scale" section before raising `SAMPLE_SIZE` or passing more
than one ONC shard's worth of patients.
