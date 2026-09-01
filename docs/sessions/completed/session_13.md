# Session 13 — Remove the patient_matching Dependency: This Repo Only Produces Test Data

**Status:** completed (executed 2026-09-01, same session as authoring — no PR/reviewer yet;
see Execution notes)
**Thread:** Evaluation & Statistical Rigor Framework
**Estimated size:** L — deletes several modules spanning multiple prior sessions' work, rewires
the generation pipeline's normalization step, and touches most of this repo's documentation.

## Outcome purpose

Opening PR #3 (session 12's population-tier work) surfaced a real CI blocker: this repo's
`pyproject.toml` depends on `patient_matching @ git+https://github.com/icanbwell/patient-matching.git`,
a **private** repo. GitHub Actions' default `GITHUB_TOKEN` has zero cross-repo read access to it
(confirmed via `patient_matching`'s own `actions/permissions/access` API: `access_level: "none"`),
so `uv sync` fails in CI with "remote: Repository not found" — not a credentials problem, a
permissions one, and fixing it properly would mean either changing `patient_matching`'s own
cross-repo access settings or provisioning a PAT secret — both org-level decisions, not something
to make unilaterally while fixing a CI pipeline for a different repo.

Asked directly, the repo maintainer's answer was simpler than any workaround: **remove the
dependency**. This repo's actual deliverable, per `evaluation/DESIGN.md`'s and
`evaluation/cases/README.md`'s own Design Principle 1, has always been supposed to be
algorithm-agnostic test data — "every test case is a pair of standard FHIR Patient resources plus
an expected outcome... nothing about the format assumes any particular matching implementation."
Depending on `patient_matching` at all was in tension with that principle from the start; this
session resolves the tension instead of working around the CI symptom.

**Explicit scope confirmed with the maintainer before starting:** full removal, not just making
the dependency optional. Delete everything that exercises the live matching engine
(`onc_baseline.py`, the `NormalizationManager` call inside generation, `fhir_match_data_source.py`,
`cms_matching_demo.ipynb`, `cases/README.md`'s "Option B"), not just decouple it from CI.

## Upstream sessions (must be completed first)

- **Session 12** (`completed/`) — this session's CI failure was discovered while getting session
  12's PR green; this session's changes land on top of it in the same PR.

## Downstream sessions (affected by this one)

- **Session 8** (`pending/`) — its entire premise (compare the legacy and new engines
  in-process, in this repo) depended on exactly the capability this session removes. Flagged as
  needing re-scoping in its own doc; not resolved here.
- **Session 11** (`pending/`) — its data-fabrication piece is likely unaffected, but its planned
  wiring into `build_labeled_pairs()` (deleted) and a regression guard inside
  `patient_matching`'s own test suite both assumed the removed dependency. Flagged as needing
  re-scoping in its own doc; not resolved here.

## Upstream data/system dependencies

None. Same static ONC fixture CSVs as every prior session.

## Downstream data/system dependencies

None new. If anything, one fewer: this repo no longer has a runtime dependency on any other
repo, private or public.

## Scope

### In scope

1. **`pyproject.toml`** — remove the `patient_matching` git dependency. Add `nicknames` as a
   direct dependency (it was only being supplied transitively through `patient_matching` before;
   `mutations.py` imports it directly and would otherwise break). `rapidfuzz` was checked and
   found to be cited only in a docstring, never actually imported — no action needed there.
2. **`.github/workflows/build_and_test.yml`** — remove the `git config
   url.insteadOf`/`GITHUB_TOKEN` step added to work around the private-repo clone (session 12's
   PR discussion) — no longer needed once nothing requires cloning a private repo.
3. **Delete the modules that exist specifically to exercise the live matching engine:**
   `evaluation/onc_baseline.py` + `evaluation/test_onc_baseline.py` (session 3's self-match
   baseline harness), `notebooks/fhir_match_data_source.py` + its test (session 4's real-FHIR-data
   query/scoring notebook), `notebooks/cms_matching_demo.ipynb` (a literal demo of
   `MatchingManager`/`MatchingEngine`), and `notebooks/_sql_safety.py` + its test (orphaned once
   `fhir_match_data_source.py`, their only consumer, is gone).
4. **`evaluation/labeled_pairs.py`** — remove `build_labeled_pairs()` (built `PatientFields` for
   `MatchingEngine.evaluate_pair()` to consume — no longer has a caller once nothing in this repo
   runs that engine) and the `NormalizationManager` call inside `generate_raw_pairs()`.
   `generate_raw_pairs()` itself, `RawPair`, and every mutation/mining/construction module it
   composes are unchanged in shape - they never needed the engine, only the normalization step
   did, and dropping it just means generated FHIR JSON now carries whatever case/punctuation the
   raw ONC CSVs used.
5. **`evaluation/population_cases.py`** — same normalization removal, same rationale.
6. **Doc updates** — `cases/README.md` (drop "Option B," renumber, add a case/punctuation
   provenance note), `SYNTHETIC_DATA_SETUP.md` (setup instructions, "Materializing a portable
   test-case file," "Memory & scale" — all referenced now-deleted functions/modules),
   `SYNTHETIC_DATA_COMPARISON.md` (a "Reading this document today" addendum — the historical
   narrative about what session 9/10 built stays as accurate history, not rewritten), root
   `README.md` (Contents/Setup sections), `onc_loader.py`/`normalization_edge_cases.py`/
   `test_mutations.py`/`test_rule_eval.py`/`test_prevalence_estimates.py` docstrings.
7. **Flag, don't resolve, the two affected pending sessions** (8 and 11) — see "Downstream
   sessions" above.

### Out of scope

- **Re-scoping session 8 or session 11.** Flagged in their own docs; whoever picks them up next
  decides, not this session.
- **Choosing where engine-comparison work (session 8's old premise) should live instead**, if the
  workgroup still wants it. Not this session's call.
- **Anything about the population-query tier's own design** (session 12's territory) beyond the
  mechanical normalization-call removal needed here.

## Tasks

1. Removed `patient_matching` from `pyproject.toml`; added `nicknames` directly. Verified via a
   fresh `rm -rf .venv uv.lock && uv sync` that installation no longer touches any private repo.
2. Removed the private-repo git-credential step from `.github/workflows/build_and_test.yml`.
3. Deleted `onc_baseline.py`, `test_onc_baseline.py`, `fhir_match_data_source.py`,
   `test_fhir_match_data_source.py`, `cms_matching_demo.ipynb`, `_sql_safety.py`,
   `test__sql_safety.py` (verified via grep that nothing else in the repo imports `_sql_safety`
   before deleting it).
4. Rewrote `labeled_pairs.py`: removed `build_labeled_pairs()`, the `FieldExtractor`/
   `NormalizationManager`/`rule_eval.LabeledPair` imports, and the normalization call inside
   `generate_raw_pairs()`. Rewrote its `__main__` smoke-run block to call `generate_raw_pairs()`
   directly instead.
5. Rewrote `population_cases.py`'s `build_population_dataset()`: removed the
   `NormalizationManager` import and call, using `patients` directly everywhere `normalized` used
   to appear.
6. Rewrote `test_labeled_pairs.py` (previously tested only `build_labeled_pairs()`, now deleted)
   to test `generate_raw_pairs()` directly — mechanical, since `RawPair` already carries the same
   `pair_id`/`is_true_match`/`strata` fields `LabeledPair` did.
7. Removed now-stale `pytest.importorskip("numpy")` guards from `test_labeled_pairs.py`,
   `test_export_test_dataset.py`, and `test_prevalence_estimates.py` — none of them touch numpy
   anymore now that `labeled_pairs.py` doesn't import `rule_eval`.
8. Updated documentation per Scope item 6 above, including fixing several already-stale
   `docs/sessions/pending/session_12.md` path references (session 12's doc had already moved to
   `completed/` by the time this session started).
9. Added status warnings to `session_8.md` and `session_11.md` per "Downstream sessions."

## Unit tests required

No new test files — this session is a removal. Existing test files updated in place (Task 6-7
above); every other existing test file needed zero changes, since the generation logic itself
(`mutations.py`/`hard_negatives.py`/`special_populations.py`/`normalization_edge_cases.py`) never
imported `patient_matching` and is already robust to un-normalized (mixed-case) input — every
case-sensitive comparison in that code already normalizes to a common case locally (e.g.
`_primary_family_name(patient).upper()`) rather than assuming its input already was.

## Validation (definition of "resolved")

- [x] `rm -rf .venv uv.lock && uv sync` succeeds with no cross-repo access of any kind.
- [x] `uv run pytest .` — 201 passed (232 before this session, minus 31 tests belonging to the
      seven deleted files).
- [x] `make lint` — clean.
- [x] `make typecheck` — clean (`evaluation` only now; `notebooks/` has no `.py` files left, so
      the Makefile's `notebooks` mypy invocation and its now-inapplicable dual-import-identity
      comment were removed too).
- [x] `make run-pre-commit` — clean.
- [x] `PYTHONPATH=. uv run python evaluation/export_test_dataset.py` and
      `evaluation/export_population_dataset.py` both regenerate their sample files successfully
      against real ONC fixture data. Spot-checked the output: field values now carry raw ONC case
      ("AABERG", "KATHERINE", `347-984-6839`) instead of the previously-normalized form
      ("aaberg", "katherine", `+13479846839`) - confirms the normalization removal is real, not
      just absent from the code path that happened to run.
- [x] `grep -r patient_matching` across the repo (excluding `.venv`) returns only the
      `icanbwell/patient-matching` GitHub URL in `README.md` (historical provenance, not a
      dependency) and citation-only mentions in docstrings/historical session docs - no code
      imports it.

## Open questions

- **For whoever revisits session 8:** does engine-comparison work belong in a different repo (one
  that can depend on both the legacy and new matching engines), or does the workgroup no longer
  need it given the algorithm-agnostic direction the rest of this repo has taken? Not resolved
  here - flagged in `session_8.md`.
- **For whoever revisits session 11:** same question, narrower - does its planned
  `patient_matching`-side regression guard move elsewhere, or get dropped? The data-fabrication
  half of that session is likely unaffected and can probably proceed once session 6 unblocks it.

## Execution notes

Executed 2026-09-01, prompted directly by PR #3's CI failure (see Outcome purpose). Verified the
full blast radius by grep before touching anything: exactly three files had real
`patient_matching` imports needing code changes (`labeled_pairs.py`, `population_cases.py`, plus
the seven files deleted outright); everything else was docstring/comment prose, fixed for
accuracy but not functionally coupled. Confirmed `nicknames` was the only actual missing direct
dependency (`rapidfuzz` was cited but never imported) before editing `pyproject.toml`. Ran the
full verification sequence (Validation checklist above) before considering this done, including
regenerating both committed sample datasets and spot-checking their content changed as expected
(raw case, not normalized) rather than just trusting that the code "should" behave differently.
