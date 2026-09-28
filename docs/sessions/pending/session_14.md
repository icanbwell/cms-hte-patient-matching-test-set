# Session 14 — Compound True-Match Variants, Harder Hard-Negatives, and Population-Scale Scoping

**Status:** implemented, pending workgroup review. Proposed 2026-09-28 in response to feedback
from the 2026-09-22 CMS Patient Matching - Test Dataset Workgroup meeting (Luke Breyer/Epic).
Repo maintainer (Imran Qureshi) authorized proceeding with implementation on 2026-09-28, in the
same session that authored this doc and its implementation plan. Implementation went through two
independent review passes (a full-branch review, and a follow-up adversarial/EA review) before
this status line was updated — see PR #10's description for both. Broader review/sign-off by the
CMS Patient Matching Workgroup itself (Luke Breyer/Epic) — as opposed to the repo maintainer's
authorization to implement — has not yet happened and is not claimed here.
**Thread:** Evaluation & Statistical Rigor Framework
**Estimated size:** M — two new generator functions in existing modules plus two new
hard-negative miners; no new modules, no schema changes.

## Outcome purpose

Luke Breyer (Epic) reviewed this repo's test dataset and raised three concrete gaps, per the
meeting notes (`CMS Patient Matching - Test Dataset Workgroup`, 2026-09-22):

1. **True-match cases lack demographic variation.** Every correct-match pair is "an exact copy
   with only one field changed" — no scenario where, e.g., one record has a Social Security
   Number and the other doesn't, or where a marriage changed both surname and address at once, or
   where phone type (home vs. cell) differs between records for the same person.
2. **Negative (non-match) cases don't have enough demographic overlap to trigger CMS rules** —
   they need to be hard enough to "outperform cheap heuristics": demographic drift, close
   relatives, twins/siblings sharing an address, not just coincidental ZIP+DOB collisions.
3. **Population size** — the workgroup aligned on a population "north of one million" for the
   eventual real release, versus this repo's current sampled-down, single-ONC-shard defaults.

This session addresses (1) and (2) directly in code. (3) is scoped as a decision to make, not
code to write yet, because it surfaces a mismatch between what the workgroup described (a
1M+-record population release, drawing on a since-shared Epic reference doc describing a fully
synthetic 500M-patient generator using SSA/Census source data) and this repo's two existing output
tiers, whose sizes are bounded by ONC's ~1M-row total and by each tier's own statistical-power
design (see `evaluation/cases/README.md`'s tier table).

**Explicitly deferred, not part of this session:** whether to adopt Epic's SSA-baby-names/Census-
surname-file/ACS-table synthetic-generation methodology (documented in the shared "Synthetic
Patient Matching Benchmarking Population — Data & Frequency Sources" reference) as an alternative
or supplement to this repo's ONC-mining-and-mutation approach. That's a bigger architectural
question (this repo's Design Principle against fabricating identities vs. Epic's fully-synthetic
model) that needs its own discussion with the workgroup before scoping. Left for a future session.

## Upstream sessions (must be completed first)

None. This session's changes are additive to `mutations.py`/`hard_negatives.py`/
`special_populations.py`, all already `completed/` (sessions 9, 10, 13) and stable.

## Downstream sessions (unblocked by this one)

None yet authored.

## Upstream data/system dependencies

None new — same static ONC fixture CSVs as every prior session. The new `marriage_variant()`
generator (Task 2 below) uses `MOTHERS_MAIDEN_NAME`, a field ONC already provides per patient
(loaded by `onc_loader.py`, per `evaluation/cases/README.md`) but currently unused downstream.

## Downstream data/system dependencies

None. Output stays in-memory `RawPair`/labeled-pair tuples, same as every prior session.

## Scope

### In scope

**1. Compound true-match variants (`evaluation/mutations.py`)**

Add `generate_compound_variant()` alongside the existing `generate_fuzzy_variant()`
(`mutations.py:321-334`). Where `generate_fuzzy_variant()` applies exactly one registered mutator
(per its docstring at `mutations.py:8-11` — kept as-is, since several provisions specifically test
one CMS rule in isolation and need a single-field diff to do that cleanly), the new function draws
2-3 independent mutators from `MUTATIONS` and applies them to different fields on the same
variant, still returning one `(original, variant, is_true_match=True)` triple. This is a new,
additional true-match category — it does not replace or change the behavior of
`generate_fuzzy_variant()` or any of its existing callers.

**2. New true-match generators for the two specific scenarios Luke named:**

- `ssn_dropped_variant(patient)` in `mutations.py` — returns a variant with SSN cleared on one
  side of the pair only. Matches Epic's cited "Missing/placeholder SSN" data-quality category.
- `marriage_variant(patient)` in `mutations.py` — swaps the variant's surname from
  `MOTHERS_MAIDEN_NAME` to the ONC record's own surname (modeling "before" and "after" a marriage
  name change) and additionally overwrites the address fields with another donor record's address
  (ONC has no move history, so a second real ONC address stands in for "moved after marriage").
  Needs a source of donor addresses — take the next patient in whatever iterable
  `generate_raw_pairs()` is already iterating, per the existing pattern other generators use for
  borrowing fields from unrelated real records (see `hard_negatives.py`'s mining functions for
  precedent).
- Phone-type variation (home vs. cell) is **not** included pending a data check: confirm ONC's CSV
  schema carries any phone-type-equivalent column before promising this mutator. If it doesn't
  exist in the source data, this scenario can't be built from ONC alone and needs its own decision
  (fabricate a type tag, or drop the idea) — flagged as an open question below, not blocking the
  rest of this session.

**3. Two new hard-negative miners (`evaluation/hard_negatives.py` or `special_populations.py`,
whichever the executing engineer judges is the better fit given each module's existing scope split
— `hard_negatives.py` is for coincidental mining, `special_populations.py` is for constructed
high-risk categories; both new miners here are coincidental mining, so `hard_negatives.py` is the
likely home):**

- `mine_sibling_negatives()` — same family surname + same ZIP + DOB gap under ~3 years, a proxy
  for siblings/twins where ONC carries no family-linkage field. Deliberately distinct from
  `special_populations.py`'s existing `mine_shared_surname_household_negatives()`
  (`special_populations.py:197-252`), which requires a ≥15-year DOB gap as a parent/child proxy —
  this session's new miner is the complementary near-DOB case that function explicitly excludes.
- `mine_name_collision_negatives()` — near-identical name (via the `nicknames` library already a
  direct dependency per session 13, or simple edit-distance/Soundex) with **no** ZIP or DOB
  overlap. Targets Luke's "outperform cheap heuristics" concern directly: an algorithm that
  over-weights name similarity alone should fail to reject this category.

### Out of scope

- **Phone-type (home/cell) true-match variant** — blocked on confirming ONC's schema has a usable
  field; see Task 2's note above. Add only if that check succeeds; otherwise flag as a new open
  question for the workgroup (fabricate vs. drop).
- **Population-scale changes of any kind.** No change to `SAMPLE_SIZE`, `POOL_SIZE`, or any new
  total-population-count parameter. That's explicitly a scoping decision, not code, per the
  Outcome purpose above — see Open questions.
- **Adopting Epic's SSA/Census-sourced synthetic generation methodology** — deferred per the
  Outcome purpose above.
- **Any change to `evaluation/prevalence_estimates.py`'s cited sources.** If the new sibling/twin
  hard-negative category needs its own cited prevalence rate (Epic's doc points to CDC NVSS
  73(2) for twin/triplet rates), that's a natural follow-up but not required for this session's
  definition of done — `prevalence_estimates.py` already supports an explicit
  `has_public_estimate=False` placeholder for categories not yet backed by a citation.

## Tasks

1. Write `generate_compound_variant()` in `mutations.py`; unit test that it always changes 2-3
   distinct fields and never fewer.
2. Write `ssn_dropped_variant()` and `marriage_variant()` in `mutations.py`; before writing
   `marriage_variant()`, confirm `MOTHERS_MAIDEN_NAME` is populated (non-empty) for a meaningful
   fraction of the ONC sample — if it's sparse, note the resulting true-match category's small
   yield in the module docstring rather than silently producing near-zero cases.
3. Before Task 2's phone-type idea, grep ONC's CSV header row for any phone-type-equivalent
   column; record the answer in this doc's Open questions (already anticipated as likely "no"
   below) and skip the mutator if absent.
4. Write `mine_sibling_negatives()` and `mine_name_collision_negatives()`, placed per the
   module-fit judgment call above; unit test each against small synthetic patient lists, following
   the existing test patterns in `test_hard_negatives.py`/`test_special_populations.py`.
5. Wire all four new generators into `labeled_pairs.py`'s `generate_raw_pairs()` (compound
   variants and the two scenario-specific mutators alongside the existing `MUTATIONS`-driven true
   matches; the two new hard-negative miners alongside the existing mining calls), each producing
   `RawPair`s with a distinguishing `strata` value (e.g. `{"pair_type": "compound_variant"}`,
   `{"pair_type": "ssn_dropped"}`, `{"pair_type": "marriage_variant"}`,
   `{"pair_type": "sibling_negative"}`, `{"pair_type": "name_collision_negative"}`) so downstream
   consumers can slice by category the same way every existing category already is.
6. Update `evaluation/cases/README.md` and `evaluation/DESIGN.md` (or `SYNTHETIC_DATA_SETUP.md`,
   whichever already documents the mutation/hard-negative category list) to list the five new
   categories.

## Unit tests required

New tests in `evaluation/test_mutations.py` (compound variant, SSN-dropped, marriage variant) and
`evaluation/test_hard_negatives.py` (sibling negatives, name-collision negatives), following each
file's existing per-function test-class pattern. Add coverage to `evaluation/test_labeled_pairs.py`
confirming the new `strata["pair_type"]` values appear when `generate_raw_pairs()` runs against a
small real-ONC-fixture sample.

## Validation (definition of "resolved")

- [ ] `generate_compound_variant()` exists, always touches ≥2 distinct fields, and has passing
      unit tests.
- [ ] `ssn_dropped_variant()` and `marriage_variant()` exist with passing unit tests; the
      phone-type question is answered (either a working mutator with tests, or a documented "ONC
      has no phone-type field" finding in Open questions).
- [ ] `mine_sibling_negatives()` and `mine_name_collision_negatives()` exist, are distinguishable
      from the existing multi-generational-household miner by DOB-gap threshold, and have passing
      unit tests.
- [ ] `PYTHONPATH=. uv run python evaluation/labeled_pairs.py` runs against real ONC fixture data
      and prints nonzero counts for all five new `pair_type` categories.
- [ ] `make tests`, `make lint`, `make typecheck`, `make run-pre-commit` all clean.
- [ ] `evaluation/cases/README.md`/`DESIGN.md` updated with the five new categories.
- [ ] Population-scale question (Outcome purpose item 3) has an explicit answer from the workgroup
      or the repo maintainer before any code changes it — not resolved by this session.

## Open questions

- **NEEDS HUMAN DECISION — population scale.** The workgroup's "1M+ / up to 500M patient" numbers
  describe a different deliverable shape than either of this repo's current output tiers. Options,
  none chosen yet: (a) scope a genuinely separate large-scale release as a distributed (Spark) job
  per `SYNTHETIC_DATA_SETUP.md`'s existing "Memory & scale" guidance, using ONC's full ~1M-row
  ceiling as the base population; (b) confirm the per-provision tier stays intentionally small
  (its whole design point) and only grow the population-candidates pool size, accepting ONC's ~1M
  total as the ceiling on realism; (c) something else the workgroup decides after seeing this repo's
  tier design explained. This session takes no position and makes no code change either way.
- **Phone-type field availability — resolved.** ONC has no phone `use` (home/mobile) semantic, but
  it does carry a second raw phone-number column, `PHONE2`, that `onc_loader.py` read from the CSV
  header but never mapped into the output FHIR `Patient` dict. Session 14 loads it as a second
  `telecom` phone entry (`onc_loader.py`), and `phone_variant()` (`mutations.py`) swaps to it to
  model two distinct on-file phone numbers per person — without fabricating a `use` code, per this
  repo's "field values copied through from ONC as-is" convention.
- **Epic sourcing-methodology adoption** — deferred per Outcome purpose; not an open question for
  this session, just explicitly out of scope. Revisit as its own session if the workgroup wants it
  discussed.

## Execution notes

_(empty at authoring time; filled in by whoever executes the session)_
