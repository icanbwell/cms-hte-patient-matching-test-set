## Repo-Specific: cms-hte-patient-matching-test-set

<!-- Migrated from this repo CLAUDE.md by the EA instruction sync. -->


This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

This repo produces a portable, algorithm-agnostic **test dataset** for validating patient-matching
algorithms against the CMS HTE Patient Matching Specification. It was split out of a private
reference matching implementation and, as of session 13, has **no runtime dependency on that or
any matching engine** — it only generates and exports test data. Everything in `evaluation/`
produces FHIR `Patient` JSON and JSON Lines manifests; nothing here scores a matching algorithm
itself.

Read `evaluation/DESIGN.md` and `evaluation/SYNTHETIC_DATA_SETUP.md` first for the full picture;
`evaluation/cases/README.md` explains how a consumer (any org, any language) uses the generated
files.

## Commands

```
uv sync              # setup (make setup)
make tests            # uv run pytest . — this is CI's actual gate (build_and_test.yml)
make lint             # uv run ruff check .
make typecheck        # uv run mypy evaluation (notebooks/ has no .py files left)
make run-pre-commit   # ruff check --fix + ruff format, whole repo
uv run pre-commit install   # one-time: get the above as a real git hook
```

Run a single test file or test:
```
uv run pytest evaluation/test_mutations.py -v
uv run pytest evaluation/test_mutations.py::test_some_case -v
```

Run the generation/export scripts directly (all default to one ONC shard, sampled down — see
"Memory & scale" below before changing that):
```
PYTHONPATH=. uv run python evaluation/labeled_pairs.py             # demo: prints pair counts
PYTHONPATH=. uv run python evaluation/export_test_dataset.py        # writes evaluation/cases/sample_labeled_pairs.jsonl
PYTHONPATH=. uv run python evaluation/export_population_dataset.py  # writes population_{candidates,queries}.jsonl
SAMPLE_SIZE=20000 PYTHONPATH=. uv run python evaluation/labeled_pairs.py   # override sample size
```

Generate from the full 9-shard ONC dataset (~1,000,000 records), one shard at a time rather than
concatenating all 9 into one in-memory list — see "Memory & scale" below:
```
make generate-full-dataset   # PYTHONPATH=. uv run python evaluation/export_full_onc_dataset.py
# writes evaluation/cases/full_labeled_pairs.jsonl, full_population_candidates.jsonl,
# full_population_queries.jsonl — deliberately not the same filenames as the sample_/population_
# files above, since those are the committed, curated sample consumers already depend on.
```

Lint/typecheck just the files you're touching:
```
uv run ruff check evaluation/mutations.py evaluation/hard_negatives.py
uv run mypy evaluation/mutations.py evaluation/hard_negatives.py
```

## Architecture

### Generation pipeline (`evaluation/`)

All test data derives from the public ONC 2017 Patient Matching Algorithm Challenge dataset
(`evaluation/fixtures/onc/*.csv`, ~1M rows across 9 alphabetically-sharded files) via this repo's
own mutation/mining/construction code — no real member-organization data, no de-identification
step (ONC's data is already public/synthetic).

- **`onc_loader.py`** — loads ONC CSV shards into FHIR `Patient` dicts. No streaming; loading all
  9 shards materializes all ~1M records in memory at once. **Every EnterpriseID in this
  vendored copy is unique, but the same person can appear under more than one ID (shared name+DOB,
  and in some cases SSN).** Never treat "different ID" as "different person": every negative miner
  and the population distractor top-up exclude pairs for which
  `identity_guard.is_possible_same_person` is true. True-match clusters are built by this repo's own
  generators.
- **`mutations.py`** — single-character-edit ("fuzzy-eligible") variants of a record: exactly one
  edit per call, composed as `(original, variant, is_true_match=True)`.
- **`hard_negatives.py`** — mines *genuinely distinct* real ONC records that coincidentally collide
  on high-signal fields (shared ZIP+DOB). Deliberately not mutation-based — mutating a record and
  calling it "a different person" would only test a matcher's own fuzzy tolerance, not reality.
- **`normalization_edge_cases.py`** — diacritic-folded / punctuation-varied name variants that CMS
  spec §V.A requires normalization to fold into an exact match (distinct from `mutations.py`'s
  fuzzy-tolerance variants).
- **`special_populations.py`** — high-risk non-match categories (shelters, nursing facilities,
  correctional institutions, multi-generational households, etc.). Some are mined (real coincidental
  collisions); institutional categories are constructed by overwriting only the address on two
  already-distinct real identities with a fabricated, clearly-synthetic address
  (`"SYNTHETIC TEST ADDRESS"`, reserved `000xx` ZIP block) — the underlying identities are never
  fabricated.
- **`scenarios.py` / `drift_profile.py` / `drift_mutations.py` / `placeholders.py`** — the
  per-patient true-match scenario registry shared by both tiers (session-14 scenarios plus surname
  change, address move, phone/email churn, placeholder values, optional gender drift), its
  placeholder emission rates, the donor-backed mutators, and the placeholder catalog (also the
  pairwise-only placeholder-collision non-matches). `audit.py` / `release_gate.py` gate the result.
- **`population_targets.py` / `population_sampling.py` / `household_assignment.py` / `export_realistic_dataset.py`** —
  cited age-band and household targets, the age-stratified sampler (all ONC shards, one at a time),
  household assignment with shared addresses and contacts, and the generator for the parallel
  `realistic_*` files (the committed curated files are never overwritten; the realistic files are
  committed as the v1 release candidate and `make audit-realistic` runs in CI).
  `make generate-realistic-dataset` / `make audit-realistic`.
- **`prevalence_estimates.py`** — real, cited public-source prevalence estimates (Census/CDC/Pew/
  peer-reviewed) per test-case category, for optional real-world-weighted aggregation. Every entry
  is either a cited estimate or an explicit `has_public_estimate=False` placeholder — never a
  guessed number.
- **`near_miss.py`** — streaming reverse-blocking finder: real look-alike decoys for sampled queries
  across all shards; feeds both tiers (`hard_negative`, `name_collision_negative`,
  `sibling_negative`, `near_miss_negative`). **`negative_balance.py`** rebalances the pairwise tier
  toward 50% negatives.
- **`labeled_pairs.py`** — assembles all of the above into per-provision `(source, target,
  is_true_match)` triples; the shared generation core everything else builds on.
- **`population_cases.py`** — regroups the same generation logic into the second test kind: one
  query patient against a candidate pool (default 40), with a possibly-empty
  `expected_match_ids` set. Reuses `labeled_pairs.py`'s generation rather than duplicating it.
- **`export_test_dataset.py`** / **`export_population_dataset.py`** — materialize the above as the
  portable JSON Lines manifests under `evaluation/cases/`.
- **`rule_eval.py`** — a separate, rule-agnostic statistical harness (Bayesian before/after
  comparison, stratified splitting, SHIP/REJECT/NEEDS-MORE-DATA verdicts) for anyone comparing two
  matching rules against a labeled gold set. Demoed in `notebooks/rule_eval_demo.ipynb`.

Every generator function is exercised by a same-named `test_*.py` file in `evaluation/`.

### The two output tiers (`evaluation/cases/`)

| Tier | Files | Answers | Valid metrics |
|---|---|---|---|
| **Per-provision pairs** | `sample_labeled_pairs.jsonl` | "Does this algorithm correctly implement this specific spec provision?" Deliberately over-samples rare/high-risk categories for statistical power — not representative by design. | Recall, FPR only |
| **Population query** | `population_queries.jsonl` + `population_candidates.jsonl` | "When this algorithm searches a realistic population, does it return the right people?" Naturally representative (real duplicate cluster + mostly-random distractors). | Precision, recall, FPR, FDR, F1, accuracy |

**Never compute precision/FDR/F1/accuracy over the per-provision tier** — its should-match ratio is
a generation-parameter artifact, not a real base rate. Use the population tier for those. See
`evaluation/cases/README.md`'s "Frequency and real-world representativeness" for the full rationale,
and its "Option A"/"Option B" sections for runnable scoring snippets any language/algorithm can
follow against these files.

### Memory & scale — read before raising `SAMPLE_SIZE`/`POOL_SIZE` or passing multiple shards

Loading the full ONC dataset and transforming it has crashed a cluster before. `onc_loader.py` has
no streaming (one Python list of ~1M dicts if given all 9 shards), and `generate_raw_pairs()` /
`mine_shared_address_hard_negatives()` assume a fully-materialized in-memory list — they add their
own overhead on top of whatever step 1 already allocated. All `__main__` scripts default to **one
shard, sampled down** for exactly this reason. If you need full-dataset scale, express it as a
distributed job (Spark), not a single-process Python list — see `SYNTHETIC_DATA_SETUP.md`'s
"Memory & scale" section for the full guidance.

## Conventions

- `from __future__ import annotations` at the top of every module; `typing.Dict`/`List`/`Set` over
  builtin generics is the established codebase-wide convention (ruff's `UP006`/`UP035`/`FURB192`
  are deliberately ignored in `pyproject.toml` rather than rewriting every existing file).
- Field values are copied through from the ONC CSVs as-is — this repo's generation pipeline does
  **not** normalize case/punctuation (that step was intentionally dropped in session 13 along with
  the removed matching-engine dependency). Any consumer must apply its own normalization before comparing.
  One exception: the `realistic_*` files move every birth date forward 9 years (`dob_shift.py`, BAI-1161)
  so ages are current; the curated files keep ONC's birth dates.
- Every generated case's `rationale` field traces to a specific category/provenance — never a
  black box (Design Principle 2 in `DESIGN.md`/the workgroup Doc).
- `docs/sessions/` narrates the design history chronologically (`completed/` and `pending/`) —
  check there before assuming something is unimplemented; `session_13.md` in particular explains
  the removed matching-engine dependency and how that shapes the current scope.
