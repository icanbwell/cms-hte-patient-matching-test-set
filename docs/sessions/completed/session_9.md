# Session 9 — Synthetic CMS Test-Dataset Generation: Fuzzy Mutations + Hard-Negative Mining

**Status:** completed (PR #27 merged 2026-08-14 — reviewed by Kenan Spruill)
**Thread:** Evaluation & Statistical Rigor Framework
**Estimated size:** M — two new small modules (mutation generators, hard-negative miner), one
assembly module wiring them into `rule_eval.LabeledPair`, and a comparison write-up.

> This session doc originated in the patient-matching repo. Read [conventions.md](https://github.com/icanbwell/patient-matching/blob/main/docs/sessions/conventions.md) there first (this repo does not carry its own copy).

## Outcome purpose

**Scope-anchor note:** `conventions.md` names two canonical sources for a session's scope
anchor — the handoff doc's Line A/Line B strategy, or the CMS spec itself. This session's actual
anchor is a third source `conventions.md` doesn't yet name: the cross-org workgroup Google Doc,
["Proposal: A Shared Test Dataset for CMS v3.3.0 Patient Matching
Compliance"](https://docs.google.com/document/d/1N6IQkaLkKPdQKVxPSWZYDaLbTCx0EYEgwBcCCPk-6pk),
plus Imran Qureshi's direct Slack ask (2026-08-14, b.well/CMS working-group DM): *"remember the
goal is to have a test dataset and a methodology that anyone can use to verify if their
algorithm complies with the CMS HTE patient matching requirements."* Flagging this explicitly
rather than silently stretching the existing rule — `conventions.md` may want a third canonical
source added if this kind of cross-org-deliverable session recurs.

`session_8.md`'s 2026-08-13 design update records Sean's Slack conversation with Imran about a
labeled test set (`Outside Record` / `Internal Record` / `IsMatch [0,1]`) and states: *"the
test-data simulation methodology itself is still open ... check for the outcome of that
conversation before starting Task 3/4."* That conversation happened 2026-08-14 (one day later
than session_8.md anticipated). This session is the resolution: it supplies the simulation
methodology session_8 was waiting on, as its own upstream session rather than folded into
session_8's already-large scope (cross-repo legacy comparison, adjudication workflow,
disagreement bucketing).

The methodology itself (per 2026-08-14 design discussion): true-match rows come from
single-edit-distance mutations of a real record (matches the CMS spec's own literal fuzzy-
tolerance definition); true-non-match rows come from **mining real, distinct-record pairs that
happen to collide on several fields** — not from asserting that a mutation is "a different
person," which would only test the algorithm's own tolerance, not reality (this distinction was
raised directly by Sean during design).

See `evaluation/SYNTHETIC_DATA_COMPARISON.md` (this session's other main deliverable) for the
full accounting against the Doc and Slack thread, including what was migrated from two prior,
never-merged prototypes, what was deliberately left behind and why, and known coverage gaps.

## Upstream sessions (must be completed first)

- **Session 3** (ONC baseline, `completed/`) — reuses `evaluation/onc_loader.py` and
  `evaluation/rule_eval.py`'s `LabeledPair` shape directly, same as `onc_baseline.py`.

## Downstream sessions (unblocked by this one)

- **Session 8** — its 2026-08-13 design update is waiting on this session's resolution of the
  test-data simulation methodology. Session 8 should update its own doc once this session
  reaches `completed/`, to say explicitly whether it consumes `evaluation/labeled_pairs.py`'s
  output directly or extends it further (this session does not decide that for session 8 — see
  "Out of scope").

## Upstream data/system dependencies

None. All inputs are static, already-committed data: `evaluation/fixtures/onc/*.csv` (session 3).

## Downstream data/system dependencies

None. `evaluation/labeled_pairs.py`'s output (`LabeledPair` objects) is in-memory only, not
persisted to this repo or any external system — same pattern as `onc_baseline.py`.

## Scope

### In scope

1. **`evaluation/mutations.py`** — DOB mutations (`mutate_dob`: day/month/year/swap/typo,
   ported from `data_science_rapid_prototyping`'s `RecordModifier.modify_birthdate`) and name
   mutations (`typo_edit`, `transpose_characters`, `drop_letters`, `abbreviate`,
   `substitute_nickname`, ported from `helix.personmatching`'s unmerged `embed-proto` branch's
   `NameModifier` hierarchy), rewritten as plain functions operating on `onc_loader.py`'s FHIR
   Patient dict shape. `generate_fuzzy_variant()` composes these into a single named or random
   mutation, returning `(mutated_patient, mutation_type_applied)`.
2. **`evaluation/hard_negatives.py`** — `mine_shared_address_hard_negatives()`: blocks ONC
   patients by `(postalCode, birthDate)` and emits pairs of distinct-ID, distinct-family-name
   records within each block as hard-negative candidates. New code (neither prior prototype
   mined real-record pairs — both only mutated-then-embedded).
3. **`evaluation/labeled_pairs.py`** — `build_labeled_pairs()`: assembles `mutations.py` (true
   matches) and `hard_negatives.py` (true non-matches) into `rule_eval.LabeledPair`s, following
   `onc_baseline.py`'s established normalize-then-extract pattern. Includes a `__main__` block
   for a standalone smoke run (`PYTHONPATH=. python evaluation/labeled_pairs.py`), matching
   `onc_baseline.py`'s convention.
4. **`evaluation/SYNTHETIC_DATA_COMPARISON.md`** — the deliverable write-up comparing this
   migration against the Google Doc and Slack thread, including the flagged-but-unresolved claim
   about the ONC dataset's duplicate-identity risk (Doc §4) and the explicitly-deferred
   client-type field-availability and Person-Patient-link-mining ideas.
5. **`evaluation/SYNTHETIC_DATA_SETUP.md`** — setup/execution walkthrough (env setup, running
   tests, running the demo script), plus a "Memory & scale" section addressing a real prior
   failure: loading the full ~1,000,000-record ONC dataset and transforming it at scale has
   crashed a Databricks cluster before (per Sean, 2026-08-14). `labeled_pairs.py`'s `__main__`
   defaults to one sampled-down shard (`DEFAULT_SAMPLE_SIZE`, overridable via `SAMPLE_SIZE`)
   rather than `onc_baseline.py`'s existing all-9-shards pattern, for exactly this reason.

### Out of scope

- Deciding whether session_8's labeled-set approach *replaces* or *runs alongside* its original
  legacy-vs-new engine comparison scope — that's session_8's own open question to resolve, not
  this session's. This session only supplies the methodology session_8 was waiting on.
- Administrative-restriction pairs, twin/shelter/institutional special-population pairs, and
  normalization edge cases (Doc §2) — ONC's available fields don't support most of these
  directly without additional synthetic construction; flagged as gaps in
  `SYNTHETIC_DATA_COMPARISON.md`, not attempted here.
- The ≥1,000,000-record empirical collision-rate validation (Doc §4) — a population-level
  statistical exercise, different from labeled-pair testing.
- Client-type field-availability/dropout modeling and mining Person-Patient link outcomes as
  fuzzy-match ground truth — both explicitly deferred per 2026-08-14 design discussion (see
  `SYNTHETIC_DATA_COMPARISON.md`'s "Known gaps" section for why).
- Verifying the Doc §4 claim about ONC's duplicate-identity structure against ONC's own
  published methodology — flagged in `SYNTHETIC_DATA_COMPARISON.md` as worth checking, not
  resolved here.
- Porting `record_keeper.py` (Redis), `embedding/*`, or the CNN-ED training pipeline from either
  prior prototype — none of it applies to this repo's rule-based matcher (see
  `SYNTHETIC_DATA_COMPARISON.md`'s "What this PR deliberately leaves behind").

## Tasks

1. Port DOB and name mutation logic into `evaluation/mutations.py`, adapted to the FHIR Patient
   dict shape and with the embedding-specific `TargetStrategy` machinery dropped.
2. Write `evaluation/hard_negatives.py`'s shared-ZIP+DOB blocking miner.
3. Write `evaluation/labeled_pairs.py`'s assembly function and `__main__` smoke-run block.
4. Write `evaluation/SYNTHETIC_DATA_COMPARISON.md`.
5. Write `evaluation/SYNTHETIC_DATA_SETUP.md`, and make `labeled_pairs.py`'s `__main__` default
   to a sampled single shard rather than all 9, per the memory/scale risk it documents.
6. Update `session_8.md` to record this session's resolution of its 2026-08-13 open question,
   and this new upstream dependency.

## Unit tests required

Files: `evaluation/test_mutations.py`, `evaluation/test_hard_negatives.py`,
`evaluation/test_labeled_pairs.py` (the last `importorskip("numpy")`, per
`test_onc_baseline.py`'s convention, since it imports `rule_eval`).

Cover decision boundaries per `conventions.md`'s testing-structure section: DOB mutation day
range (±1 to ±3 days, never 0 or >3), month-boundary wraparound (Dec -> Jan), invalid-typo
fallback (keep original date rather than crash), short-name no-ops (`_MIN_MUTATABLE_LENGTH`),
hard-negative exclusion of same-family-name and same-ID pairs, and determinism given a fixed
seed. See the actual test files for the full parametrized case tables.

## Validation (definition of "resolved")

- [x] `evaluation/mutations.py`, `evaluation/hard_negatives.py`, `evaluation/labeled_pairs.py`
      exist and import cleanly.
- [x] `uv run pytest evaluation/test_mutations.py evaluation/test_hard_negatives.py evaluation/test_labeled_pairs.py -v`
      passes (27 passed, 0 failed, run 2026-08-14).
- [x] `PYTHONPATH=. python evaluation/labeled_pairs.py` (and a smaller direct-sample smoke run)
      runs against real ONC fixture data without error and produces a non-empty, mostly-fuzzy-
      variant pair set (hard negatives are expected to be rare on small samples — confirmed 0
      hard negatives on a 300-row single-shard sample, non-zero variants of every registered
      mutation type).
- [x] `ruff check` is clean on all new files; `mypy` reports zero new errors (3 pre-existing
      errors remain in `rule_eval.py`, unrelated to this session — confirmed by running mypy on
      the new files directly).
- [x] `evaluation/SYNTHETIC_DATA_COMPARISON.md` exists and covers: what was migrated from each
      prior prototype, what was left behind and why, the hard-negative-vs-mutation distinction,
      the flagged-but-unresolved ONC duplicate-identity claim, coverage against Doc §2's
      categories, and explicitly deferred ideas.
- [x] `evaluation/SYNTHETIC_DATA_SETUP.md` exists and covers setup, test/demo execution, and the
      memory/scale risk; `labeled_pairs.py`'s `__main__` loads one sampled shard by default, not
      all 9.
- [x] `session_8.md` updated to record this session's resolution (done as part of this PR — see
      that file's changelog).
- [x] PR reviewed and approved (Kenan Spruill, GitHub) and merged 2026-08-14. **Partial:**
      Imran/Adam have not formally reviewed via GitHub — the methodology itself was built
      directly from Sean's 2026-08-14 Slack design discussion with Imran, but neither has signed
      off on the PR specifically. Follow up with them before treating the methodology direction
      as fully confirmed, per the original plan.

## Open questions

- **For session_8, not this session:** does `evaluation/labeled_pairs.py`'s output replace
  session_8's original legacy-vs-new engine comparison scope outright, or run alongside it?
  Session_8.md has been updated to carry this question forward explicitly.
- **Verify, don't assume:** is the Doc §4 claim about ONC containing intentional same-person
  duplicate records under different IDs actually true of this specific dataset copy? Nothing
  found in either repo corroborates or refutes it (see `SYNTHETIC_DATA_COMPARISON.md`). If
  false, `onc_baseline.py`'s existing cross-pair negative sampling (session 3) is unaffected; if
  true, both that code and this session's `hard_negatives.py` need revisiting.
- Whether `patient-matching` remains a permanent home for this module or a staging copy ahead of
  the Doc §8-recommended neutral cross-org repo is explicitly treated as an open question for
  the workgroup, per Sean's design-time answer — not resolved here.

## Execution notes

Executed 2026-08-14 in a single session, alongside reading the source Slack thread and Google
Doc directly (both fetched fresh, not from a committed copy, matching `conventions.md`'s
guidance for the CMS v3.3 spec's own live-draft handling). Code and tests written and verified
locally (`uv run pytest`, `ruff check`, `mypy`, and a real-data smoke run) before opening the PR.
`session_8.md` and `docs/sessions/index.md` updated in the same PR to record this session's
resolution of session_8's 2026-08-13 open question and register session_9 in the index.

**Close-out (2026-08-14):** PR #27 approved by Kenan Spruill and merged into `main` same day.
Doc moved `in_review/` -> `completed/`; `index.md` updated accordingly. Imran/Adam have not yet
formally reviewed the PR itself (see Validation) — the "replace vs. run alongside" open question
for session_8 remains open regardless of that follow-up.
