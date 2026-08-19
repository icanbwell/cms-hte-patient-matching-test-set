"""Build rule_eval.py LabeledPairs from the ONC dataset, and run the current
engine's self-match baseline (session 3 of docs/sessions/).

Run from the repo root with the root package on the path (bare imports here
mirror evaluation/test_rule_eval.py's convention, since evaluation/ has no
__init__.py and is not an installed package):

    PYTHONPATH=. python evaluation/onc_baseline.py
"""

from __future__ import annotations

import random
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping, Set, Tuple

from onc_loader import load_onc_patients
from rule_eval import LabeledPair, compare, format_report, min_sample_size

from patient_matching.matching.field_extractor import FieldExtractor
from patient_matching.matching.in_memory_backend import InMemoryBackend
from patient_matching.matching.matching_engine import MatchingEngine
from patient_matching.normalization.manager import NormalizationManager

MASKING_SCENARIOS = ("none", "drop_email_phone")


@lru_cache(maxsize=1)
def _engine() -> MatchingEngine:
    """Lazily-built, read-only engine: evaluate_pair() never mutates the rule
    set, comparator, or (empty, unused) backend, so one instance safely serves
    every pair rather than reconstructing it per call."""
    return MatchingEngine(backend=InMemoryBackend([]))


def _mask(patient: Dict[str, Any], scenario: str) -> Dict[str, Any]:
    if scenario == "drop_email_phone":
        return {**patient, "telecom": []}
    return dict(patient)


def build_onc_pairs(
    patients: List[Dict[str, Any]], *, n_negative_samples: int, seed: int = 0
) -> List[LabeledPair]:
    """Build labeled pairs from ONC patients for rule_eval.py.

    Patients are run through NormalizationManager before extraction - the same
    contract every MatchingEngine caller must honor. FieldExtractor assumes
    already-normalized input, and FieldComparator.exact_match is a
    case-sensitive set intersection, so skipping this step would silently
    make every field comparison fail on raw ONC data's mixed-case values.
    """
    normalizer = NormalizationManager()
    extractor = FieldExtractor()
    normalized = [normalizer.normalize(p) for p in patients]
    pairs: List[LabeledPair] = []

    # True-match pairs: each record against each masked variant of itself.
    for p in normalized:
        q_fields = extractor.extract(p)
        for scenario in MASKING_SCENARIOS:
            c_fields = extractor.extract(_mask(p, scenario))
            pairs.append(
                LabeledPair(
                    features={"query": q_fields, "candidate": c_fields},
                    is_true_match=True,
                    strata={"scenario": scenario},
                    pair_id=f"{p['id']}::{scenario}",
                )
            )

    # True-non-match pairs: a random sample of distinct-record cross pairs.
    # ONC guarantees every row is a distinct individual, so any (i, j), i != j
    # pair is a genuine non-match - sampling avoids the O(n^2) full cross-product.
    rng = random.Random(seed)
    n = len(normalized)
    seen: Set[Tuple[int, int]] = set()
    while len(seen) < n_negative_samples:
        i, j = rng.randrange(n), rng.randrange(n)
        if i == j or (i, j) in seen or (j, i) in seen:
            continue
        seen.add((i, j))
        q_fields = extractor.extract(normalized[i])
        c_fields = extractor.extract(normalized[j])
        pairs.append(
            LabeledPair(
                features={"query": q_fields, "candidate": c_fields},
                is_true_match=False,
                strata={"scenario": "cross_pair"},
                pair_id=f"{normalized[i]['id']}::{normalized[j]['id']}",
            )
        )
    return pairs


def current_engine_matcher(features: Mapping[str, Any]) -> bool:
    """Adapts MatchingEngine.evaluate_pair to rule_eval.py's Matcher signature."""
    return _engine().evaluate_pair(features["query"], features["candidate"])


if __name__ == "__main__":
    onc_dir = Path(__file__).parent / "fixtures" / "onc"
    patients = load_onc_patients(sorted(onc_dir.glob("*.csv")))
    # Size the negative sample to detect a 1-percentage-point FPR shift at a
    # ~0.1% baseline FPR, per rule_eval.py's own power-calculation utility.
    n_negative = min_sample_size(p0=0.001, delta=0.01)
    pairs = build_onc_pairs(patients, n_negative_samples=n_negative)
    report = compare(
        current_engine_matcher,
        current_engine_matcher,  # self-comparison: this run establishes the baseline
        pairs,
        baseline_name="v3.2.2 (26 rules)",
        candidate_name="v3.2.2 (26 rules)",
    )
    output_path = Path(__file__).parent / "baselines" / "v3_2_2_onc_baseline.txt"
    output_path.parent.mkdir(exist_ok=True, parents=True)
    output_path.write_text(format_report(report))
    print(format_report(report))
