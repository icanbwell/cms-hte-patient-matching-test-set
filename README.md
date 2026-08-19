# cms-hte-patient-matching-test-set
Test set for validating an algorithm against the CMS HTE Patient Matching Specification.

This repo was split out of [icanbwell/patient-matching](https://github.com/icanbwell/patient-matching),
which still holds the reference matching implementation this code was originally developed
against.

## Contents

- `evaluation/` — the generator: fuzzy-mutation and hard-negative-mining code that builds the
  labeled CMS test dataset, plus the ONC self-match baseline harness. Start with
  `evaluation/DESIGN.md` and `evaluation/SYNTHETIC_DATA_SETUP.md`.
- `evaluation/cases/` — the materialized, portable test-case dataset. See
  `evaluation/cases/README.md` for how to run an algorithm against it.
- `notebooks/` — demo notebooks (`cms_matching_demo.ipynb`, `rule_eval_demo.ipynb`) and the FHIR
  match-data-source helper used to exercise the dataset against a live matching engine.
- `docs/sessions/` — the session logs that narrate how this dataset and its generation code were
  designed and built (carried over from patient-matching's session-planning process).

## Setup

```
uv sync
```

`evaluation/onc_baseline.py`, `notebooks/fhir_match_data_source.py`, and a few other modules
import from `patient_matching` (installed here as a git dependency — see `pyproject.toml`).
