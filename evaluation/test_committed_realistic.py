"""The committed realistic release files pass their gate and match the code."""

from __future__ import annotations

import json

from audit import CASES_DIR
from drift_profile import DriftProfile
from export_inputs import DEFAULT_DONOR_SIZE
from export_realistic_dataset import DATASET_VERSION, generator_fingerprint
from labeled_pairs import DEFAULT_SAMPLE_SIZE
from release_gate import failures, run


def test_committed_realistic_files_pass_the_realistic_gate():
    results = run("realistic")
    assert failures(results) == [], [(r.name, r.value) for r in failures(results)]


def test_committed_realistic_manifest_matches_the_code():
    manifest = json.loads((CASES_DIR / "realistic_manifest.json").read_text())
    assert manifest["dataset_version"] == DATASET_VERSION
    assert manifest["generator_fingerprint"] == generator_fingerprint(), (
        "generator code changed since the committed realistic files were built; "
        "run `make generate-realistic-dataset` and commit the result"
    )
    assert manifest["seed"] == 0
    assert manifest["sample_size"] == DEFAULT_SAMPLE_SIZE
    assert manifest["donor_size"] == DEFAULT_DONOR_SIZE
    assert manifest["profile_source"] == DriftProfile().source
