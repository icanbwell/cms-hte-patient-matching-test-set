# Session 16 — v1 Release Blockers: Realistic-Set Hard Negatives, Negative Balance, FHIR Conformance

**Status:** Implemented on branch IQ-BAI-1156; realistic set is a v1 release candidate with open caveats 2, 3, 4. Written 2026-10-14 in response to written feedback from a
workgroup reviewer on the v1 release candidate.
**Author:** Imran Qureshi
**Ticket:** BAI-1156
**Thread:** Evaluation & Statistical Rigor Framework
**Estimated size:** L. Recommend shipping as five PRs (see Rollout). Blockers are PRs 1-4;
enhancements are PR 5 and can slip past v1 without reopening the blockers.

## Summary

The reviewer lists four v1 blockers and four enhancements. Blockers: (1) the `realistic_*` files,
which pass the realism floors, are git-ignored, so a clone only gets the committed set, which fails
them; (2) the realistic set has almost no hard negatives; (3) the pairwise tier is so
positive-heavy that always answering "match" scores about 98% F1; (4) the ONC-to-FHIR loader emits
non-conformant `Patient` resources. We fix (2) and (3) with one mechanism, a streaming
**reverse-blocking near-miss finder** that finds real ONC decoys for the sampled queries across all
shards, and reuse it for the "harder decoys" enhancement. We fix (4) in `onc_loader.py` plus a
conformance test. We resolve (1) by committing the realistic set as the v1 release, gated in CI.

## Findings, verified

Reproduced against the committed files and against a fresh run of
`export_realistic_dataset.py` (seed 0, defaults, written to a scratch dir).

| # | Reviewer's claim | Reproduced | Root cause in code |
|---|---|---|---|
| R1 | Realistic set is git-ignored; a clone fails the realism floors | **Yes.** `.gitignore` excludes `evaluation/cases/realistic_*.jsonl`. The committed set's gate is the one that fails `release_thresholds_realistic.json` | Release-candidate files were deliberately kept out of the tree (`export_realistic_dataset.py` docstring) until the open caveats were closed |
| R2 | Realistic set loses sibling, name-collision and hard-negative cases | **Yes.** Realistic pairs: 1 `hard_negative`, 1 `name_collision_negative`, 2 `sibling_negative` (committed: 75 name-collision, ~36 sibling, 20+ hard-negative) | `generate_realistic` runs every miner on `housed.patients`, a 2,000-record random draw from ~1M. The miners need two records that collide (ZIP+DOB, surname+ZIP, name distance 1). In the committed sample those collisions exist only because the first N rows of one alphabetical shard are adjacent. A random 0.2% draw almost never contains both members of a pair |
| R3 | Always-"match" on the pairwise tier scores ~98% F1 | **Yes.** Committed: 13,619 positive / 582 negative (95.9% positive), so all-yes F1 = 0.979. Realistic: 13,458 / 2,893 (82.3% positive), all-yes F1 = 0.903. Of the realistic negatives, 2,389 are `household_member_negative` | Positives are generated per patient per scenario (about 7 per patient); negatives come only from miners and constructors with fixed small caps |
| R4 | Loader emits non-conformant Patients | **Yes, each item.** Shard A-C alone: 6,733 of 196,495 rows have an empty `FIRST` (emitted as `given: [""]`), 1,263 `PHONE2` values contain `^`, 10,527 carry `ALIAS`, 10,487 carry `MOTHERS_MAIDEN_NAME` | `_row_to_patient` (`onc_loader.py:59-114`) copies columns straight into elements: `given.append(ALIAS)`, a second `name` built from `MOTHERS_MAIDEN_NAME` with the patient's own given names and no `use`, `SSN` identifier with no `type`, telecom with no `use`/`rank`, nothing with `period` |
| E1 | 52 of 430 minors live with a same-surname adult | Not re-measured; same mechanism as R2 (see E1 below) | Households are assigned over a random draw, so same-surname adults are rare in the sample |
| E2 | Birth years stop at 2016; 8.8% under 18, 8.8% 85+ | **Explained, not a defect.** `AS_OF = 2017-01-01` (`population_targets.py`) makes bands match Census targets; measured as of the reviewer's date the same data is under-18-light and 85+-heavy | ONC's latest birth year is 2016 (documented in `population_targets.py`). A genuine fix needs post-2016 births, which ONC cannot supply |
| E3 | Every query has 2-11 expected matches | **Yes.** Committed and realistic: exactly one query with 2 matches, none with 0 or 1 | Every patient gets one fuzzy variant, two normalization variants, a compound, and several scenario variants; there is no query-level dropout |
| E4 | 97% of decoys share nothing with the query | Consistent with the code: after mined negatives, `build_population_dataset` fills each pool from `all_ids` shuffled | The top-up at `population_cases.py:313-323` is uniform random |

**R2, R3 and E4 are one problem.** Each needs *real records that resemble a given query*, found
across the whole ONC population rather than inside a 2,000-record sample.

## Constraints

- **No fabricated identities** (CLAUDE.md, Design Principle): decoys are real ONC records; any
  constructed field is tagged and sliceable (carried over from session 15).
- **Memory & scale:** no 1M-record in-memory list; one shard at a time. The existing
  `mine_name_collision_negatives` is effectively O(n²) per bucket (measured ~142s at n=16,000 in its
  docstring), so running it on a whole shard is not an option.
- **Two tiers stay separate:** precision/F1 only on the population tier. The reviewer scores F1 on
  the pairwise tier anyway, so we make that score meaningful rather than argue.
- **Additive schema:** existing JSONL keys unchanged. Patient resource *content* changes (R4), so
  `dataset_version` bumps and `cases/README.md` gets a changelog.
- **Same-person guard:** every decoy passes `identity_guard.is_possible_same_person` (ONC has the
  same person under several EnterpriseIDs).
- **Tier parity:** any new category exists in both tiers (`audit.tier_parity_gap` stays 0).
- **Repo conventions:** `from __future__ import annotations`, `typing.Dict/List`, ruff + mypy clean,
  one same-named `test_*.py` per module. No new runtime dependency (`policies/approved-tech.yaml`
  has not been consulted for any; none is proposed).

## Alternatives considered

### R2/R3/E4: how to get hard negatives into a random sample

**A. Mine per shard before stratifying (the reviewer's suggestion).** Run the existing miners on each
full shard, then draw the stratified sample from the mined pairs plus random fill.
- ✅ Matches the reviewer's mental model; reuses the miners.
- ❌ The name-collision miner is O(n²) per bucket at shard size (~110k): hours, not minutes.
- ❌ Sampling pairs first distorts age-band quotas; members of mined pairs skew toward whatever ages
  collide most, so the sampler has to be reworked around pairs.
- ❌ Mined pairs are whatever collides, not decoys for *our* queries; pool decoys (E4) would still need
  a second mechanism.
- Verdict: ⚠️ Right goal, wrong direction of the join.

**B. Reverse blocking: sample first, then stream every shard for look-alikes of the sampled queries.**
Build a small key index over the 2,000 sampled queries (DOB; normalized first+last; surname+ZIP; DOB+ZIP;
phone; street address; deletion-neighborhood of name for edit distance 1). Stream each shard once and, for
each ONC record, look its keys up in that index (O(1) per record). Matches become near-miss decoys
for those queries. Age-band quotas are untouched because the sample is drawn first. Decoys live in
the candidate registry, not the sample. ✅ Proposed. Cost: one extra pass over ~1M rows (the realistic
export already takes about a minute for the stratified pass).

**C. Construct negatives by editing real records** (give a random patient the query's DOB, etc.).
❌ Rejected: fabricates identity attributes, and tests a matcher's tolerance rather than reality
(the reason `hard_negatives.py` exists; see its module docstring).

**D. Do nothing.** Not viable: all three items are reviewer-labelled blockers or enhancements and the
realistic set would ship with no hard negatives.

### R1: release route for the realistic set

**A. Keep ignoring; consumers run `make generate-realistic-dataset`.** ❌ Requires the ~1M-row ONC
fixtures (already vendored, but a ~1 minute, memory-sensitive run) and risks seed/version drift
between consumers.
**B. Commit the realistic files** (remove the ignore rule, or `git add -f`). Files are ~51 MB
total as built (34 MB pairs, 14 MB candidates, 3 MB queries; each under 50 MB), about twice the current committed set
(~25 MB). ✅ Proposed.
**C. GitHub Release artifact built in CI.** ⚠️ Cleaner repo, but a clone no longer holds the data and
the reviewer's complaint is specifically about what a clone gets. Reconsider if file size grows
(for example with the full-dataset export).

## Proposed solution

### Overview

Five PRs. Workstream order is by dependency: conformance first (it changes every record the later
workstreams read), then the near-miss finder, then the negative-balance and release changes that
consume it.

### Workstream 1 — FHIR conformance of the loader (R4, PR 1)

Fix `_row_to_patient`; no category or sampling changes.

| ONC field | Today | New |
|---|---|---|
| `FIRST` empty | `given: [""]` | Omit `given`. If no name part survives, omit the `name` entry rather than emit an empty one. Never emit an empty string anywhere (FHIR forbids it) |
| `MIDDLE` | appended to `given` | Unchanged, but only when non-empty |
| `PHONE` / `PHONE2` containing `^` | one `telecom.value` holding both numbers | Split on `^`, trim, drop empties, one `telecom` entry per number. `rank` follows source order (PHONE first) |
| `ALIAS` | appended to `name[0].given` | Separate `HumanName` with `use: "nickname"` and `text: ALIAS`. `text`-only avoids guessing whether an alias is a given or family name (the data has both shapes) |
| `MOTHERS_MAIDEN_NAME` | second `name` with the patient's own given names, no `use` | **Decided:** map to the standard `patient-mothersMaidenName` extension (`http://hl7.org/fhir/StructureDefinition/patient-mothersMaidenName`). It is the *mother's* maiden name, not the patient's own prior surname, so `use: "maiden"` would assert something false. Scenario-generated prior names (`surname_change`) carry `use: "maiden"` / `"old"` on the target only (decided; see Risks) |
| `SSN` identifier | `system` + `value` | Add `type.coding` (`http://terminology.hl7.org/CodeSystem/v2-0203`, `SS`) |
| `PHONE`/`EMAIL` `use` | absent | Keep absent: ONC has no source for "home" vs "mobile", and inventing one is a fabricated attribute. Emit `rank` (derivable). Decided: `use`/`period` only where a scenario models history |
| `period` | absent | ONC carries no dates, so base records get none. Scenarios that model history (`address_move`) already emit `period`; extend `phone_churn`/`email_churn` history targets to emit `use: old` + `period.end` for the same reason |

**Blast radius.** Code that reads `name[1]`, `given[...]`, or assumes the maiden name is a second
`name`: `mutations.py` (the `marriage_variant` comment at line ~345), `scenarios.py`,
`drift_mutations.py`, `placeholders.py` (`names[0]["given"][0] = value` fails on a missing
`given`), `identity_guard.py`, `special_populations.py`, `audit.py`. Step 1 is a repo-wide grep and
making every reader tolerate a missing `given`.

**Guard.** New `evaluation/fhir_conformance.py` (pure Python, no dependency) with rules: no empty
strings or empty arrays, no `^` in a telecom value, `telecom.system` in the value set, identifier
`type` present, names have `use` from the NameUse binding. `test_fhir_conformance.py` runs it over
every patient in the committed sample, the realistic set, and fixtures from all 9 shards (sampled).
Running the official HL7 FHIR validator jar once per release is recommended as a manual step; it is
not added to CI or to dependencies.

**Positive labels that depended on `name[1]`.** Today `marriage_variant` / `surname_change` derive a
prior name from `MOTHERS_MAIDEN_NAME` (session 15, F4). Moving it to an extension changes which
sources have a recoverable prior surname. The audit re-checks recoverability and the positive count
for those subtypes; any case the CMS rules can no longer resolve is dropped by `case_exclusions.py`
rather than relabelled.

**Decision (2026-10-15): `marriage_variant` is kept.** It reads the mother's maiden name from the `patient-mothersMaidenName` extension and takes its donor address from the held-out donors (not the next patient). It stays an approximation, since a mother's maiden name is not the patient's own, so `surname_address_change` (a donor surname plus a donor address) was added as the better-founded surname-and-address case. The duplicate guard (`identity_guard.looks_like_same_person`) is now applied in every negative miner, so the curated tier also reports `probable_duplicate_negatives` 0.

### Workstream 2 — Reverse-blocking near-miss finder (R2, E4 foundations, PR 2)

New `evaluation/near_miss.py`.

```
index = QueryKeyIndex(sampled_queries)             # small: ~2k queries x ~30 keys
for shard in iter_shard_batches():                 # one shard in memory at a time
    for record in shard:
        for query_id, shared in index.lookup(record):
            if is_possible_same_person(query, record): continue
            keep(query_id, record, shared)         # reservoir-capped per (query, shared-field set)
```

Near-miss kinds (`shared_fields` is recorded, as the miners do today):

| Kind | Shares | Differs | Replaces / extends |
|---|---|---|---|
| `dob_zip` | DOB + ZIP | surname | `mine_shared_address_hard_negatives` |
| `name_exact` | first + last | DOB, ZIP | new |
| `name_near` | first + last within edit distance 1 | DOB, ZIP | `mine_name_collision_negatives` |
| `dob_only` | DOB | everything else | new (decoy only) |
| `address` | street + ZIP | name | new |
| `phone` / `email` | contact value | name, DOB | new |
| `surname_zip` | surname + ZIP | given name | `mine_sibling_negatives` input |

- **Edit distance 1 without O(n²):** index the deletion neighborhood (every single-character
  deletion of the normalized name) for each query name; a record matches if its own deletion
  neighborhood intersects. O(L) per record, no pairwise comparison.
- **Caps:** per (query, kind) reservoir size (default 3) so a common DOB cannot flood a pool; the
  manifest reports yield per kind.
- **Determinism:** one RNG per query, keyed `f"{seed}:near_miss:{query_id}"` (same pattern as
  `population_topup`), shard order fixed.
- **Existing miners stay** (they still serve the committed sample and unit tests). Both tiers call the
  new finder for the realistic export, so tier parity holds.
- **Native duplicates:** every candidate decoy passes `is_possible_same_person` and `is_probable_duplicate`
  (typo duplicates), against both the housed query and its pre-household original; the independent
  `probable_duplicate_negatives` check in `audit.py` (enforced, max 0, both tiers) reports any leakage.

Out of scope for PR 2: changing pool composition or pair counts (PR 3 and PR 4).

### Workstream 3 — Population tier: harder decoys and query-size spread (E3, E4, PR 3)

1. **Decoys.** Pool assembly order becomes: true matches, then near-miss decoys (Workstream 2), then
   existing constructed/special-population decoys, then random top-up **only for the remainder**.
   Target: at most 50% of decoys share nothing with the query (default; the reviewer's concern is the
   97% figure). Production candidates come from a blocking step, so most decoys *should* resemble the
   query; keep a minority of random decoys as the easy-rejection control.
2. **Pool composition metadata.** Each query row gains `strata.decoy_kinds` (count per kind) so
   consumers can slice FDR by decoy difficulty. Additive.
3. **Expected-match spread.** Add a per-query `n_true_matches` draw from a configurable distribution
   (default placeholder: 0 → 15%, 1 → 35%, 2+ → 50%) applied by choosing which generated variants
   a query keeps, never by relabelling. Zero-match queries are not empty pools; they are pools of
   near-misses only, which is exactly the case where a matcher should return nothing. Distribution is a
   profile input (`DriftProfile`) with a `has_public_estimate=False` placeholder, per the repo's
   cited-or-placeholder rule. The reviewer's own duplicate-rate data is the best source (Open
   Question 4).
4. **Metrics note.** `cases/README.md` documents that FDR on a pool of near-misses is expected to be
   higher than on random pools, and that precision numbers are only comparable at equal decoy mix.

### Workstream 4 — Pairwise tier: negative balance, and the release route (R3, R1, PR 4)

1. **Negative generation.** Add, per source patient, *near-miss negative pairs* drawn from the
   Workstream 2 index (the same decoys that populate the pool), in proportion to that patient's
   positive scenarios. Target: 50% negatives (decided), giving an all-"match" F1 of 0.67
   (F1 = 2p/(1+p), p = positive share); about 8k negatives at current size gives ±0.3pp standard error
   on a 2% FPR. If near-miss yield is thin, subsample positives before adding weak negatives. The per-provision tier stays deliberately
   unrepresentative; only the *floor* moves.
2. **Hard-negative scenarios paired to positives.** For each positive scenario (surname change,
   address move, phone churn, ...), emit a matched negative with the **same drifted field pattern but a
   different person** (for example, two records sharing a stale phone number but differing in name and DOB).
   This keeps single-field matchers honest per scenario, not just overall.
3. **Gate.** Add `all_yes_f1` (max 0.70, `enforced`) and `negative_share` (min 0.45, `enforced`; slack under the 0.50 target) to
   `release_thresholds_realistic.json`, plus `hard_negative_count` min per category, computed in
   `audit.py`. A new baseline `always_match` is added to `naive_baselines.py`.
4. **Release route.** Remove the ignore rule for `realistic_*.jsonl` and `realistic_manifest.json`,
   commit the files, and change `release_gate.run("realistic")` to run in CI against the committed
   files (`build_and_test.yml`). Add a CI test that the manifest's `dataset_version`, seed and
   profile source match the code, so a stale commit fails. The old committed sample (`sample_*`,
   `population_*`) is either deprecated with a pointer or kept as a "curated per-provision" artifact
   (Open Question 1). A regeneration drift check (regenerate in a nightly job and diff the
   manifest hash) is optional.

### Workstream 5 — Enhancements (E1, E2, PR 5)

**E1 Family structure.** Reverse blocking also solves this. After sampling minors, stream shards
for same-surname adults (surname is alphabetical, so within-shard), choose a parent-age-compatible
adult (gap ≥ 15), and **add the adult to the sample** as a household member (their age band's quota is
reduced by the added count, so band error stays within the 1% gate). The minor receives the adult's real
address and, with the existing sharing rates, phone/email. Outcome metric:
`minors_with_same_surname_adult` (reported in the manifest and gated, target is a profile input,
default ≥ 70%; Open Question 6). Natural near-twins (same surname, same DOB, different given name,
same address) are found by the same index (`surname_zip` + `dob`). Literal twins stay out of scope
per CMS spec §IV.G (`special_populations.py` module docstring), so "twins cases" here means
same-DOB siblings.

**E2 Birth-year distribution.** ONC cannot supply births after 2016. Options: (a) keep
`AS_OF = 2017-01-01` and document the vintage in the README and manifest (default); (b) shift every
DOB forward by a fixed number of years so ages match today's bands (changes real DOBs, breaking the
"real values copied through" rule, and invalidating anniversary-sensitive checks); (c) report both
vintages in the manifest. Recommend (a)+(c) for v1 and an explicit workgroup decision on (b). This is
Open Question 7, already open from session 15 as Open Question 5.

### Implementation map

| Component | Change | Workstream |
|---|---|---|
| `evaluation/onc_loader.py` | Conformant mapping | 1 |
| `evaluation/fhir_conformance.py`, `test_fhir_conformance.py` (new) | Structural validator + test | 1 |
| `mutations.py`, `scenarios.py`, `drift_mutations.py`, `placeholders.py`, `identity_guard.py`, `special_populations.py`, `audit.py` | Tolerate missing `given`; maiden-name source change | 1 |
| `evaluation/near_miss.py`, `test_near_miss.py` (new) | Reverse-blocking finder | 2 |
| `export_inputs.py`, `export_realistic_dataset.py` | Second streaming pass for near-miss decoys | 2 |
| `population_cases.py`, `drift_profile.py` | Pool assembly order; match-count spread; `strata.decoy_kinds` | 3 |
| `labeled_pairs.py`, `export_test_dataset.py` | Near-miss negative pairs; matched negatives per scenario | 4 |
| `audit.py`, `naive_baselines.py`, `release_thresholds_realistic.json`, `release_gate.py` | `all_yes_f1`, `negative_share`, per-category minimums | 4 |
| `.gitignore`, `.github/workflows/build_and_test.yml`, `evaluation/cases/*` | Commit realistic set; gate it in CI | 4 |
| `household_assignment.py`, `population_sampling.py` | Parent-first households; add adults to sample | 5 |
| `cases/README.md`, `DESIGN.md`, `CLAUDE.md` | Tiers, changelog, `dataset_version` | all |

## Rollout

1. **PR 1 — Conformance (R4).** Scope: loader + validator, plus deleting the stale rule-29 caveat. Defers all sampling and pool changes.
   Regenerates both datasets; positive/negative counts must match except the documented
   maiden-name subtypes.
2. **PR 2 — Near-miss finder (foundation).** Scope: module + export plumbing + yield report, no
   change to emitted cases. Records per-kind yield so PRs 3-4 can set caps from data.
3. **PR 3 — Population decoys and match-count spread (E3, E4).** Defers pairwise-tier changes.
4. **PR 4 — Pairwise balance and release route (R3, R1).** Defers family structure.
5. **PR 5 — Family structure and vintage (E1, E2).** Can ship after v1.

PR 2 follows PR 1; PRs 3 and 4 each follow PR 2 and are independent of each other; PR 5 follows PR 2.
If any of these is opened stacked on another, merging is left to the maintainer.

**Decision (2026-10-14):** shipped as one PR (former PRs 1, 2, 4 and the decoy part of PR 3), one commit per workstream. Still deferred: queries with 0 or 1 expected matches, `strata.decoy_kinds`, family structure (PR 5), age vintage.

**Versioning.** `dataset_version` bumps in PR 1 (resource content changed) and again in PR 4
(committed files replaced). `case_id`s for existing categories are stable; new categories add ids.

## Release caveats: what blocks inclusion of the realistic set

`export_realistic_dataset.py` writes five caveats (`CAVEATS`) into `realistic_manifest.json`. Status
and resolution:

| # | Caveat | Status | Resolution | Blocks inclusion? |
|---|---|---|---|---|
| 1 | Not filtered for CMS Table 2 rule 29 (BAI-1061) | **Closed.** Commits `bd4f4ae` and `ea2d2e2` moved the exclusion into the generators | Line deleted from `CAVEATS` | No |
| 2 | Drift positives not verified against the CMS reference algorithm | Open; this repo has no matching engine | Reviewer runs the realistic positives through their CMS 3.3.0/3.4.0 harness after PR 4 and returns rejected case ids; we drop or fix them via `case_exclusions.py`. Manifest keeps the caveat until they confirm (open question 8) | No, but must stay disclosed |
| 3 | Drift and household sharing rates are placeholders | Open | Reviewer supplies measured cross-organization rates (session 15, open question 1). Without them the profile stays `has_public_estimate=False` and the dataset is marked provisional | No; ship as provisional |
| 4 | Households are mostly unrelated real records at one address | Open; reviewer enhancement E1 | PR 5 (parent-first households, gated same-surname minors rate). Until then, disclosed in the manifest and `cases/README.md` | No |
| 5 | Mined sibling, name-collision and hard-negative categories are scarce | **Closed.** Near-miss finder and negative rebalance; `missing_hard_negative_categories` is enforced in the realistic gate (0 missing). Pairwise counts: `hard_negative` 625, `name_collision_negative` 1,488, `sibling_negative` 530, `near_miss_negative` 11,449 | **Yes** |

**Inclusion criteria for v1:** reviewer blockers R1-R4 closed, caveat 5 closed, realistic gate green
from a fresh clone in CI, and the manifest and `cases/README.md` list every caveat still open
(2, 3 and 4 if PR 5 has not shipped).

**Status at release (2026-10-14):** caveats 1 and 5 are closed. Caveats 2, 3 and 4 remain open and disclosed. Update (BAI-1162): population pools now keep up to 8 look-alikes per kind, so `decoy_no_overlap_rate` is 0.4707 and enforced, and the "harder decoys" ask (E4) is met. Also open: E3 (queries with exactly 0 or 1 expected matches), E1 (family structure) and E2 (age vintage) are not addressed. Measured on the realistic set: `negative_share` 0.556, `all_yes_f1` 0.6149, `best_single_field_f1` 0.8755 (enforced, max 0.9), `multi_field_margin` 0.1029, `pairwise_two_of_three_f1` 0.8991 (tracked, max 0.95), `probable_duplicate_negatives` 0 (enforced), 0 positives dropped by rebalancing (near-miss negatives alone exceeded the 50% target). The final review also found typo duplicates and original-record matches among the decoys; both are now rejected in `near_miss.py` (default run: 11 typo-duplicate decoys rejected against the housed query, 4 against the pre-household original).

**Asks of the reviewer** (shortens the path): (a) run the realistic positives through the CMS harness
once PR 4 lands; (b) share measured disagreement and share rates now, which closes caveat 3.

## Non-goals

- Fully synthetic generation (rejected in session 15).
- Literal twins as should-not-match cases (spec §IV.G).
- Post-2016 birth years (cannot be sourced from ONC; see E2).
- Mapping `MRN` (the loader ignores it today; adding an identifier needs a synthetic assigner system
  and adds a matching signal the CMS spec does not use).
- Scoring any matcher in this repo beyond the dependency-free naive baselines.

## Tradeoffs

| Benefit | Cost |
|---|---|
| Hard negatives, harder decoys and family structure from one mechanism | One more streaming pass over all shards (about a minute) and a new module to maintain |
| Decoys are real ONC records, so no fabricated identities | Natural yield per kind is data-dependent; some kinds (for example `address`) may be thin and need a cap or a tagged constructed fallback |
| Conformant resources | Resource shape changes, so consumers pinned to the old shape (`given` including aliases, second `name`) must re-run; a documented changelog covers it |
| Near-miss pools give realistic FDR | FDR/precision on the new pools are not comparable to numbers from the previous release |
| Committed realistic set matches what a clone gets | Repo grows by ~51 MB and a CI gate has to stay green |

## Risks / stress test

- **Strongest counterargument:** adding negatives to hit a target ratio is tuning the benchmark to the
  reviewer's metric. Mitigation: the negatives are real look-alikes, labelled by construction, and the
  gate is a floor on `negative_share` and `all_yes_f1`, not on any real matcher's score.
- **Hidden assumption:** ONC has enough natural look-alikes per query. Validate with the PR 2 yield
  report before committing to caps; the fallback for thin kinds is the existing constructed pattern
  with `strata.address_source = "constructed"`.
- **Maiden-name extension (decided):** if the reviewer's matcher expects `name[1]` with `use: maiden`
  from the source, moving it to the extension changes their results. Call it out in the changelog.
- **Reversibility:** all additive, except the resource-shape change (one-way once adopted) and the
  committed-release route (reversible by re-adding the ignore rule, but consumers may have cloned).

## Open questions

| # | Question | Needed from | Impact |
|---|---|---|---|
| 1 | Is the realistic set the v1 release, with the old committed sample demoted or removed? | Maintainer / reviewer | Final shape of PR 4 and `cases/README.md` |
| 2 | ~~Maiden name mapping~~ Resolved: standard mother's-maiden-name extension | n/a | PR 1 still re-checks affected positives |
| 3 | ~~Telecom use/period~~ Resolved: only where history is modelled. Still open: which conformance profile (base R4, US Core, CMS)? | Reviewer | Validator rule set |
| 4 | Target distribution of expected matches per query (zero / one / many) | Reviewer | Defaults in Workstream 3 |
| 5 | ~~Negative share~~ Resolved: 50% target, gate ≥ 0.45 and all-yes F1 ≤ 0.70 | n/a | Reviewer may adjust |
| 6 | Target share of minors with a same-surname adult | Reviewer / Census | E1 gate |
| 7 | Age vintage: keep 2017 as-of, or shift births forward | Workgroup | E2 |
| 8 | Can the reviewer share the CMS 3.3.0/3.4.0 harness? | Reviewer | Before/after for R3's 98.5% and 3.4.0 |

## Success criteria

- [ ] `test_fhir_conformance.py` passes over both release datasets and a per-shard sample: no empty
      strings, no `^` in telecom, identifiers typed, every `HumanName` has a binding-valid `use`.
- [ ] Realistic set contains hard-negative, name-collision and sibling cases at or above the committed
      set's counts (per-category minimums in `release_thresholds_realistic.json`, enforced).
- [ ] Pairwise tier: `negative_share` ≥ 0.45 and `always_match` F1 ≤ 0.70 (enforced); realistic set
      passes the existing realism floors **from a fresh clone** in CI.
- [ ] Population tier: ≤ 50% of decoys share nothing with their query; queries with 0 and 1 expected
      matches both present; `strata.decoy_kinds` populated.
- [ ] Tier parity gap is still 0; same-person-in-negatives is still 0 (independent detector).
- [ ] (PR 5) Minors with a same-surname adult meet the profile target; age-band error stays ≤ 1%.
- [ ] Reviewer re-runs the CMS-algorithm comparison; always-match is no longer a ~98% score.
