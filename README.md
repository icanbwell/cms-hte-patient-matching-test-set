# cms-hte-patient-matching-test-set
Test set for validating an algorithm against the CMS HTE Patient Matching Specification.

This repo was split out of [icanbwell/patient-matching](https://github.com/icanbwell/patient-matching),
which holds a reference matching implementation this code was originally developed against.
As of session 13, this repo has no runtime dependency on that (or any) matching engine — it only
produces portable, algorithm-agnostic test data (see `evaluation/DESIGN.md`'s Design Principle 1
and `docs/sessions/completed/session_13.md`).

## Contents

- `evaluation/` — the generator: fuzzy-mutation and hard-negative-mining code that builds the
  labeled CMS test dataset. Start with `evaluation/DESIGN.md` and
  `evaluation/SYNTHETIC_DATA_SETUP.md`.
- `evaluation/cases/` — the materialized, portable test-case dataset. See
  `evaluation/cases/README.md` for how to run an algorithm against it.
- `notebooks/` — `rule_eval_demo.ipynb`, a demo of the algorithm-agnostic statistical comparison
  harness (`evaluation/rule_eval.py`).
- `docs/sessions/` — the session logs that narrate how this dataset and its generation code were
  designed and built (carried over from patient-matching's session-planning process).

## Setup

```
uv sync
```

## Development

```
make tests          # uv run pytest . — also CI's build_and_test.yml gate
make lint           # uv run ruff check .
make typecheck      # uv run mypy, evaluation/ and notebooks/ separately (see Makefile comment)
make run-pre-commit # ruff check + ruff format over the whole repo
```

Run `uv run pre-commit install` once to also get these as a local git hook.
