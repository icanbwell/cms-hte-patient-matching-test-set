# Session 12 — Align Test-Dataset Generation with the Finalized Cross-Org CMS Proposal

**Status:** completed (executed 2026-08-31, same session as authoring — no PR/reviewer yet;
see Execution notes)
**Thread:** Evaluation & Statistical Rigor Framework
**Estimated size:** L — one new test tier (generator module + manifest format + tests), plus
several smaller doc/metadata alignment fixes across existing modules.

> This session doc originated in the repo this test-data generation code was split out of. See that repo's own session-doc conventions if you need them (not carried over here).

## Outcome purpose

The cross-org workgroup has finalized its test-dataset methodology: ["A Shared Test Dataset for
CMS Patient Matching Compliance — Proposal
(current)"](https://docs.google.com/document/d/1A96--dAjIwID5RCDr9qZeqDnk6snOqNcQOg1ZBy3FWw)
(referenced below as **"the current Doc"**). This repo's generation code (sessions 9-10) was
built against an earlier, options-heavy draft, ["Proposal: A Shared Test Dataset for CMS v3.3.0
Patient Matching
Compliance"](https://docs.google.com/document/d/1N6IQkaLkKPdQKVxPSWZYDaLbTCx0EYEgwBcCCPk-6pk)
(referenced below as **"the draft Doc"**, still cited throughout `SYNTHETIC_DATA_COMPARISON.md`
and `cases/README.md`). This session diffs the two documents against this repo's actual code and
closes the gaps.

**The headline finding is reassuring: most of the draft Doc's substance survived finalization
unchanged**, and this repo already implements it — ONC as the seed population (draft §1 Option
A), the per-provision ground-truth categories (draft §2 → `mutations.py`/`hard_negatives.py`/
`special_populations.py`/`normalization_edge_cases.py`), the portable JSONL manifest (draft §3 →
`export_test_dataset.py`), and precision/recall/FPR-with-NA-disclosure reporting broken out by
category (draft §5 → `cases/README.md`'s "Option A"). No rework needed there.

**Five real deltas surfaced by the diff, in descending order of engineering cost:**

1. **New test shape, not just new cases.** The current Doc adds a second test kind absent from
   the draft entirely: "query against a population" — one record queried against a candidate
   pool, expected answer a *set* (possibly empty, possibly several), explicitly modeled on FHIR
   `Patient/$match`. This repo has only ever built the first kind (per-provision pairs). This is
   the session's main scope item (Task 2-3 below).
2. **A verified, not just flagged, data-provenance problem.** The current Doc's stated reason for
   adopting ONC changed from the draft's hedged "may not carry authoritative... ground truth" to
   an affirmative claim: *"it ships its own answer key: the enterprise patient identifier. Same
   identifier means same person... group by enterprise patient ID, never by row ID."* Direct
   inspection of this repo's vendored files (below, Task 1) shows that claim does not hold for
   *this specific copy* of the dataset. `SYNTHETIC_DATA_COMPARISON.md` already flagged this as
   "worth checking, not resolved" after session 9; this session resolves it.
3. **The metrics-validity fix changed shape.** The draft Doc's own text already warned that a
   single blended accuracy number over a curated, rare-case-oversampled suite is misleading; this
   repo's answer (session 10) was a per-case `frequency` reweighting field
   (`prevalence_estimates.py`). The current Doc answers the same problem differently: don't
   reweight the curated suite at all — compute precision/recall/FDR "only over the realistic
   population," i.e., over a second, naturally-representative tier. That tier is exactly the
   population-query tier from delta 1 — **deltas 1 and 3 are the same missing piece**, viewed
   from two angles of the current Doc.
4. **Contribution model narrowed.** The draft's four seed-population options (A/B/C/D, with a
   real de-identification-adequacy-review gate for raw-data contribution) collapsed to two
   contribution paths for member orgs going forward: synthetic-records-derived-from-real-data, or
   aggregate statistics — with **no path for contributing raw real records at all**. This
   directly un-blocks a backlog item `SYNTHETIC_DATA_COMPARISON.md` deferred after session 9
   (client-type field-availability modeling), which was waiting on exactly this kind of
   cross-org-repo contribution review.
5. **The harness/adapter contract went from "proposed" back to "open."** The draft Doc's §6/§8
   specified a fairly detailed adapter contract (stdin/stdout JSON, `cms-match-harness score`
   CLI). The current Doc's "What we need to decide" list still carries "what exactly is the
   adapter contract?" as unresolved. Nothing in this repo depends on that contract yet
   (`SYNTHETIC_DATA_COMPARISON.md` already scoped harness-building to session 8's Tier 3 work),
   but session 8 should not assume the draft's specific JSON shape survived finalization.

## Upstream sessions (must be completed first)

- **Session 9** (`completed/`) — this session's population tier is built directly on top of
  `labeled_pairs.generate_raw_pairs()`, reused rather than duplicated, per this repo's existing
  "write the generation logic once" convention.
- **Session 10** — code (`evaluation/special_populations.py`, `evaluation/normalization_edge_cases.py`)
  is merged to `main` and already exercised by `generate_raw_pairs()`; this session's population
  tier consumes it. **Housekeeping note:** `docs/sessions/pending/session_10.md` is still in
  `pending/` despite its code being complete and in production use — a stale status flag,
  unrelated to this session's actual scope but cheap to fix in the same PR (Task 8).

Not blocked by session 6, 8, or 11 — none of this session's tasks touch Table 2 rules, the
legacy-comparison harness, or insurance-identifier fields.

## Downstream sessions (unblocked by this one)

- **Session 8** (Tier 3 legacy-comparison harness) — should consume whichever manifest format(s)
  exist once this session lands, and should re-confirm the adapter/CLI contract's status with the
  workgroup (Open Questions, below) before building against either the draft's or an assumed
  contract.
- **Session 11** (administrative-restriction/insurance-identifier pairs, blocked on session 6) —
  once unblocked, should feed both the existing pairwise manifest and this session's population
  manifest, not just the former.

## Upstream data/system dependencies

None new. Same static, already-committed inputs as session 9/10: `evaluation/fixtures/onc/*.csv`.

## Downstream data/system dependencies

None new. Outputs remain local JSONL files under `evaluation/cases/`, never persisted externally.
No real PHI is touched anywhere in this pipeline — every input is ONC's already-public synthetic
dataset — which matters directly for Task 6 below (the current Doc's provenance-disclosure
requirement).

## Scope

### In scope

1. **Verify and document the ONC duplicate-identity claim** (delta 2). Resolves the open question
   session 9 explicitly left unresolved.
2. **`evaluation/population_cases.py`** (new) — the population-query tier's generator (delta 1/3).
3. **`evaluation/export_population_dataset.py`** (new) — the population tier's manifest writer.
4. **`evaluation/cases/README.md`** updates — new "two test tiers" section, the metrics-validity
   split (precision/FDR/F1/accuracy: population tier only; recall/FPR: either tier), an FDR
   formula addition to the sample code, and updated Doc citations.
5. **`evaluation/SYNTHETIC_DATA_COMPARISON.md`** updates — record this session's diff against the
   current Doc, add a coverage-table row for the population tier, cross-reference both Doc
   versions going forward.
6. **`evaluation/prevalence_estimates.py`/`export_test_dataset.py`** docstring updates — clarify
   `frequency` is documentation/analysis metadata, not a substitute for the population tier's
   metrics (delta 3), and add the repo-level provenance/synthesis-method disclosure the current
   Doc's contribution rules call for (delta 4's technical requirement — trivially satisfied today
   since no real PHI is in the pipeline, but worth stating explicitly rather than leaving implicit).
7. **Flag, do not build,** the newly-available aggregate-statistics contribution path (delta 4) —
   an org-policy decision, not an engineering task for this session.
8. **Housekeeping:** move `session_10.md` to `completed/` (its code has been in `main` and in use
   since session 10 landed) and update `docs/sessions/completed/session_9.md`'s "Open questions"
   entry that this ONC-duplication question was ever resolved, pointing to this session.

### Out of scope

- **Building the actual reference harness or resolving the adapter contract.** Session 8's Tier 3
  territory; also explicitly reopened as unresolved by the current Doc itself (delta 5) — building
  against a specific contract now would risk building against something the workgroup already
  moved away from.
- **Sourcing an alternate, duplicate-inclusive ONC release** to satisfy the current Doc's literal
  "group by enterprise ID" language. Deliberately rejected — see Task 1's rationale: this repo's
  own single-edit variant generation already satisfies the current Doc's *stricter* contribution
  rule ("person IDs assigned by the synthesis process, not looked up from a master index") better
  than trusting ONC's native linkage would, so there is no need to chase down a different dataset
  release to unblock the population tier.
- **Administrative-restriction/insurance-identifier pairs** — session 11's scope, blocked on
  session 6, untouched here.
- **Any actual aggregate-statistics contribution to the workgroup from this organization.** Org policy/legal
  decision (Task 7 only flags that the path now exists).
- **The ≥1,000,000-record empirical collision-rate validation.** A distinct, larger,
  not-yet-scoped exercise in both Doc versions (current Doc's methodology section doesn't restate
  the draft's §4 in detail, but nothing suggests it was dropped as a requirement) — this session's
  population tier is a curated, per-query candidate pool for pairwise-style grading, not a
  population-scale collision-rate study.

## Tasks

1. **Verify the ONC duplicate-identity claim (delta 2).** Count `EnterpriseID` occurrences across
   all nine vendored shards. **Already run once during this session's design** (not gated on
   implementation): all 1,000,000 rows have unique `EnterpriseID` values — zero duplicates. This
   means:
   - `onc_baseline.py`'s existing "different `EnterpriseID` ⇒ different person" true-negative
     sampling assumption is **confirmed safe** for this fixture set (a small piece of good news
     worth recording, not just a gap to close).
   - The current Doc's "same identifier means same person" / "group by enterprise ID, not row ID"
     framing does not describe *this* vendored copy — there is no found duplication to group.
     Whatever the workgroup meant by that language (a different ONC release variant with
     multiple records per person, or a description that doesn't match this repo's specific
     download), it should not be silently assumed true here.
   - Document this finding in `evaluation/onc_loader.py`'s module docstring and
     `SYNTHETIC_DATA_SETUP.md`, and raise it with the workgroup (see Open Questions) — this
     affects every organization following the current Doc's recommendation, not only this one.
2. **Design and implement `evaluation/population_cases.py`.** Reuses
   `labeled_pairs.generate_raw_pairs()`'s per-patient variant/hard-negative/special-population
   generation, restructured from "flat list of pairs" into "one candidate pool per query":

   ```python
   @dataclass(frozen=True)
   class PopulationCase:
       query_id: str
       query_patient: Patient
       candidate_ids: List[str]        # this query's full candidate pool
       expected_match_ids: List[str]   # subset of candidate_ids - possibly empty
       rationale: str

   def build_population_cases(
       patients: List[Patient],
       *,
       pool_size: int = 40,            # per the current Doc's own "forty near-misses" framing
       n_fuzzy_variants_per_patient: int = 1,
       seed: int = 0,
   ) -> List[PopulationCase]: ...
   ```

   For each query patient: the **known-match cluster** is its `mutations.py`/
   `normalization_edge_cases.py`-generated variants (never the query's own literal record —
   mirrors `Patient/$match`'s real shape of "find my other record(s)," not a trivial self-match).
   The **decoy pool** is that query's mined `hard_negatives.py`/`special_populations.py`
   near-misses, topped up with random distractors from the broader sample up to `pool_size`. A
   query with no generated variants (e.g. `n_fuzzy_variants_per_patient=0`) must be able to
   produce an **empty** `expected_match_ids` — the current Doc explicitly calls out "possibly
   empty" as a real case, not an edge case to special-case away.
3. **Write `evaluation/export_population_dataset.py`.** Two-file manifest, following the current
   Doc's own "mostly splitting an existing file rather than generating one from scratch" framing:
   - `evaluation/cases/population_candidates.jsonl` — flat pool, one row per candidate:
     `{"id": ..., "patient": {FHIR Patient JSON}}`.
   - `evaluation/cases/population_queries.jsonl` — one row per query:
     `{"query_id": ..., "query": {FHIR Patient JSON}, "candidate_ids": [...], "expected_match_ids": [...], "rationale": ...}`.

   Splitting candidates from queries avoids redundantly repeating full FHIR blobs across every
   query whose pool happens to share a decoy.
4. **Update `evaluation/cases/README.md`:**
   - New section explaining the two tiers side by side (per-provision pairs vs. population-query)
     and when to use which.
   - State plainly, per the current Doc: **recall and FPR are valid on the curated per-provision
     suite; precision, FDR, F1, and accuracy are only valid on the population tier** — replacing
     the current "use the `frequency` field to reweight" guidance rather than layering on top of
     it, since the current Doc supersedes that approach (delta 3).
   - Add **false discovery rate** (`FDR = FP / (FP + TP)`) to the Option A sample code — named
     explicitly in the current Doc alongside precision/recall/FPR, absent from today's sample.
   - Add both Doc links, marking the draft as superseded-but-retained-for-traceability (existing
     `SYNTHETIC_DATA_COMPARISON.md`/session docs cite specific draft line items by content, which
     would otherwise dangle).
5. **Update `evaluation/SYNTHETIC_DATA_COMPARISON.md`:** add a "What changed between the draft and
   the finalized proposal" section recording deltas 1-5 above (this repo's established pattern for
   this kind of comparison document), and a coverage-table row for the population-query tier.
6. **Update `evaluation/prevalence_estimates.py` and `export_test_dataset.py` docstrings** —
   cross-reference the new tier split from Task 4 so `frequency`'s scope doesn't silently drift
   back to "the" fix for representativeness. Add one sentence to `cases/README.md`'s top matter
   disclosing this file's synthesis method end-to-end (ONC public dataset → programmatic
   single-edit mutation/mining, zero de-identification step because no real PHI is ever in the
   pipeline) — satisfies the current Doc's per-segment method-disclosure requirement at the only
   cost it has today (a documentation sentence, not a schema change), since this repo has exactly
   one segment and it never touched real data.
7. **No code for this task** — record in Open Questions (below) that the aggregate-statistics
   contribution path is now open, so the client-type field-availability backlog item
   `SYNTHETIC_DATA_COMPARISON.md` deferred after session 9 isn't stale-by-omission.
8. **Housekeeping:** move `session_10.md` to `completed/`; add one line to `session_9.md`'s Open
   Questions marking the ONC-duplication question resolved by this session.

## Unit tests required

File: `evaluation/test_population_cases.py` (new, `importorskip("numpy")` per
`test_labeled_pairs.py`'s convention if it imports anything from `rule_eval`).

- Every `expected_match_ids` is a subset of `candidate_ids`.
- A query with `n_fuzzy_variants_per_patient >= 1` produces a non-empty `expected_match_ids`.
- A query with no generated variants produces an **empty** `expected_match_ids` without erroring
  or falling back to some non-empty default — the "possibly empty" case from the current Doc must
  actually be reachable, not just documented.
- Hard-negative/special-population decoys never appear in `expected_match_ids` even though they
  were selected *because* they're near-misses — the whole point of the tier.
- `candidate_ids` length is capped at `pool_size` and is deterministic given a fixed `seed`.
- No accidental collision between a decoy id and a true-match id for the same query.

File: `evaluation/test_export_population_dataset.py` (new).

- Round-trip: write both files, read them back, confirm every `candidate_ids`/`expected_match_ids`
  entry in `population_queries.jsonl` resolves to a row in `population_candidates.jsonl` (no
  orphan references).

## Validation (definition of "resolved")

- [x] `evaluation/onc_loader.py`'s docstring and `SYNTHETIC_DATA_SETUP.md` record the verified
      EnterpriseID-uniqueness finding (Task 1).
- [x] `evaluation/population_cases.py` and `evaluation/export_population_dataset.py` exist, import
      cleanly, and their tests (above) pass via `uv run pytest evaluation/test_population_cases.py
      evaluation/test_export_population_dataset.py -v` (13 passed).
- [x] `PYTHONPATH=. python evaluation/export_population_dataset.py` runs against real ONC fixture
      data and produces both non-empty output files with cross-referencing IDs, on the same
      one-shard/`SAMPLE_SIZE`-limited default as the existing scripts (per
      `SYNTHETIC_DATA_SETUP.md`'s "Memory & scale" guidance — no new scale risk introduced).
      Confirmed: 2,000 queries, 8,016 candidates from `SAMPLE_SIZE=2000` on one shard, seed 0.
- [x] `evaluation/cases/README.md` states the recall/FPR-vs-precision/FDR/F1/accuracy tier split
      explicitly and includes FDR in its sample code (both the pairwise Option A sample and the
      new Option C population-tier sample).
- [x] `evaluation/SYNTHETIC_DATA_COMPARISON.md` records deltas 1-5 and cites both Doc versions.
- [x] `session_10.md` is in `completed/`; `session_9.md`'s open question is marked resolved.
- [x] `ruff check` and `mypy` are clean on all new/changed files under `evaluation/`, modulo the
      pre-existing `FURB192`/`UP006`/`UP035` style debt this repo's existing modules already carry
      (confirmed those same warnings pre-exist on `labeled_pairs.py`/`export_test_dataset.py` —
      not introduced by this session, not fixed here to avoid an unrelated repo-wide lint sweep).
- [x] `uv run pytest .` is green from the repo root (232 passed).

## Open questions

- **NEEDS HUMAN DECISION — maintainer (raise with the workgroup):** the current Doc's justification
  for adopting ONC assumes duplicate-bearing records grouped by `EnterpriseID`; this repo's
  vendored files have zero such duplicates (verified, Task 1). Is this a mismatched/incomplete
  download on this organization's side, or does the workgroup's actual intended ONC release differ
  from what's vendored here? Recommended default (already reflected in this session's scope):
  don't block on resolving this — this repo's self-generated variants substitute for found
  duplicates just fine — but flag it to the workgroup since every other org following the current
  Doc's Option-A recommendation will hit the same gap if they pull the same release.
- **NEEDS HUMAN DECISION — workgroup, via the maintainer:** has the workgroup actually decided to
  build the population tier now, or is this session getting ahead of the current Doc's own open
  decision #2 ("pairs are closer to done; populations are what make this a real benchmark")?
  Recommended default: build it anyway — most of the hard synthesis logic already exists (this is
  assembly work over `generate_raw_pairs()`, not new generation), and it's also the fix for the
  metrics-validity gap (delta 3), which is a correctness problem independent of sequencing
  preference.
- **NEEDS HUMAN DECISION — workgroup, via the maintainer (for session 8, not this session):** did
  the adapter/harness contract get dropped or just not restated when the Doc was finalized?
  Session 8 should confirm before building against the draft's specific JSON/CLI shape.
- **NEEDS HUMAN DECISION — maintainer / whoever owns this organization's workgroup contribution:**
  does this organization want to exercise the newly-opened aggregate-statistics contribution path
  (client-type field-availability rates), the exact idea `SYNTHETIC_DATA_COMPARISON.md` deferred
  pending review after session 9? No code work either way in this session — just don't let the backlog item go
  stale now that a path for it formally exists.

## Execution notes

Executed 2026-08-31, same session as authoring. All eight tasks completed:

1. Verified EnterpriseID uniqueness directly against `evaluation/fixtures/onc/*.csv` (Python
   `csv.DictReader` count across all nine shards) — confirmed 1,000,000 unique ids, zero
   duplicates. Documented in `onc_loader.py`, `SYNTHETIC_DATA_SETUP.md`,
   `SYNTHETIC_DATA_COMPARISON.md`, and `session_9.md`'s open question.
2. Built `evaluation/population_cases.py` (`build_population_dataset()`, `PopulationCase`,
   `PopulationDataset`), reusing `mutations.py`/`normalization_edge_cases.py`/`hard_negatives.py`/
   `special_populations.py` directly. Deliberate design departure from the original sketch: rather
   than grouping `labeled_pairs.generate_raw_pairs()`'s flat RawPair stream by query id (which
   would silently drop any patient never selected as a mining "query"), this iterates over every
   input patient directly, guaranteeing full coverage and making the empty-`expected_match_ids`
   case actually reachable and testable. Institutional-negative candidates are namespaced
   (`<id>::institutional::<type>`) rather than keyed by the underlying real record's bare id, since
   `construct_institutional_negatives()` overwrites only the address on a deep copy that keeps the
   original `EnterpriseID` — using the bare id would have silently collided two different bodies
   (real vs. fabricated-address) under one candidate registry key.
3. Built `evaluation/export_population_dataset.py` (two-file JSONL writer). Smoke-tested against
   real ONC fixture data: 2,000 queries / 8,016 candidates from `SAMPLE_SIZE=2000` on one shard.
   Both output files committed as concrete sample artifacts, matching
   `sample_labeled_pairs.jsonl`'s existing precedent.
4. `evaluation/cases/README.md`: added "Two test tiers," the population-tier file format, the
   metrics-validity split, FDR in both the pairwise and new population-tier sample code, an Option
   C computing precision/FDR/F1/accuracy over the population tier, and the provenance-disclosure
   paragraph.
5. `evaluation/SYNTHETIC_DATA_COMPARISON.md`: added "What changed between the draft and the
   finalized proposal" (deltas 1-5), resolved the session_9-era open ONC-duplication question
   inline, added the population-tier coverage-table row, and updated the client-type
   field-availability deferral note.
6. `prevalence_estimates.py`/`export_test_dataset.py`: added scope cross-references to the new
   tier split; no functional change.
7. No code — flagged only, per scope (`SYNTHETIC_DATA_COMPARISON.md`'s updated deferral note).
8. `session_10.md` moved to `completed/` with an honest status note (no PR/reviewer info exists in
   this repo's own git history — the original PR happened pre-split, in the originating repo).

Verification: `uv run pytest .` — 232 passed. `ruff check` clean on all new/changed files modulo
pre-existing `FURB192`/`UP006`/`UP035` debt already present in `labeled_pairs.py`/
`export_test_dataset.py` (confirmed, not introduced here). `uv run --with mypy mypy
evaluation/population_cases.py evaluation/export_population_dataset.py` — zero errors (the two
errors surfaced when run were pre-existing `rule_eval.py` issues, matching session_9's own note
about that file).

**Not done — genuinely open, carried to whoever picks this up next (see Open Questions):** this
session did not seek out or receive the workgroup's actual answer to any of the four
`NEEDS HUMAN DECISION` items below. All four recommended defaults were applied without waiting,
per this session's own stated rationale for each.
