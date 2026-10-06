# Session 15 — Label Validity, Drift Realism, and a Release Gate

**Status:** Draft, not yet reviewed. Written 2026-10-06 in response to written feedback from a
workgroup reviewer on the post-session-14 test set ("getting closer to a solid first release").
**Author:** Imran Qureshi
**Ticket:** TBD (project BAI unless the workgroup board says otherwise)
**Thread:** Evaluation & Statistical Rigor Framework
**Estimated size:** L — one new module family (audit/baselines/sampling), four generator changes,
one refactor of the true-match generation loop. Recommend shipping as four PRs (see Rollout);
this is more than the 2-3 responsibilities a single session should carry.

## Summary

The reviewer found three defects that make some labels wrong or some categories untestable, six
realism gaps, and one meta-check that fails: a single-field phone matcher scores 98.6% F1 and a
3.5x better false-positive rate than the CMS proposed algorithm. We (1) fix the label-validity
defects first, since a wrong label is worse than a missing scenario, (2) add the missing drift
scenarios and population realism, and (3) add an in-repo audit + naive-baseline gate so "is this
ready to release" becomes a CI check rather than a reviewer's judgment.

## Findings, verified

I re-ran each claim against the committed `evaluation/cases/sample_labeled_pairs.jsonl`
(11,668 rows; 2,000 distinct source patients). All reproduce except where noted.

| # | Reviewer's claim | Reproduced | Root cause in code |
|---|---|---|---|
| F1 | 39/81 sibling non-matches share first+last+DOB; 19 share SSN | **39/81, 19/81** | `mine_sibling_negatives` → `_mine_same_surname_zip_pairs` (`special_populations.py`) buckets on (ZIP, surname) and a birth-year gap ≤3. It never checks given name, full DOB or SSN, so a duplicate record of one person under two EnterpriseIDs passes. |
| F2 | 262/262 "multi-generational" non-matches have different street | **262/262** | Same miner bucketed on ZIP, not street. The category as built never shares an address. |
| F3 | 96% of addresses hold one person (1.06/address) | 1.11 people/address on the 2,000 source patients | ONC addresses are near-unique per record; nothing in the pipeline creates co-residents except the institutional constructor. (Gap vs. 1.06 is counting method; the audit module will pin the definition.) |
| F4 | marriage_variant: surname changes in 117/1,980; 117/117 recoverable from name[1] | **117/1,980; 117/117** | `marriage_variant` (`mutations.py`) only changes surname when `name[1]` (MOTHERS_MAIDEN_NAME, ~5.3% of ONC) exists, and the new surname *is* `name[1]` on the source. In the other 94% only the address changes, which is why address drift is all labeled "marriage". |
| F5 | Phone changes in 104/11.5k positives | **104/11,222 positives (0.93%)** | `phone_variant` needs a distinct PHONE2 (~5% of records). Reviewer's positive count (11,539) differs from the file (11,222); the working tree has uncommitted export changes, so their snapshot may differ. |
| F6 | Age: 8% <18, 21% 85+ | **8.0%, 21.1%** (as of 2026) | Not a generator choice. `labeled_pairs.py`/`export_*` take `load_onc_patients([shard])[:SAMPLE_SIZE]`, i.e. the first N rows of one alphabetically sorted shard, inheriting ONC's age skew and a surname skew (first record is `AABERG`). |
| F7 | Phones near-unique (1,889 distinct / 1,947 records) | 1,993 distinct / 1,947 records with a phone (counts PHONE2) | Same as F3. |
| F8 | Gender differs in 0 positive pairs | **0/11,222** | No mutator touches `gender`. |
| F9 | Phone-only matcher: 98.6% F1 | Not reproducible here (no engine since session 13) | **Population tier never contains session-14 scenarios.** `population_cases.build_population_dataset` builds positives only from `fuzzy_variant` and diacritic/punctuation, none of which touch phone, and negatives never share one. Phone-only gets perfect recall by construction. |

**F9 is the most important finding.** Fixing the per-provision pairs alone would not move the
reviewer's headline check, because it is computed on the population tier, which does not yet
include ssn_dropped, marriage, phone, compound, sibling or name-collision cases at all.

**Side finding.** `CLAUDE.md` says every EnterpriseID is unique so "zero duplicate-person
clusters exist natively". True for IDs, but F1 shows the same person (same name, DOB and in 19
cases SSN) exists under different IDs. Any miner that assumes distinct ID ⇒ distinct person
mislabels. These native duplicates are either a label hazard (F1) or free naturally-occurring
positives (see Open Question 3).

## Constraints

- **Design Principle (CLAUDE.md):** no fabricated identities; real ONC records stay real. Fabricated
  values (addresses, new phones) must be unambiguously synthetic or drawn from a held-out real
  record. Carried forward unchanged.
- **Prevalence rule:** every category's `frequency` comes from a cited estimate or an explicit
  `has_public_estimate=False` placeholder, never a guess (`prevalence_estimates.py`). New drift
  rates below are therefore *inputs*, not constants we pick.
- **Memory & scale:** no all-9-shard in-memory list. New sampling must stream/shard-wise.
- **Two tiers stay separate:** precision/F1 only on the population tier (`cases/README.md`).
- **Additive schema:** existing JSONL keys unchanged; consumers already pin `case_id` strings.
- **Repo conventions:** `from __future__ import annotations`, `typing.Dict/List`, ruff + mypy clean,
  one same-named `test_*.py` per generator.

## Alternatives considered

**A. Patch each finding in place (one flag per new scenario).** Adds ~6 more `include_*` booleans
to `generate_raw_pairs` (already 9). Fast, but every scenario is duplicated again in
`population_cases.py` — which is exactly how F9 happened. ❌ Rejected for scenarios; accepted for
the pure bug fixes (F1, F2).

**B. Adopt Epic's fully synthetic generator (SSA/Census-sourced) instead of ONC mining.** Would
fix age and household realism at the source. ⚠️ Already explicitly deferred in session 14 as an
architectural question; it also abandons the no-fabricated-identity principle. Would reconsider
if the workgroup decides ONC cannot supply enough minors/households after Workstream D.

**C. Reweight instead of resample (post-stratification weights on age).** Keeps data as is and
attaches a weight per case. ⚠️ Fine for per-provision aggregates, wrong for the population tier,
where precision/FDR depend on the actual candidate mix in each pool. Used only as the fallback
for the full-dataset export (see D1).

**D. Do nothing / ship with caveats.** Not viable: F1/F2 are wrong labels in a published set.

## Proposed solution

Four workstreams, each its own PR. Scope boundaries are explicit so reviews stay separable.

### Workstream A — Label validity (blocker, PR 1)

Bug-level; no new categories.

1. **`is_possible_same_person(a, b)`** in a new `evaluation/identity_guard.py`: true if non-placeholder
   SSNs match, or normalized (first given, family, birthDate) match. Every negative miner calls it
   and skips the pair. Normalization is local to the guard (casefold, strip punctuation/diacritics);
   emitted data stays un-normalized per the existing convention.
2. **Sibling miner:** additionally require first given names to differ. (Twins may share DOB; they
   are still excluded from "same person" only if names/SSN also match.)
3. **Household miner:** bucket on `(street line, postalCode, surname)` and keep gap ≥15. Natural
   yield is expected to be tiny (F3), so add a *constructed* path mirroring
   `construct_institutional_negatives`: take a real adult and a real distinct younger same-surname
   record and give the younger one the adult's real address. Tag `strata.address_source =
   "constructed"` and the rationale. Mined and constructed counts are reported separately.
4. **Label-validity invariant test** (`test_label_validity.py`): over every negative category, no
   pair satisfies `is_possible_same_person`. This is the regression test for F1 and runs in CI.

Out of scope for PR 1: new scenarios, population-tier changes.

### Workstream B — True-match drift scenarios (PR 2)

Replace the growing flag list with a small registry, then add scenarios to it. A `Scenario` is a
callable `(patient, context) -> Patient | None` registered under a stable name plus a prevalence
entry; `generate_raw_pairs` and `build_population_dataset` both iterate the same registry, which
removes the F9 class of bug (a category existing in one tier only). Existing categories are
migrated to the registry with identical `case_id`s and output.

| Scenario | Models | Mechanism |
|---|---|---|
| `surname_change` (replaces `marriage_variant`'s name half) | Marriage/divorce name change | Source holds only the prior surname with **no `name[1]`**; target holds a new surname drawn from the held-out donor pool. Subtypes: `no_history`, `prior_name_on_target` (name[1] carries it, `use: maiden`), `hyphenated`. Address untouched. This is the "must be recovered" case the reviewer found missing. |
| `address_move` (replaces `marriage_variant`'s address half) | Move, with history | Subtypes: `current_vs_prior` (source = old address, target = new), `history_on_one_side` (target carries both, new one `use: home` with `period.start`, old one `use: old` with `period.end`). Donor address from the held-out pool, same-state weighted. |
| `phone_churn` (replaces `phone_variant`) | Contact churn | Target gets a replacement phone from the held-out donor pool (real ONC numbers on no in-set record), or phone dropped, or a PHONE2 swap. No longer gated on PHONE2 existing. `email_churn` follows the same shape. |
| `gender_drift` | Administrative-sex disagreement | male↔female, ↔unknown, composed with another field change so gender is not the only signal. |
| `placeholder` | Placeholder values | One side carries a well-known placeholder in SSN (`000-00-0000`, `999-99-9999`, `123-45-6789`), DOB (`1900-01-01`, `1901-01-01`, `01-01` of any year), phone (`000-000-0000`, `555-555-5555`), name (`BABY BOY`, `UNKNOWN`), or address (`HOMELESS`, `UNKNOWN`). Positives: other fields still match. Negatives: two distinct people share the placeholder and must not match on it (new `placeholder_collision_negative`). A single curated, versioned catalog lives in `placeholders.py`. |

**Held-out donor pool.** New phones, addresses and surnames come from a reserved slice of ONC that
is excluded from the generated set, so a donor value never collides with a real in-set record.
This keeps labels pure while the values stay real (no fabricated identifiers needed).

**Rates are inputs.** Per-scenario targets come from a `DriftProfile` (JSON, loaded by the export
scripts) so the workgroup can set them from measured cross-organization disagreement rates. We do
not hard-code a number: the repo's rule is cited-or-placeholder, and the reviewer's own data is the
best source. Default profile ships with `has_public_estimate=False` placeholders and a clear
"override me" note. For the headline concern, the default raises `phone_churn` from 0.93% of positives to a
documented placeholder at least one order of magnitude higher; the actual value is Open Question 1.

Out of scope for PR 2: population-tier distribution (Workstream C) — but PR 2 *does* wire all
registry scenarios into the population tier, fixing F9's structural cause.

### Workstream C — Population realism (PR 3)

1. **`population_sampling.py`: `age_stratified_sample(patients, target_bands, n, rng, as_of)`.**
   Replaces `[:SAMPLE_SIZE]` in all three export scripts with a seeded, random, band-stratified
   draw across shards (one shard at a time, per Memory & scale; reservoir per band). Target
   bands come from a cited Census ACS age table added to `prevalence_estimates.py`. `as_of` is a
   fixed constant (not `date.today()`) so output is deterministic. Fixes F6 and the surname skew.
   **Feasibility caveat:** if ONC is ~8% minors overall, the full ~1M export can hold at most
   ~380k records at 21% minors. For `make generate-full-dataset` we cap N by the scarcest band
   and say so in the manifest; Option C weights are the fallback. Step 1 is to measure band
   supply across all 9 shards.
2. **Household assignment (`household_assignment.py`).** Post-process the sampled population into
   households whose size distribution follows a cited Census household-size table (mean ≈2.5):
   group real records by surname and age compatibility, overwrite addresses with a shared real
   address (same technique as Workstream A.3). Fixes F3; also yields the co-resident
   non-match pairs the multi-generational category was meant to supply.
3. **Shared contacts.** Within a household, set phone and/or email to a shared value at a
   configurable `shared_contact_rate`; for members under 13, the contact is always a guardian's.
   Children are the hard case the reviewer named: shared surname + shared address + shared phone,
   near-identical DOB for siblings, no SSN. This produces the child/parent pairs and the
   shared-phone distractors that break phone-only matching (F7). Rate is a profile input
   (the reviewer reports >50% at some organizations).
4. **Minor-specific profile:** minors get a higher SSN-absent rate and the `placeholder` newborn
   name scenario.

All constructed fields are tagged in `strata` so a consumer can slice results by "natural vs.
constructed".

### Workstream D — Release gate: audit + naive baselines (PR 0, ships first)

Build this first, so every other PR reports before/after numbers instead of anecdotes.

- **`evaluation/audit.py`**: computes the reviewer's metrics (people/address, shared-phone rate,
  age bands, per-field positive disagreement rates, same-person-in-negatives count, per-category
  yield) and emits a JSON report. `test_audit.py` asserts thresholds from a checked-in
  `release_thresholds.json`.
- **`evaluation/naive_baselines.py`**: dependency-free reference matchers, no engine required:
  phone-only, SSN-only, email-only, exact name+DOB, address-only, fuzzy-name-only, and a simple
  weighted multi-field matcher. Scored through the existing `rule_eval.py` harness on the
  population tier.
- **Gate:** (a) no single-field baseline's F1 exceeds a ceiling; (b) the multi-field baseline beats
  every single-field baseline by a margin; (c) label-validity count is zero. Thresholds are Open
  Question 2. Comparison against the CMS proposed algorithm (the reviewer's exact check) stays an
  external workgroup step, since this repo has had no matching engine since session 13; the audit
  report is the artifact they run it against.

### Implementation map

| Component | Change | Workstream |
|---|---|---|
| `evaluation/audit.py`, `naive_baselines.py`, `release_thresholds.json` (new) | Metrics, baselines, gate | D |
| `evaluation/identity_guard.py` (new) | `is_possible_same_person` | A |
| `special_populations.py` | Sibling given-name check; street-level + constructed household | A |
| `hard_negatives.py` | Call guard in both miners | A |
| `evaluation/scenarios.py`, `drift_profile.py`, `placeholders.py` (new) | Registry, rates, placeholder catalog | B |
| `mutations.py` | Replace `marriage_variant`/`phone_variant`; add gender/email/placeholder mutators | B |
| `labeled_pairs.py`, `population_cases.py` | Iterate registry; drop per-scenario flags | B |
| `population_sampling.py`, `household_assignment.py` (new) | Age-stratified sampling; households and shared contacts | C |
| `export_*.py` | Use sampler and profile; manifest records profile and as-of date | C |
| `prevalence_estimates.py` | Entries for every new category (cited or placeholder) | B, C |
| `cases/README.md`, `DESIGN.md`, `CLAUDE.md` | New strata keys, tiers, dedup caveat | all |

## Rollout

1. **PR 0 — Gate (D).** Adds audit + baselines; records the "before" numbers (including the
   reviewer's F-table) in the PR. No generator changes. Scope: measurement only.
2. **PR 1 — Label validity (A).** Defers all new scenarios.
3. **PR 2 — Drift scenarios + registry (B).** Defers sampling/household realism.
4. **PR 3 — Population realism (C).** Defers any change to scenario definitions.

PRs 1 and 2 are independent of each other after PR 0 (neither is stacked on the other); PR 3 needs
PR 2's registry. Per standing policy, if PR 3 is opened stacked on PR 2, merging is left to the
maintainer.

**Versioning:** `marriage_variant` and `phone_variant` case_ids are replaced, which is a
breaking change for consumers pinned to them. Ship as a new dataset version with a short
changelog in `cases/README.md`; keep old ids out rather than aliasing them, since their semantics
changed.

## Non-goals

- Adopting Epic's fully synthetic population (Alternative B).
- Scoring any algorithm inside this repo beyond the dependency-free baselines.
- Modeling twins as a should-not-match case (spec §IV.G treats them as unresolvable).
- Calibrating drift rates ourselves without the workgroup's measured data.

## Tradeoffs

| Benefit | Cost |
|---|---|
| Wrong labels removed before first release | Existing case_ids change; consumers re-pin |
| One registry feeds both tiers; F9 cannot recur | Refactor touches the two core generators |
| Rates are workgroup inputs, nothing guessed | Release is blocked on supplied numbers or ships with placeholders |
| Constructed addresses/contacts reach realistic household density | Sharing is synthetic structure on real identities; tagged and sliceable, but not "natural" |
| Gate turns readiness into a CI check | Naive baselines are our definition of "bad"; thresholds are a judgment call |

## Risks / stress test

- **Strongest counterargument:** constructed households and shared contacts bake our assumptions
  into the benchmark and could favor algorithms tuned to them. Mitigation: tag everything
  constructed, publish natural-only slices, and let the workgroup own the profile.
- **Hidden assumption:** ONC has enough minors and enough same-surname adults to build households.
  Validate with the PR 0 audit across all 9 shards before committing to C.
- **Donor pool shrinks the usable population** slightly; negligible at 1M.
- **Reversibility:** all additive behind the registry and profile, except the case_id change, which
  is one-way once consumers adopt it. Decide the versioning policy before PR 2 merges.

## Open questions

| # | Question | Needed from | Impact |
|---|---|---|---|
| 1 | Measured per-field disagreement rates between real organizations (phone, email, address, surname, gender, placeholders) and share rates for phone/email | Reviewer / Epic | Sets `DriftProfile` defaults; blocks "ready" for B and C |
| 2 | Gate thresholds: max single-field baseline F1, required margin for multi-field baseline | Workgroup | Defines "ready to release" in D |
| 3 | The ~39 native same-person pairs found in F1: drop them, or keep them as a `native_duplicate` positive category? | Workgroup | A yields extra real positives; avoid hand-adjudicating |
| 4 | Does gender participate in any CMS Table 2 rule, so does gender drift change any expected label? | Spec reading / workgroup | Whether `gender_drift` is expected-match or an "algorithm should ignore it" case |
| 5 | Age as-of date and target table (ACS vintage) | Workgroup | Determinism of C; reviewer's figures reproduce at 2026 |
| 6 | Versioning/changelog policy for case_id changes | Maintainer | PR 2 release mechanics |
| 7 | Can the reviewer share their phone-only/CMS-algorithm harness? | Reviewer | Lets us reproduce F9's 98.6% and 3.5x numbers as a before/after |

## Success criteria

- [ ] `test_label_validity.py` passes: zero negatives satisfy `is_possible_same_person` in every category.
- [ ] Household category: ≥ the mined+constructed count target, 100% share a street line.
- [ ] Surname-change positives: ≥ the profile rate, 0% recoverable from a name entry on the source.
- [ ] Positives where phone differs, and where gender differs, meet the profile rates (non-zero, workgroup-set).
- [ ] Population-tier age bands within tolerance of the cited Census table; people/address and
      shared-phone rate within tolerance of profile targets.
- [ ] Every scenario appears in **both** tiers (audit asserts parity).
- [ ] Phone-only baseline F1 below the agreed ceiling; multi-field baseline beats every single-field baseline.
- [ ] Reviewer re-runs the CMS-algorithm comparison and the phone-only result is no longer the headline.
