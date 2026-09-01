"""Materialize labeled_pairs.py's generated pairs as a portable, algorithm-
agnostic test-case manifest - the Google Doc's ("Proposal: A Shared Test
Dataset for CMS v3.3.0 Patient Matching Compliance") Section 3 "Test case
format": one row per test case, with a stable case ID, the source and target
Patient resources as FHIR JSON, the expected outcome, and a rationale/
provenance string - "the artifact the workgroup actually shares and versions,
not code."

Sessions 9/10's LabeledPair output (rule_eval.LabeledPair) is deliberately
NOT this format: LabeledPair.features holds already-extracted PatientFields
(this repo's own internal representation, consumed directly by
MatchingEngine.evaluate_pair() - see onc_baseline.py), not raw FHIR JSON, so
it assumes this repo's own matching implementation and isn't something
another organization could run their own algorithm against. This module
builds the raw-FHIR-JSON manifest from the same underlying generation logic
(labeled_pairs.generate_raw_pairs()) instead of duplicating it.

Run standalone from the repo root:

    PYTHONPATH=. python evaluation/export_test_dataset.py

See labeled_pairs.py's module docstring for the "Memory & scale" caution -
this script defaults to the same one-shard, sampled-down population for the
same reason (a prior real cluster crash loading the full ~1,000,000-record
ONC dataset at once).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List

from labeled_pairs import DEFAULT_SAMPLE_SIZE, generate_raw_pairs
from onc_loader import load_onc_patients

Patient = Dict[str, Any]
FrequencyLookup = Callable[[str], float]

# cases/ (not a bare repo-root cases/, per the Doc's own proposed layout for
# the eventual neutral cross-org repo) - this repo is this organization's
# staging copy, not that repo, per SYNTHETIC_DATA_COMPARISON.md's
# "Repo-ownership note".
DEFAULT_OUTPUT_PATH = Path(__file__).parent / "cases" / "sample_labeled_pairs.jsonl"


@dataclass(frozen=True)
class LabeledCaseRecord:
    """One row of the Doc's Section 3 manifest format.

    Attributes:
        case_id: Stable identifier (same as labeled_pairs.RawPair.pair_id).
        source: The query/"Outside Record" FHIR Patient resource.
        target: The candidate/"Internal Record" FHIR Patient resource.
        expected_match: The gold label.
        rationale: Which category/provenance this case traces to (Design
            Principle 2: "every test case traces to a specific spec
            provision").
        frequency: Relative real-world prevalence weight for this case's
            category - NOT the raw count of how many cases of this category
            exist in the file (that's a generation-parameter artifact, e.g.
            SAMPLE_SIZE or institutional_group_size, not a prevalence signal).
            Defaults to 1.0 for every case via uniform_frequency() (below) -
            i.e. no real-world weighting applied yet. See
            evaluation/prevalence_estimates.py (a follow-up PR) for real,
            cited public-source estimates per category, and this module's
            `frequency_lookup` parameter for how to supply them.

            SCOPE, per session 12: this field is documentation/analysis
            metadata only, not a substitute for real precision/FDR/F1/
            accuracy - the cross-org workgroup's finalized proposal computes
            those over a separate, naturally-representative population-query
            tier (evaluation/population_cases.py) instead of by reweighting
            this file's curated, rare-case-oversampled counts.
    """

    case_id: str
    source: Patient
    target: Patient
    expected_match: bool
    rationale: str
    frequency: float = 1.0


def uniform_frequency(rationale: str) -> float:
    """Default frequency_lookup: every case weighted equally (1.0),
    regardless of category - i.e. this dataset's raw per-category case
    counts are NOT a real-world-prevalence signal (see LabeledCaseRecord's
    `frequency` docstring). Kept as the default rather than silently
    guessing a real-world weight."""
    return 1.0


def format_rationale(strata: Dict[str, Any]) -> str:
    """Render a RawPair's strata dict as a human-readable provenance string,
    e.g. "fuzzy_variant/dob_day" or "hard_negative (postalCode=10001,
    birthDate=1980-01-01)".

    `pair_type` plus its single most-specific companion key (mutation/case/
    category, whichever is present) forms the "<pair_type>/<subtype>" head,
    matching the same subtype-selection precedence labeled_pairs.py's own
    __main__ summary uses. Every other key in strata is appended as
    "key=value" context, sorted for determinism.
    """
    pair_type = strata.get("pair_type", "unknown")
    subtype_key = next(
        (k for k in ("mutation", "case", "category") if strata.get(k)), None
    )
    head = f"{pair_type}/{strata[subtype_key]}" if subtype_key else str(pair_type)

    extra_keys = sorted(k for k in strata if k not in {"pair_type", subtype_key})
    if not extra_keys:
        return head
    extras = ", ".join(f"{k}={strata[k]}" for k in extra_keys)
    return f"{head} ({extras})"


def build_test_case_records(
    patients: List[Patient],
    *,
    n_fuzzy_variants_per_patient: int = 1,
    include_normalization_edge_cases: bool = True,
    include_special_populations: bool = True,
    institutional_group_size: int = 3,
    seed: int = 0,
    frequency_lookup: FrequencyLookup = uniform_frequency,
) -> List[LabeledCaseRecord]:
    """Build the portable test-case manifest from ONC patients, using the
    same generation logic build_labeled_pairs() uses (labeled_pairs.
    generate_raw_pairs()) but keeping the raw FHIR Patient dicts instead of
    extracting PatientFields.

    `frequency_lookup` maps each case's formatted `rationale` string to a
    `frequency` weight (default: uniform_frequency(), every case weighted
    1.0). Pass a different lookup (e.g. evaluation/prevalence_estimates.py's
    real, cited estimates) to apply real-world-prevalence weighting without
    touching this function.
    """
    records = []
    for raw in generate_raw_pairs(
        patients,
        n_fuzzy_variants_per_patient=n_fuzzy_variants_per_patient,
        include_normalization_edge_cases=include_normalization_edge_cases,
        include_special_populations=include_special_populations,
        institutional_group_size=institutional_group_size,
        seed=seed,
    ):
        rationale = format_rationale(dict(raw.strata))
        records.append(
            LabeledCaseRecord(
                case_id=raw.pair_id,
                source=raw.query_patient,
                target=raw.candidate_patient,
                expected_match=raw.is_true_match,
                rationale=rationale,
                frequency=frequency_lookup(rationale),
            )
        )
    return records


def write_jsonl(records: List[LabeledCaseRecord], path: Path) -> None:
    """Write one JSON object per line - case_id, source, target,
    expected_match, rationale, frequency - creating parent directories if
    needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for record in records:
            f.write(
                json.dumps(
                    {
                        "case_id": record.case_id,
                        "source": record.source,
                        "target": record.target,
                        "expected_match": record.expected_match,
                        "rationale": record.rationale,
                        "frequency": record.frequency,
                    }
                )
                + "\n"
            )


if __name__ == "__main__":
    # researched_frequency() applies evaluation/prevalence_estimates.py's real,
    # cited public-source prevalence weights (pending maintainer review as of
    # this writing - see docs/sessions/completed/session_10.md's Task 9 notes).
    # Pass frequency_lookup=uniform_frequency explicitly (or call
    # build_test_case_records() directly) to opt back out to the neutral
    # default.
    from prevalence_estimates import researched_frequency

    sample_size = int(os.environ.get("SAMPLE_SIZE", DEFAULT_SAMPLE_SIZE))
    onc_dir = Path(__file__).parent / "fixtures" / "onc"
    # One shard only - see this module's and labeled_pairs.py's docstrings.
    shard = sorted(onc_dir.glob("*.csv"))[0]
    patients = load_onc_patients([shard])[:sample_size]
    records = build_test_case_records(patients, frequency_lookup=researched_frequency)
    output_path = Path(os.environ.get("OUTPUT_PATH", str(DEFAULT_OUTPUT_PATH)))
    write_jsonl(records, output_path)
    n_true = sum(r.expected_match for r in records)
    print(
        f"Wrote {len(records)} test cases ({n_true} expected_match=true, "
        f"{len(records) - n_true} expected_match=false) from {len(patients)} "
        f"ONC patients (one shard, sampled to SAMPLE_SIZE={sample_size}) to "
        f"{output_path}"
    )
