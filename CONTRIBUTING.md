# Contributing

This repo produces a portable, algorithm-agnostic test dataset for validating patient-matching
algorithms against the CMS HTE Patient Matching Specification. Contributions generally fall into
two buckets: **code** (generation logic, tooling, docs) and **test data** (new cases/categories in
the dataset itself). Data contributions have their own rules — read that section before adding new
cases.

By submitting a contribution, you agree it's licensed under this repo's [Apache License, Version
2.0](LICENSE), same as the rest of the codebase.

## Data contributions

This dataset is meant to be usable as evidence in a cross-org compliance conversation, so what
goes into it — and how it's disclosed — matters more than in a typical code repo.

- **Two sanctioned paths only**, per the current cross-org workgroup proposal ("A Shared Test
  Dataset for CMS Patient Matching Compliance"): synthetic records derived from a member
  organization's real data, or aggregate statistics (e.g. real-world prevalence rates). **There is
  no path for contributing raw real records** — see
  `evaluation/SYNTHETIC_DATA_COMPARISON.md`'s "What changed between the draft and the finalized
  proposal", delta 4.
- **Every record must trace to a disclosed synthesis method.** This repo's current (only) segment
  is entirely derived from the public ONC 2017 Patient Matching Algorithm Challenge dataset via
  this repo's own mutation/mining/construction code — see `evaluation/cases/README.md`'s
  "Provenance / synthesis-method disclosure" and "How this test data was generated" sections for
  the existing example. If you add a second segment (e.g. synthetic records derived from a member
  organization's real data), it needs its own disclosure written the same way — the existing
  repo-level note stops being sufficient once there's more than one segment.
- **Never construct a true-match pair by mutating a record and asserting the mutation is "a
  different person."** That only tests whether a matcher's own fuzzy tolerance is too generous —
  a statement about an algorithm, not about reality. True-non-match pairs must come from two
  genuinely distinct source identities (mined, per `hard_negatives.py`/
  `special_populations.py`'s pattern) or, when nothing to mine exists for a category (e.g.
  institutional residency), from constructing the collision on top of already-distinct real
  identities — never by fabricating the identities themselves.
- **Any fabricated field value must be unambiguously marked as synthetic** — see
  `special_populations.py`'s `"SYNTHETIC TEST ADDRESS"` / reserved-ZIP-block convention for the
  existing example. Don't fabricate a value that could be mistaken for a real one.
- **Prevalence/frequency numbers must be cited from a public source** (U.S. Census Bureau,
  CDC/NCHS, Pew Research Center, peer-reviewed record-linkage literature, etc.) or explicitly
  marked as an unresolved placeholder — never a guessed number. See
  `evaluation/prevalence_estimates.py`'s module docstring.
- **Every new case needs a `rationale`** that traces it to a specific category/generator, per
  Design Principle 2 in `evaluation/DESIGN.md` — no black-box cases.

## Adding a new test-case category (code)

New true-match or true-non-match categories follow the existing mutation/mining/construction
pattern:

1. Add the generator function(s) to the appropriate module — `mutations.py` for fuzzy-tolerance
   edits, `normalization_edge_cases.py` for cases normalization must fold to exact-match,
   `hard_negatives.py`/`special_populations.py` for mined or constructed true-non-match pairs (see
   "Data contributions" above for which is appropriate).
2. Wire it into **both** `labeled_pairs.generate_raw_pairs()` (the per-provision pairs tier) and
   `population_cases.build_population_dataset()` (the population-query tier) — they share this
   generation logic rather than duplicating it, and both tiers should stay in sync with what
   categories exist.
3. Give it a stable `pair_id`/`case_id` scheme and a `rationale` strata entry, following the
   existing `{id}::{category}` conventions (see `evaluation/cases/README.md`'s "Assembly, export,
   and reproducibility" section for the exact patterns already in use).
4. Add a same-named `test_*.py` file exercising the new generator — every existing generator
   module has one.
5. If the category has a real, citable real-world prevalence, add an entry to
   `evaluation/prevalence_estimates.py`; otherwise leave it out (it'll default to a neutral
   weight) rather than guessing.
6. Update `evaluation/cases/README.md` and `evaluation/SYNTHETIC_DATA_COMPARISON.md`'s coverage
   tables to reflect the new category.

## Development setup

```
uv sync
```

```
make tests          # uv run pytest . — this is also CI's build_and_test.yml gate
make lint           # uv run ruff check .
make typecheck      # uv run mypy evaluation
make run-pre-commit # ruff check --fix + ruff format, whole repo
uv run pre-commit install   # one-time: get the above as a real git hook
```

Before scaling any generation script beyond its default one-shard, `SAMPLE_SIZE`-limited run,
read `evaluation/SYNTHETIC_DATA_SETUP.md`'s "Memory & scale" section — loading the full
~1,000,000-record ONC dataset and transforming it at once has crashed a cluster before.

## Code conventions

- `from __future__ import annotations` at the top of every module; use `typing.Dict`/`List`/`Set`
  over builtin generics (matches this codebase's existing style — `ruff`'s `UP006`/`UP035`/
  `FURB192` are deliberately ignored in `pyproject.toml` rather than rewriting every existing
  file).
- Don't add a normalization step to the generation pipeline — this repo deliberately copies field
  values through as-is (session 13 dropped that step along with the runtime dependency on any
  matching engine); any generated FHIR JSON should carry raw ONC case/punctuation, same as today.
- Keep generation logic algorithm-agnostic — nothing under `evaluation/` should take a dependency
  on, or assume the shape of, any specific matching implementation. This repo only produces test
  data.

## Submitting a change

1. Branch off `main`.
2. Run `make run-pre-commit` and `make typecheck` before pushing — CI (`test`, `lint`, and Aikido
   Security's automated code scan) must be green before a PR can merge.
3. Open a PR describing what changed and why. If your change affects the generated dataset files
   under `evaluation/cases/`, regenerate them via the commands in `evaluation/cases/README.md`'s
   "Regenerating or extending this file" section and include the regenerated output in the diff.
