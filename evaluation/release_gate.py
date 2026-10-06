"""Release gate: compare audit.py's report against release_thresholds.json.

A metric's `status` is "tracked" (reported, never fails) or "enforced" (a
violation fails the gate and `make audit`). A later PR that fixes a
metric flips it from "tracked" to "enforced" in the same change.

Run from the repo root:

    PYTHONPATH=. uv run python evaluation/release_gate.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping

from audit import REALISTIC_PATHS, build_report

THRESHOLDS_PATH = Path(__file__).parent / "release_thresholds.json"
REALISTIC_THRESHOLDS_PATH = Path(__file__).parent / "release_thresholds_realistic.json"
VALID_STATUSES = ("tracked", "enforced")


@dataclass(frozen=True)
class GateResult:
    name: str
    value: float
    passed: bool
    enforced: bool


def metric_value(report: Mapping[str, Any], name: str) -> float:
    """Numeric value of a report metric; list-valued metrics gate on their length."""
    if name not in report:
        raise ValueError(f"release_thresholds.json names unknown metric: {name!r}")
    value = report[name]
    return float(len(value)) if isinstance(value, list) else float(value)


def check(
    report: Mapping[str, Any], thresholds: Mapping[str, Mapping[str, Any]]
) -> List[GateResult]:
    results: List[GateResult] = []
    for name, rule in thresholds.items():
        if rule["status"] not in VALID_STATUSES:
            raise ValueError(f"{name}: status must be one of {VALID_STATUSES}")
        value = metric_value(report, name)
        passed = ("max" not in rule or value <= rule["max"]) and (
            "min" not in rule or value >= rule["min"]
        )
        results.append(
            GateResult(name, value, passed, enforced=rule["status"] == "enforced")
        )
    return results


def load_thresholds(path: Path = THRESHOLDS_PATH) -> Dict[str, Dict[str, Any]]:
    with path.open() as f:
        return json.load(f)


def failures(results: List[GateResult]) -> List[GateResult]:
    return [r for r in results if r.enforced and not r.passed]


def run(dataset: str = "committed") -> List[GateResult]:
    """Evaluate one dataset's thresholds: "committed" (the checked-in case
    files) or "realistic" (the generated age/household-realistic files)."""
    if dataset == "committed":
        return check(build_report(), load_thresholds())
    if dataset == "realistic":
        pairs, queries, candidates = REALISTIC_PATHS
        report = build_report(pairs, queries, candidates)
        return check(report, load_thresholds(REALISTIC_THRESHOLDS_PATH))
    raise ValueError(f"dataset must be 'committed' or 'realistic', got {dataset!r}")


if __name__ == "__main__":
    gate_results = run(sys.argv[1] if len(sys.argv) > 1 else "committed")
    for r in gate_results:
        state = "ok" if r.passed else ("FAIL" if r.enforced else "tracked-fail")
        print(f"{state:13} {r.name} = {r.value:.4g}")
    sys.exit(1 if failures(gate_results) else 0)
