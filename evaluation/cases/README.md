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
| `PHONE`, `PHONE2`, `EMAIL` | `telecom[]` | `PHONE2` (session 14) is only ~15.1% populated in the vendored shard |
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
| `dob_swap` | Transposes month/day (e.g. `03/07` → `07/03`), only when both are valid as the other. A random fuzzy-variant draw never returns an unchanged patient (see below), so every `dob_swap`-labeled pair has a real transposition. Before this, a draw for a patient whose DOB can't be transposed emitted a pair labeled `dob_swap` with an unchanged DOB (128 of 180 standalone swap pairs in 0.0.3) |
| `dob_typo` | Substitutes one digit of the `YYYYMMDD` string, re-parsed to a valid calendar date |
| `family_typo` | One random insert/delete/substitute edit on the family name |
| `family_transpose` | Swaps one adjacent character pair in the family name |
| `family_drop_letters` | Drops ~20% of the family name's letters |
| `given_nickname` | Substitutes the given name with a known nickname/diminutive (e.g. "Katherine" → "Kate", via the `nicknames` library) |
| `given_abbreviate` | Reduces the given name to its first initial (e.g. "William" → "W.") |

**Every standalone fuzzy-variant pair differs from its source.** The mutation type is drawn at random, and a type that does nothing on that patient (a swap on a DOB that can't be transposed, a nickname for a name with none, a `dob_typo` digit that lands on an invalid date, a transposition of two identical letters) is retried, then replaced by another type. A patient nothing applies to (no DOB and no usable name) gets no fuzzy-variant pair. Before this, those draws were emitted unchanged under their label: in 0.0.3, 128 of 180 `dob_swap`, 104 of 195 `given_nickname`, 41 of 148 `dob_typo` and 21 of 184 `family_transpose` standalone pairs were identical to their source, so each category's recall was overstated (an exact copy always matches) and its real cases were under-sampled. An explicit `mutation_type` request is applied once and may still no-op.

### True-match pairs — normalization edge cases (`normalization_edge_cases.py`)

Two more true-match variant generators, but exercising a different requirement: CMS SS V.A
requires normalization to fold these into a byte-identical match, not just fuzzy-tolerance-close.

- **`diacritic_variant`** — replaces a foldable Latin letter with its accented form (a→á, e→é,
  i→í, o→ó, u→ú, n→ñ, c→ç), e.g. "Nunez" → "Nuñez".
- **`punctuation_variant`** — inserts one hyphen/apostrophe/period/doubled-space into a name, e.g.
  "OBrien" → "O'Brien".

(A third edge case, placeholder/out-of-range DOB, is a single-patient normalization behavior, not
a pair, so it isn't represented in this dataset's pair/pool format.)

### True-match pairs — compound variants and scenario-specific mutators (`mutations.py`, session 14)

Four more true-match generators added in response to the 2026-09-22 CMS Patient Matching
workgroup's feedback that every prior true-match pair was "an exact copy with only one field
changed":

- **`generate_compound_variant`** — applies 2-3 independently-chosen mutators from the fuzzy-edit
  table above to the same variant, so a single pair can differ in name *and* DOB at once, not just
  one field. `generate_fuzzy_variant` itself is unchanged.
- **`ssn_dropped_variant`** — one side of the pair has its SSN identifier removed, modeling a
  record where only one of two on-file copies carries a Social Security Number.
- **`marriage_variant`** — swaps in the record's second `name` entry (ONC's `MOTHERS_MAIDEN_NAME`,
  loaded as a pre-marriage surname proxy) and replaces the address with an unrelated real ONC
  record's address, modeling a marriage-driven surname + address change together. Only ~5.3% of
  the vendored ONC shard carries a second `name` entry, so this category's yield is intentionally
  small — not a bug, and no-op (skipped, not emitted) for records without one.
- **`phone_variant`** — swaps to the record's second phone number (ONC's `PHONE2` column,
  loaded by `onc_loader.py` starting session 14), modeling two genuinely different on-file phone
  numbers for one person. Only ~15.1% of the vendored ONC shard carries a `PHONE2` value — and of
  those, ~70% duplicate `PHONE` verbatim (also a no-op, since swapping two identical numbers isn't
  a "different phone number" scenario), so the real usable yield is closer to ~5%. This category's
  yield is intentionally small, and no-op (skipped) records don't emit a pair.
  ONC has no phone `use` (home/mobile) semantic, so this does not fabricate
  a FHIR `ContactPoint.use` value.

### True-non-match pairs — mined hard negatives (`hard_negatives.py`, `special_populations.py`)

Never generated by mutating a record — that would only test a matcher's own fuzzy tolerance, not
reality. Always two genuinely distinct real ONC records instead:

- **General hard negatives** — distinct-ID pairs sharing postal code + DOB but a *different*
  family name (a coincidental collision, blocked by `(postalCode, birthDate)` for O(n) mining).
- **Multi-generational households** — distinct-ID pairs sharing a street address and family name,
  with birth years ≥15 years apart (a parent/child pattern). ONC addresses are near-unique, so
  in the committed sample all household pairs are *constructed* (the mined same-street path yields
  none here; it remains for inputs with co-resident records): a real younger same-surname record
  is given the elder's real address (identities unchanged, tagged `address_source=constructed` in
  the rationale). Each constructed pair is its family's smallest-gap (≥15 years) eligible pair,
  i.e. the closest available approximation of a parent/child.
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
- **Sibling negatives** (session 14, `mine_sibling_negatives`) — distinct-ID pairs sharing postal
  code + family name, with different first names and birth years ≤3 years apart (the near-DOB case the
  multi-generational-household miner's ≥15-year gap deliberately excludes) — a proxy for
  siblings/twins, since ONC has no family-relationship column. **The 4-14 year gap between these
  two miners is a deliberate, currently-unclaimed dead zone** — a same-surname, same-ZIP pair in
  that range is genuinely ambiguous between "siblings with a wide age gap" and "parent/child with a
  young parent", and neither miner claims it rather than guessing. Not yet resolved as a workgroup
  decision.
- **Name-collision negatives** (session 14, `mine_name_collision_negatives`) — distinct-ID pairs
  with a near-identical full name (edit distance ≤1, blocked by family-name first letter) but
  **no** shared postal code or DOB — targets matchers that over-weight name similarity alone with
  no corroborating field.

Every non-match pair is checked with `identity_guard.is_possible_same_person`; none may share a
real SSN or first+family+DOB.

### Assembly, export, and reproducibility

- **`labeled_pairs.py`**'s `generate_raw_pairs()` combines all of the above into
  `(source, target, is_true_match)` triples — the shared generation core everything else builds
  on. It runs on **one shared `random.Random(seed)` instance** (default `seed=0`), consumed in a
  fixed order (per patient: fuzzy variant → normalization edge cases → compound variant →
  ssn_dropped → marriage_variant → phone_variant; then, across all patients: hard negatives →
  name-collision negatives → households → sibling negatives → institutional pairs per type). The
  session-15 registry scenarios (`surname_change`, `address_move`, `phone_churn`, `email_churn`,
  `placeholder`, `gender_drift`) do not draw from that stream: each uses its own RNG seeded by
  `(seed, scenario name, patient id)`, and the placeholder-collision negatives are built after the
  existing categories. A given `seed` therefore reproduces the same generator output byte-for-byte
  given the same input patients. This applies to the generators, not to the committed files (see the note at the end of
  this section).
- **Every case gets a stable, self-describing id**, built from the ONC `EnterpriseID`(s)
  involved: `{id}::{mutation_type}` for a fuzzy variant (e.g. `14065387::family_transpose`),
  `{id}::diacritic` / `{id}::punctuation` for normalization edge cases,
  `{id}::compound::{mutation_types}` for a compound variant, `{id}::ssn_dropped` /
  `{id}::marriage_variant` / `{id}::phone_variant` for those session-14 scenarios,
  `{id}::surname_change` / `{id}::address_move` / `{id}::phone_churn` / `{id}::email_churn` /
  `{id}::placeholder` / `{id}::gender_drift` for the session-15 drift scenarios,
  `{a}::{b}::placeholder_{field}` for a placeholder-collision negative (two distinct people
  sharing a dummy SSN, phone or DOB),
  `{query_id}::{candidate_id}` for a mined hard negative,
  `{query_id}::{candidate_id}::name_collision` for a mined name-collision negative,
  `{query_id}::{candidate_id}::household` for a mined household pair,
  `{query_id}::{candidate_id}::household_constructed` for a constructed household pair,
  `{query_id}::{candidate_id}::sibling` for a mined sibling negative, and
  `{query_id}::{candidate_id}::{institution_type}` for a constructed institutional pair.
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
  query's **known-match cluster** is its own fuzzy-variant, normalization-edge-case, compound and
  registry-scenario (drift) candidates
  (added to its pool first, so trimming logic below can never drop them); its **decoy pool** is
  its mined hard-negative/household/sibling/name-collision/institutional candidates, deduplicated against a per-query
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
- The generators are reproducible given the same seed/inputs, and the commands in "Regenerating
  or extending this file" below re-run them. **The committed files are curated snapshots, not
  byte-for-byte regenerable outputs:**
  1. The committed positives were hand-filtered by BAI-1061 (317 rule-29-only positives removed).
     That filter is now code (`case_exclusions.py`, applied inside both generators), so
     regenerating no longer needs a hand edit. It reproduces 314 of the 317 removals on the
     pre-filter data and also drops about 50 rule-29-only pairs the hand filter left in, so the
     regenerated positive count is not 11,222. See the changelog entry below.
  2. BAI-1067 refreshed only the negatives (a negatives-only migration), so regenerating
     `sample_labeled_pairs.jsonl` reproduces the committed negatives but not the positives.
  3. The committed population tier was not refreshed for constructed households: regenerating
     `population_*.jsonl` adds `::household::constructed` decoys and yields different pools than
     the committed files.

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
(`::household::constructed`, a same-surname record given its elder's real address, or
`::institutional::<type>`, whose `address` is a fabricated, unambiguously-synthetic institutional
address per `special_populations.py` — the underlying identity is still a real, distinct ONC
record). **Known simplification, read before treating this tier as equivalent to
`labeled_pairs.py`'s institutional pairs:** `special_populations.construct_institutional_negatives()`
fabricates the same address on *both* sides of a pair; this tier only injects the fabricated side
into the decoy pool, so the query here keeps its real address. See `population_cases.py`'s module
docstring for why.

## Frequency and real-world representativeness

**The number of cases in each `rationale` category is an artifact of how this file was
generated, not a signal about how often that scenario occurs in the real world.** For example,
`normalization_edge_case` cases are ~33% of this file because the generator emits exactly one
diacritic and one punctuation variant per source patient — not because accented or hyphenated
names are that common. Conversely, `hard_negative` has only 4 cases because that's how many
coincidental ZIP+DOB collisions happened to occur in a 2,000-patient sample — not because that
scenario is rare in reality. Likewise, `marriage_variant`/`ssn_dropped`/`phone_variant` (session
14) track how often `MOTHERS_MAIDEN_NAME`/SSN/`PHONE2` happen to be populated in the vendored ONC
sample (~5.3%/~75%/~15.1% respectively — see those mutators' own docstrings), not real-world
prevalence of a missing-SSN or two-phone-number record. **Do not compute an aggregate "expected
real-world accuracy" number by weighting categories according to their raw counts in this file.**

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

## Option A: score the per-provision pairs (`sample_labeled_pairs.jsonl`)

Your algorithm just needs to satisfy one contract: given two FHIR `Patient` documents, decide
match or no-match. Any language, any org — no need to adopt Python or this repo's tooling.

1. Stream the file line by line (it's ~6,300 lines / ~6MB as committed; don't assume that stays small).
2. Parse each line's JSON and hand `source`/`target` to your algorithm.
3. Compare its answer to `expected_match` and tally into `tp`/`fp`/`fn`/`tn`.
4. Compute metrics from the tallies — never per-case, never by averaging per-case percentages.

```python
import json

tp = fp = tn = fn = 0
with open("evaluation/cases/sample_labeled_pairs.jsonl") as f:
    for line in f:
        case = json.loads(line)
        predicted_match = my_algorithm(
            case["source"], case["target"]
        )  # <- your code here
        actual_match = case["expected_match"]
        if predicted_match and actual_match:
            tp += 1
        elif predicted_match and not actual_match:
            fp += 1
        elif not predicted_match and actual_match:
            fn += 1
        else:
            tn += 1

recall = tp / (tp + fn) if (tp + fn) else float("nan")
fpr = fp / (fp + tn) if (fp + tn) else float("nan")
print(f"recall={recall:.4f} fpr={fpr:.4f}  (n={tp + fp + tn + fn})")
```

Three rules for reporting results from this tier:

- **Only trust `recall`/`fpr` here.** `precision`/`fdr`/`accuracy` have no real-world
  interpretation on this curated, rare-case-oversampled file — compute those over the population
  tier instead (Option B). See "Frequency and real-world representativeness" above for why.
- **Break results out by `rationale`**, not one blended number — group by the prefix before the
  `/` (`case["rationale"].split("/")[0]`), e.g. `fuzzy_variant`, `hard_negative`. A single number
  hides categories your algorithm handles well vs. poorly.
- **Report skipped cases separately** — if your algorithm can't evaluate a case (e.g. a required
  field is empty), count that, don't silently exclude it from the tallies. An algorithm that skips
  its hardest cases shouldn't look stronger than one that attempted everything.

## Option B: score the population tier (`population_queries.jsonl` + `population_candidates.jsonl`)

This tier is where valid precision/FDR/F1/accuracy numbers come from. Load the candidate registry
once, then score every query against its own candidate pool:

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
            predicted_match = my_algorithm(
                query_case["query"], candidates[candidate_id]
            )
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
print(
    f"precision={precision:.4f} recall={recall:.4f} fpr={fpr:.4f} fdr={fdr:.4f} accuracy={accuracy:.4f}"
)
```

Every (query, candidate) pair in every pool flattens into the same four buckets as Option A — the
realism here comes from *how the pools were built* (mostly random distractors, not curated rare
cases), not a different scoring shape. Report skipped evaluations the same way as Option A.

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
PYTHONPATH=. uv run python evaluation/export_test_dataset.py
PYTHONPATH=. uv run python evaluation/export_population_dataset.py
```

Both scripts share the same `SAMPLE_SIZE` override as `evaluation/labeled_pairs.py`. Beyond that,
`export_test_dataset.py` also takes `OUTPUT_PATH` (default `evaluation/cases/sample_labeled_pairs.jsonl`),
while `export_population_dataset.py` takes its own `POOL_SIZE` (default 40), `CANDIDATES_PATH`
(default `evaluation/cases/population_candidates.jsonl`), and `QUERIES_PATH` (default
`evaluation/cases/population_queries.jsonl`) — it does not read `OUTPUT_PATH`. Read
`SYNTHETIC_DATA_SETUP.md`'s "Memory & scale" section before raising `SAMPLE_SIZE`/`POOL_SIZE` or
passing more than one ONC shard's worth of patients.

To generate from the full 9-shard ONC dataset (~1,000,000 records) instead of one sampled shard,
use `make generate-full-dataset` (`evaluation/export_full_onc_dataset.py`) rather than raising
`SAMPLE_SIZE`/passing all shards to the scripts above yourself — it processes one shard at a time
(never materializing the full dataset in memory at once, per `SYNTHETIC_DATA_SETUP.md`'s "Memory &
scale" section) and writes to `full_labeled_pairs.jsonl`/`full_population_candidates.jsonl`/
`full_population_queries.jsonl`, not the `sample_`/`population_` files documented above, so it
never overwrites the committed sample this README describes. One difference from the sample tier:
the full-dataset run skips the `name_collision_negative` category
(`hard_negatives.mine_name_collision_negatives()`) because that generator is O(n^2), not O(n) like
every other generator here — full-shard scale would take on the order of two hours per shard. Every
other true-match/hard-negative/special-population category is present at full scale.

## Dataset changelog

- **BAI-1061 (case exclusions)** - `case_exclusions.py` drops true-match pairs the CMS spec cannot
  link, at generation time in `labeled_pairs.generate_raw_pairs` and
  `population_cases.build_population_dataset`; negatives are never dropped. The first rule,
  `rule_29_removed`, drops a pair when a DOB outside +/-1 day leaves removed rule 29 (First Name* +
  Last Name* + Phone + ZIP) as the only link: names fuzzy (Damerau-Levenshtein <= 1, nickname-,
  diacritic- and punctuation-insensitive), phone and ZIP equal, and none of the 12 DOB-free rules
  (13-22, 25, 26) matching. Measured against the pre-filter data (`cf5aaa1^`): 314 of the 317 hand
  removals reproduced, plus 50 pairs the hand filter kept (48 of them unmatched by the current engine).
  At the default seed the export reports 378 pairs and 413 population candidates excluded. To add an
  exclusion, register an `ExclusionRule` in `DEFAULT_RULES` (steps in the module docstring).

- **BAI-1067** — `sample_labeled_pairs.jsonl` negatives reduced from 446 to 282 rows: 164 non-match
  pairs that could be the same person (shared real SSN, or identical first name + family + DOB) were
  removed. `::sibling` case ids changed, and a new `::household_constructed` id class was added
  (a real younger record given a real elder's address; the pair-tier target keeps the younger
  record's id). Positives are unchanged. `population_*.jsonl` no longer contains such pairs but does
  not yet contain constructed households (a follow-up regenerates the population tier). Consumers
  that pin row counts or case ids should re-pin.

## Release gate

`make audit` evaluates `evaluation/release_thresholds.json` against `evaluation/audit.py`'s report
(label validity, tier parity, positive phone drift, naive-baseline F1). A metric marked
`"tracked"` is reported but does not fail; `"enforced"` fails CI. Enforced: `same_person_negatives`
(max 0); `tier_parity_gap` (max 0; `placeholder_collision_negative` is exempt because it is
pairwise-only by design); and `positive_phone_drift_rate` (min 0.05). The 0.05 floor is
**provisional**: it is to be re-set when the workgroup supplies measured rates, and a measured
profile with phone churn below roughly that level will fail CI until the floor is changed. Run `PYTHONPATH=. uv run python evaluation/audit.py` for the full
JSON report (per-field positive drift rates, people per address, shared-phone rate, age bands).
The naive baselines (phone-only, SSN-only, ...) are deliberately weak matchers: a test set where
one of them scores near the multi-field baseline is not discriminating between algorithms.

## Drift scenarios (session 15)

True-match pairs where the same person differs between two systems. Every scenario is in **both**
tiers. Registry scenarios (`surname_change`, `address_move`, `phone_churn`, `email_churn`,
`placeholder`, `gender_drift`) use the same variant body in both tiers, including on regeneration.
Compound variants are generated per tier (a shared generator stream in the per-provision tier, a
per-patient RNG in the population tier), so their bodies match between tiers only in the committed
files, where the migration copied them from the sample rows; `placeholder_collision_negative` is pairwise-only (both sides must carry the shared dummy).

| Scenario | What differs | Subtypes (`rationale` = `scenario/subtype`) |
|---|---|---|
| `surname_change` | surname not present anywhere on the other record | `no_history`, `prior_name_on_target` (old surname kept as `use: maiden`), `hyphenated` |
| `address_move` | a different real address | `current_vs_prior`, `history_on_one_side` (new `use: home`, old `use: old`; no dates invented) |
| `phone_churn`, `email_churn` | contact value replaced, dropped or added | `replaced`, `dropped`, `added` |
| `placeholder` | one field holds a well-known dummy (SSN `999-99-9999`, phone `000-000-0000`, given name `UNKNOWN`, address `HOMELESS`) | the field name; DOB is never used (a placeholder DOB leaves only rules CMS removed) |
| `gender_drift` | administrative sex differs, composed with one fuzzy edit | `<from>_to_<to>`; **off by default** until the workgroup confirms the label |
| `placeholder_collision_negative` | two distinct people share a placeholder SSN, phone or DOB | the field name |

New phones, emails, addresses and surnames come from a held-out donor pool (the ONC rows right
after the sample), so donors are distinct records, but a donated value can coincidentally equal a value held by an in-set patient (counts below). Emission rates come from
`drift_profile.py` and are **placeholders, not measured real-world rates**; supply measured ones
with `DRIFT_PROFILE_PATH=profile.json` (`{"source": "...", "rates": {"phone_churn": 0.4}}`).
`marriage_variant` and `phone_variant` (session 14) are kept unchanged for `case_id` stability;
`surname_change` + `address_move` and `phone_churn` are the replacements, and removing the old ids
awaits the workgroup's versioning decision.

The committed files were extended **append-only** by a one-off migration: every row that was
committed before is unchanged in content (`population_candidates.jsonl` is
re-sorted by id), and population pools grew by the new candidates (39-48 candidates
per query). Regenerating the files will not reproduce them exactly (see "Assembly, export, and
reproducibility"). 
**Donor coincidences** (computed over the 2,715 appended pairwise rows; a "new" value is on the target
but not on the source; "in-set" means held by a different patient in the committed sample or queries):
`email_churn/replaced` 2 of 78 rows carry a new email equal to an in-set email, and `email_churn/added`
5 of 363; `phone_churn/replaced` and `phone_churn/added` 0 of 462 and 0 of 25; `surname_change` 0 of
303; `address_move` 19 of 366 target addresses (street + city + ZIP) equal an in-set patient's address.
7 of the 366 `address_move` targets are placeholder-like addresses (line containing UNDOMICILED,
HOMELESS or UNKNOWN, or ZIP 99999/00000), so `address_move` can move a record to a placeholder-like
address in those rows.

**Donor skew (committed files).** Donors are the rows immediately after the sample in one alphabetically sorted shard, so
donated surnames start almost entirely with "A" (303 of 303 `surname_change` rows have a new surname
starting with "A") and donated addresses are almost all NY (364 of 366 `address_move` targets, 99.5%).
This limits what the `surname_change` and `address_move` categories stress in the committed files. The
realistic set draws its donors with the age-stratified sampler across all shards, so its 297
`surname_change` targets are spread over many initials (initials are counted on the DONATED surname; for hyphenated prior-name targets, the part after the hyphen; largest: S 33, H 26, B 25, M 23, R 22; 24 distinct initials); its
`address_move` targets are still almost all NY (396 of 397), because ONC itself is New York data.

**Phone churn can leave a shared phone.** ONC patients can hold two phones and the scenarios drop or
replace only the first, so some `phone_churn` rows still share a phone with the source: 63 of 474
`phone_churn/dropped`, 82 of 462 `phone_churn/replaced`, and 12 of 74 `placeholder/phone` rows have a
shared normalized phone between source and target. `audit.positive_phone_drift_rate` counts set
inequality of normalized phones: it is 0.0801 (1,093 of 13,637 positives) as reported, and 0.0728
(982 of 13,480) when those 157 rows are excluded.

**Not yet verified against the CMS reference algorithm.** This repo has no matching engine. BAI-1061
removed positives that only a removed rule could match; a new positive that no Table 2 rule can
match is a label defect. Run the new categories through the reference algorithm and report any
such rows.

Highest label-defect risk: subtypes whose only differing identifying field is a name field. Appended
row counts, and how many of them have no shared real SSN between source and target (placeholder SSNs
do not count), so no SSN-based rule can match them:

| Subtype | Rows | No shared real SSN |
|---|---|---|
| `placeholder/given` | 82 | 18 |
| `surname_change/no_history` | 96 | 20 |
| `surname_change/hyphenated` | 109 | 21 |
| `surname_change/prior_name_on_target` | 98 | 27 |

Run these rows FIRST through the reference algorithm. A conformant algorithm failing them may
indicate a label defect, not an algorithm defect.

## Age- and household-realistic dataset (session 15)

The committed samples take the first 2,000 rows of one alphabetically sorted ONC shard. Measured as of
ONC's own vintage (2017-01-01) they are already 21.5% under 18, so the earlier "8% under 18" finding was
an artifact of measuring ages as of 2026 (ONC's latest birth year is 2016, so nobody is under 10 that
year); the skew that persists is the elderly (12.8% aged 85+ against about 2%). The committed samples also
have almost no shared addresses (1.03 patients per address) or shared phones (6%). `make
generate-realistic-dataset` builds a **parallel release candidate** (`realistic_labeled_pairs.jsonl`,
`realistic_population_candidates.jsonl`, `realistic_population_queries.jsonl`, `realistic_manifest.json`;
git-ignored, commit deliberately with `git add -f`) from all nine ONC shards, one at a time:

| Stage | What it does | Source of the target |
|---|---|---|
| Age-stratified sample | 2,000 patients with exact band counts: 21.5% under 18 (430, including infants and toddlers), 61.2% 18-64, 15.35% 65-84, 1.95% 85+ (39) | Census Vintage 2024 (under 18); ACL 2023 Profile of Older Americans citing Census 2022 (65+ 17.3%, 85+ 6.5 million) |
| Households | sizes with 29% one-person and target mean 2.5 (realized 2.60 patients per household and 2.48 patients per address at seed 0); members share the anchor adult's real address; a share of members share the anchor's phone and email; children under 13 always take the anchor's phone and email (or have none when the anchor has none) and usually have no SSN | Census 2024 (one-person households); reviewer's "roughly 2.5 nationally" (mean; not independently verified against a Census table) |
| Household non-matches | every pair of co-residents is a non-match in the pairwise file, and each co-resident is a decoy in the other's population pool (`household_member_negative/shared_contact` or `/same_address`) | n/a |

Measured on the generated set (seed 0): exact age bands; 2.48 patients per address (committed: 1.03);
60% of patients share a phone and 58% an email (committed: 6% and 32%); 769 households, 49 of the 430
children placed with a same-surname adult. Against the committed set the phone-only baseline's F1 on
the population tier drops from 0.953 to 0.882 and the address-only baseline's from 0.862 to 0.749; the
multi-field margin over the best single field rises from 0.032 to 0.054 (only just above the provisional
0.05). Date-of-birth-only is now the strongest single field in the realistic set (F1 0.919; phone-only was
strongest in the committed set at 0.953), so `best_single_field_f1` stays `tracked`.

The committed audit (`make audit`) now reports age shares as of 2017-01-01, so its JSON age bands read
21.5% under 18 and 12.8% aged 85+ for the committed files; the earlier 8.0% / 21.1% figures are the same
data measured as of 2026.

A custom `DRIFT_PROFILE_PATH` JSON REPLACES the whole rates dict. A profile that omits
`household_shared_phone`, `household_shared_email` or `minor_ssn_absent` silently gets 0.0 for them (no
sharing, no SSN drops), so list those keys when supplying a profile.

What this is not:

- **Not the committed set.** The rule-29 exclusion now applies here too (`case_exclusions.py`), but the
  new drift positives are not yet verified against the CMS reference algorithm. Treat them as a release
  candidate.
- **Most households are unrelated real records at one address** (roommates, blended families whose
  surnames differ). The sample is too small to mine family structure; the report counts how many children
  were placed with a same-surname adult.
- **The shape of the multi-person household size distribution is an assumption** (sizes 2-6, geometric
  weights solved to hit the mean); the cited sources fix only the one-person share and the mean. The
  sharing and no-SSN rates are PLACEHOLDERS in `drift_profile.py`. The realistic gate floors
  (`shared_phone_rate` >= 0.30, `people_per_address` >= 2.0) are provisional and tied to the placeholder
  0.5 sharing rate: children under 13 always take their anchor's phone, so the realistic `shared_phone_rate`
  stays around 0.29 even when `household_shared_phone` is 0.0 (measured: 0.29, 0.35, 0.41, 0.60 at 0.0, 0.1, 0.2,
  0.5 respectively). A profile fails the 0.30 floor only when `household_shared_phone` approaches 0. The
  `people_per_address >= 2.0` floor depends on household size distribution, not sharing rates.
- **The mined negative categories collapse.** A random 2,000-of-1M draw across all shards removes the
  alphabetical clustering that the sibling, name-collision and shared-ZIP+DOB miners relied on. Pairwise
  rows per category, committed -> realistic: `sibling_negative` 36 -> 3, `name_collision_negative` 75 -> 1,
  `hard_negative` 4 -> 1. The realistic set therefore does NOT meaningfully exercise those provisions, and
  the pairwise tier's purpose of deliberately over-sampling rare categories is not met for them. Mining
  them per shard, or constructing them, is a follow-up.
- Age uses `AS_OF = 2017-01-01` (ONC's vintage) against Census targets from 2022 and 2024 (Open Question 5).

`make audit-realistic` evaluates `release_thresholds_realistic.json` against the generated files;
`test_realistic_dataset.py` does the same on a 300-patient version in CI.
