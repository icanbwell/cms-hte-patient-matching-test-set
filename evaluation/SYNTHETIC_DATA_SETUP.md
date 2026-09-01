# Synthetic CMS test-dataset generation: setup & execution

Walkthrough for running `evaluation/mutations.py`, `evaluation/hard_negatives.py`, and
`evaluation/labeled_pairs.py` (session 9) — the fuzzy-mutation and hard-negative-mining code
this repo uses to build a labeled CMS test dataset. See `SYNTHETIC_DATA_COMPARISON.md` for what
this code does and doesn't cover; this file is just how to run it.

## Setup

1. Standard repo setup first, if you haven't already: `make setup` (or `uv sync` directly) from
   the repo root. `numpy`/`pandas`/`scipy`/`matplotlib` are core dependencies of *this* repo's own
   `pyproject.toml` (not of the upstream `patient_matching` package, which deliberately keeps them
   out — see `evaluation/DESIGN.md`) — `uv sync` installs them, no separate `uv pip install` step
   needed.
2. No other new dependency is required — `nicknames` and `rapidfuzz` (used by
   `mutations.py`) are already core `patient_matching` dependencies (see `pyproject.toml`).

## Running the tests

```
uv run pytest evaluation/test_mutations.py evaluation/test_hard_negatives.py evaluation/test_labeled_pairs.py -v
```

Or the full suite: `make tests` (equivalently, `uv run pytest .` from the repo root) — this is
also CI's actual gate, `.github/workflows/build_and_test.yml`.

Lint/format and type-check the whole repo with `make lint` / `make typecheck`, or both plus the
formatter via `make run-pre-commit` (installed as a real git hook via `uv run pre-commit
install`, and CI's `lint` job). `evaluation/` and `notebooks/` are **not** excluded — the
pre-commit config covers the whole repo. To check just the files you're touching:

```
uv run ruff check evaluation/mutations.py evaluation/hard_negatives.py evaluation/labeled_pairs.py
uv run mypy evaluation/mutations.py evaluation/hard_negatives.py evaluation/labeled_pairs.py
```

## Running the demo script

```
PYTHONPATH=. uv run python evaluation/labeled_pairs.py
```

This loads **one** ONC shard (not all 9), samples it down to `SAMPLE_SIZE` (2000 by default —
see "Memory & scale" below), builds labeled pairs, and prints counts per pair type/mutation.
Override the sample size deliberately: `SAMPLE_SIZE=20000 PYTHONPATH=. uv run python evaluation/labeled_pairs.py`.

To use the pieces individually (e.g. from a notebook or another script):

```python
from mutations import generate_fuzzy_variant
from hard_negatives import mine_shared_address_hard_negatives
from labeled_pairs import build_labeled_pairs

variant, mutation_type = generate_fuzzy_variant(patient)          # one mutated copy
candidates = mine_shared_address_hard_negatives(patients)          # List[HardNegativeCandidate]
pairs = build_labeled_pairs(patients, n_fuzzy_variants_per_patient=1, seed=0)  # List[LabeledPair]
```

## Materializing a portable test-case file

`labeled_pairs.py`'s `LabeledPair` output (above) is in-memory only and holds already-extracted
`PatientFields`, not raw FHIR JSON — it's this repo's own internal representation, meant for
`MatchingEngine.evaluate_pair()`, not something another organization could point their own
matching algorithm at. `export_test_dataset.py` builds the actual portable manifest the
cross-org workgroup Doc's Section 3 describes ("the artifact the workgroup actually shares and
versions, not code") — one JSON Lines row per test case, with a stable `case_id`, `source`/
`target` FHIR Patient JSON, `expected_match`, and a `rationale` string:

```
PYTHONPATH=. uv run python evaluation/export_test_dataset.py
```

Same one-shard, `SAMPLE_SIZE`-limited default as `labeled_pairs.py` (see "Memory & scale"
below), writing to `evaluation/cases/sample_labeled_pairs.jsonl` by default (override with the
`OUTPUT_PATH` env var). A committed copy of this file exists at that path already, generated
from `SAMPLE_SIZE=2000` on one ONC shard with the default seed — regenerate it any time by
re-running the command above; it's fully reproducible given the same inputs. See
**`evaluation/cases/README.md`** for how to actually test a matching algorithm (this repo's own,
or a different organization's entirely) against the file.

To build the manifest programmatically instead of via the file:

```python
from export_test_dataset import build_test_case_records, write_jsonl

records = build_test_case_records(patients, seed=0)   # List[LabeledCaseRecord]
write_jsonl(records, Path("my_output.jsonl"))
```

`labeled_pairs.build_labeled_pairs()` and `export_test_dataset.build_test_case_records()` both
build from the same underlying generator, `labeled_pairs.generate_raw_pairs()` — the mutation/
mining/construction logic itself is written exactly once; only what's kept from each generated
pair (extracted `PatientFields` vs. raw FHIR JSON) differs between the two callers.

## Population-query tier (session 12)

`evaluation/population_cases.py` builds the cross-org workgroup Doc's second test
kind — one query patient against a candidate pool, expected answer a set rather
than a single label — on top of the same generation logic as `labeled_pairs.py`.
Run it the same way:

```
PYTHONPATH=. uv run python evaluation/export_population_dataset.py
```

Same `SAMPLE_SIZE` env-var override and one-shard default as `labeled_pairs.py`;
additionally accepts `POOL_SIZE` (default 40, per the current Doc's "forty
near-misses" framing) to control each query's candidate-pool cap. Writes two
files (`OUTPUT_PATH`-style overrides: `CANDIDATES_PATH`, `QUERIES_PATH`) — see
`evaluation/cases/README.md`'s "Two test tiers" section for the schema and how
to consume it, and `docs/sessions/pending/session_12.md` for why this tier
exists and what it does and doesn't cover relative to `labeled_pairs.py`'s
per-provision pairs.

**ONC ground-truth caveat (verified 2026-08-31, session 12):** the current Doc
justifies adopting ONC by saying it "ships its own answer key" — multiple
records per person, grouped by `EnterpriseID`. Direct inspection of this repo's
vendored shards shows that's not true of this specific copy: all 1,000,000
records have unique `EnterpriseID`s, zero duplicates (see `onc_loader.py`'s
module docstring). `population_cases.py` and `labeled_pairs.py` don't depend on
that structure — every true-match cluster is built from this repo's own
single-edit variant generation, with ids assigned by the generator, not looked
up from ONC — but don't assume ONC's native duplication is available here if
you're building something new against it.

## Memory & scale — read before running this against the full ONC dataset

This is a real, previously-encountered failure mode, not a hypothetical one: loading the full
ONC dataset and running large transformations against it has crashed a Databricks cluster before
(per an internal design discussion, 2026-08-14). Three things compound this specifically for this
code path:

1. **`onc_loader.load_onc_patients()` has no streaming.** It reads whichever CSV paths you pass
   it entirely into one Python list of nested dicts. Passing it `sorted(onc_dir.glob("*.csv"))`
   (all 9 shards) materializes all ~1,000,000 records in memory at once — there is no
   chunked/lazy mode.
2. **`NormalizationManager.normalize_batch()` (or a per-record loop calling `.normalize()`)
   produces a second full copy** of whatever list you feed it — normalization is explicitly
   documented as non-mutating (`manager.py`: "The original dict is not mutated"). Running this
   over the full dataset means holding two ~1,000,000-record lists in memory simultaneously,
   not one.
3. **`build_labeled_pairs()` and `mine_shared_address_hard_negatives()` both assume their input
   is already a fully-materialized, in-memory list** — they don't take a file path or a
   generator. Whatever memory pressure steps 1-2 already created is the baseline they add their
   own (smaller, per-record-transient) overhead on top of.

None of this is new to this session's code specifically — `evaluation/onc_baseline.py`'s own
`__main__` (session 3) already loads all 9 shards unconditionally and runs the same
normalize-then-transform pattern. This session's code doesn't fix that; it just doesn't make it
worse by default, since `labeled_pairs.py`'s `__main__` loads one shard and samples it down
rather than following `onc_baseline.py`'s all-shards pattern. `export_test_dataset.py`'s
`__main__` follows the identical default (one shard, `SAMPLE_SIZE`-limited) since it shares
`generate_raw_pairs()` with `labeled_pairs.py` — the same caution applies before raising
`SAMPLE_SIZE` or passing it more than one shard's worth of patients.
`export_population_dataset.py`'s `__main__` follows the same default too, with one addition:
`population_cases.py` normalizes its own copy of `patients` independently (needed for its
random-distractor top-up step), on top of whatever `generate_raw_pairs()` already normalized
internally — a third full copy at full scale, not just the two steps 1-2 already describe. Fine
at the documented default (`SAMPLE_SIZE=2000` on one shard); worth remembering before raising
`SAMPLE_SIZE`, `POOL_SIZE`, or passing more than one shard.

**Practical guidance if you need to scale this up:**

- **Prefer one shard at a time, not all 9 concatenated.** Each shard is ~110K rows (~1/9th of
  the full dataset) — a meaningfully smaller working set than the full ~1,000,000.
- **Sample before transforming, not after.** Slice the patient list down (`patients[:N]`)
  *before* calling `NormalizationManager`/`build_labeled_pairs`, not after loading and
  normalizing everything and then discarding most of it — the peak memory is what matters, not
  the final output size.
- **If you genuinely need full-dataset scale (e.g. the Doc's §4 ≥1,000,000-record collision
  validation, which this session's code does not attempt), do it as a distributed job, not a
  single-process Python list.** On Databricks specifically: express the load/normalize/transform
  as Spark operations (`spark.read.csv(...)`, `.rdd.map(...)`, or a pandas-UDF applied per
  partition) so the work is distributed across executors rather than collected onto the driver
  as one Python list — the same shape session 4's `notebooks/fhir_match_data_source.py` already
  uses for its own real-data query (`spark.sql(...)`, never a driver-side full materialization).
  Do not `collect()` the full dataset onto the driver and then call this session's
  Python-list-based functions on it directly.
- **When in doubt, measure before you scale.** Time and profile memory on one shard, sampled
  down, before running anything against the full dataset — this is exactly the step that was
  skipped the time this crashed a cluster previously.
