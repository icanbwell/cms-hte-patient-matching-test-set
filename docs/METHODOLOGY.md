# Methodology: how this test dataset is built, and what's left

This is the current-state summary of how this repo generates its CMS HTE patient-matching test
data, and what's still missing. For the full design history (why each decision was made, in
chronological order) see `docs/sessions/completed/` — this doc only states what's true *now*, as
of session 13.

## Source population

Everything starts from the public **ONC 2017 Patient Matching Algorithm Challenge** dataset —
~1,000,000 records, already synthetic and non-PHI, vendored at `evaluation/fixtures/onc/*.csv`.
`onc_loader.py` maps its flat CSV columns onto FHIR `Patient` dicts (see its module docstring and
`evaluation/cases/README.md`'s column-mapping table for the exact field-by-field translation).

**Verified fact this pipeline depends on:** every `EnterpriseID` in this vendored copy is unique —
there are no native duplicate-person clusters to mine. Every true-match cluster used below is
*built* by this repo's own generators, never looked up from ONC.

## The generation pipeline

Four generator modules, each answering a different part of the CMS spec, assembled by
`labeled_pairs.py`:

| Module | Produces | Method |
|---|---|---|
| `mutations.py` | True-match pairs: fuzzy-tolerance variants | Exactly one single-character edit (insert/delete/substitute/transpose) or nickname/abbreviation swap per generated case — 10 registered mutation types across DOB and name fields. |
| `normalization_edge_cases.py` | True-match pairs: normalization edge cases | Diacritic-folding and punctuation variants that CMS spec §V.A requires normalization to fold into an exact match — a different requirement than fuzzy tolerance. |
| `hard_negatives.py` | True-non-match pairs: coincidental collisions | *Mines*, never mutates, genuinely distinct real ONC records that share a high-signal field combination (ZIP + DOB) but a different name. |
| `special_populations.py` | True-non-match pairs: high-risk categories | Multi-generational households (mined, real ONC pairs). 8 institutional categories — shelter, nursing facility, correctional institution, hotel/short-term housing, halfway house, dormitory, group home, migrant camp — *constructed* by overwriting only the address on already-distinct real identities with a fabricated, clearly-synthetic address (`"SYNTHETIC TEST ADDRESS"`, reserved `000xx` ZIP block). The underlying identities are never fabricated. |

**Why mining, not mutation, for non-matches:** mutating a record and calling the result "a
different person" would only test a matcher's own fuzzy tolerance, not reality. A genuine
non-match requires two records that were never derived from one another.

**Literal twins are deliberately never constructed** — CMS spec §IV.G itself acknowledges this
case can't be resolved through field matching alone, so it isn't a valid test case, not a gap.

### Frequency weighting

`prevalence_estimates.py` optionally stamps each generated case with a real-world prevalence
weight, sourced only from cited public data (Census, CDC/NCHS, Pew, peer-reviewed record-linkage
literature) — never a guessed number. Categories with no public estimate get an explicit
`has_public_estimate=False` placeholder pinned to a neutral value instead of a fabricated one. See
`evaluation/cases/README.md`'s "Frequency and real-world representativeness" for which metrics
this is (and isn't) valid for.

### Assembly and export

- `labeled_pairs.py`'s `generate_raw_pairs()` combines all of the above into `(source, target,
  is_true_match)` triples on one seeded RNG, so a given seed reproduces the same output
  byte-for-byte.
- `population_cases.py` regroups the same generation logic into the second test shape: one query
  patient against a candidate pool (default 40), using an independent RNG so topping up a pool
  with random distractors never perturbs the variant-generation stream.
- `export_test_dataset.py` / `export_population_dataset.py` materialize both shapes as the JSON
  Lines files under `evaluation/cases/`.
- Every export defaults to **one ONC shard, sampled down** (2,000 patients) — loading and
  transforming the full ~1,000,000-record dataset at once has crashed a cluster before. See
  `SYNTHETIC_DATA_SETUP.md`'s "Memory & scale" section before raising this.

### What changed at session 13

This repo used to depend on a private reference matching engine for a normalization step during
generation. That dependency was removed entirely (session 13) so this repo has zero runtime
dependency on any matching engine — it only produces algorithm-agnostic test data now. One
consequence worth knowing: generated field values carry whatever case/punctuation the raw ONC CSVs
used; this pipeline does not normalize them. Apply your own normalization convention before
comparing fields, same as you would for any other input.

## What this covers, against the cross-org workgroup's ground-truth categories

| Category | Status |
|---|---|
| Exact-match true positives | Covered (pre-existing, outside this pipeline's generators). |
| Fuzzy-eligible single-character edits | **Done** — `mutations.py`. |
| Normalization edge cases (diacritics, punctuation) | **Done** — `normalization_edge_cases.py`. |
| Coincidental-collision non-matches | **Done** — `hard_negatives.py`. |
| Named special/high-risk populations (except twins) | **Done** — `special_populations.py`. |
| Population-query tier (one query vs. a candidate pool) | **Done** — `population_cases.py`. |
| Literal twins | **Deliberately not attempted** — unresolvable by field matching per CMS spec §IV.G. |

## What's left to do

- **Administrative-restriction / insurance-identifier pairs** (e.g. family-shared Subscriber ID).
  ONC has no insurance/plan-ID column, so this needs a genuinely *fabricated* identifier module —
  scoped in `docs/sessions/pending/session_11.md`. Currently blocked: it depends on FHIR
  `identifier` extraction work ("session 6") that lived in the private reference matching engine
  this repo was split from and was never ported here. Needs re-scoping to be fully
  algorithm-agnostic before it can proceed.
- **≥1,000,000-record empirical collision-rate validation.** The population tier's pools (default
  40 candidates) tell you whether an algorithm picks the right candidate out of a realistic-sized
  pool — not the population-wide collision probability of a field combination at full ONC scale.
  Not attempted; would need a distributed job (Spark), not this pipeline's single-process
  in-memory approach. No session scoped yet.
- **Client-type field-availability modeling** (e.g. modeling that payer clients have phone numbers
  populated at a different rate than provider clients). An organizational-policy decision, not an
  engineering blocker — the current cross-org methodology Doc already sanctions "aggregate
  statistics" as a contribution path. Not started.
- **Finalizing prevalence estimates.** `prevalence_estimates.py`'s researched estimates are
  real and cited but pending maintainer review, not yet treated as final. Several categories
  (`fuzzy_variant/*`, `hard_negative`, four institutional subcategories) have no public per-category
  rate at all and are pinned at a neutral placeholder — that's a real, permanent data gap, not an
  oversight to fix.
- **A reference scoring harness / CLI** (the cross-org Doc's proposed `harness/` layout and
  `cms-match-harness score` command). Deliberately out of scope, not a gap — this repo's Design
  Principle 1 is to produce algorithm-agnostic data and leave scoring to the consumer. See
  `evaluation/cases/README.md`'s Option A/B for the scoring approach this repo recommends instead.
- **Cross-engine comparison work** (`docs/sessions/pending/session_8.md`) — its entire premise
  (compare two specific matching engines in-process, in this repo) is incompatible with this
  repo's post-session-13 scope. Needs a decision on whether that work belongs in a different repo
  or is no longer needed, not execution here.

## Where to go for more detail

- `evaluation/cases/README.md` — how to actually test an algorithm against the generated files,
  including runnable scoring code.
- `evaluation/SYNTHETIC_DATA_SETUP.md` — how to run the generation/export scripts, memory & scale
  guidance.
- `evaluation/SYNTHETIC_DATA_COMPARISON.md` — the original, session-9-era design rationale
  (historical record, not current state past session 13's changes — read the "Reading this
  document today" note at its top first).
- `docs/sessions/completed/` and `docs/sessions/pending/` — the full chronological design history.
