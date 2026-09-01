# cms-hte-patient-matching-test-set
Test set for validating an algorithm against the CMS HTE Patient Matching Specification.

This repo was split out of a private reference matching implementation this code was originally
developed against. As of session 13, this repo has no runtime dependency on that (or any) matching
engine — it only produces portable, algorithm-agnostic test data (see `evaluation/DESIGN.md`'s
Design Principle 1 and `docs/sessions/completed/session_13.md`).

## Contents

- `evaluation/` — the generator: fuzzy-mutation and hard-negative-mining code that builds the
  labeled CMS test dataset. Start with `evaluation/DESIGN.md` and
  `evaluation/SYNTHETIC_DATA_SETUP.md`.
- `evaluation/cases/` — the materialized, portable test-case dataset. See
  `evaluation/cases/README.md` for how to run an algorithm against it.
- `notebooks/` — `rule_eval_demo.ipynb`, a demo of the algorithm-agnostic statistical comparison
  harness (`evaluation/rule_eval.py`).
- `docs/sessions/` — the session logs that narrate how this dataset and its generation code were
  designed and built (carried over from the originating repo's session-planning process).

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

## Data attribution

Every record in `evaluation/fixtures/onc/` and every generated test case derived from it
(`evaluation/cases/`) traces back to the public [ONC 2017 Patient Matching Algorithm
Challenge](https://healthit.gov/blog/interoperability/demystifying-patient-matching-algorithms/)
dataset, published by the Office of the National Coordinator for Health IT and also mirrored at
[onc-healthit/patient-matching](https://github.com/onc-healthit/patient-matching) — already
synthetic, non-PHI data. See `evaluation/cases/README.md`'s "How this test data was generated" for
exactly how this repo's own code (mutation, mining, and construction — never any real
member-organization data) builds on top of it. Vendoring this dataset here is for reproducibility;
if you redistribute it further, independently confirm the terms ONC published it under.

## License

Licensed under the [Apache License, Version 2.0](LICENSE). Contributions are accepted under the
same license — see `CONTRIBUTING.md`.
