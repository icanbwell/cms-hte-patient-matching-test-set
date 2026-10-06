"""Release gate: compare audit.py's report against release_thresholds.json.

A metric's `status` is "tracked" (reported, never fails) or "enforced" (a
violation fails the gate and `make audit`). A later PR that fixes a
metric flips it from "tracked" to "enforced" in the same change.

Run from the repo root:

    PYTHONPATH=. uv run python evaluation/release_gate.py

Set AUDIT_DATASET=full to gate the full-ONC export instead of the committed sample.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping

from audit import build_report, dataset_paths

THRESHOLDS_PATH = Path(__file__).parent / "release_thresholds.json"
VALID_STATUSES = ("tracked", "enforced")
VALID_RULE_KEYS = frozenset({"min", "max", "status"})


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
    if isinstance(value, list):
        return float(len(value))
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name!r} is not a scalar metric and cannot be gated")
    return float(value)


def check(
    report: Mapping[str, Any], thresholds: Mapping[str, Mapping[str, Any]]
) -> List[GateResult]:
    results: List[GateResult] = []
    for name, rule in thresholds.items():
        if rule.get("status") not in VALID_STATUSES:
            raise ValueError(f"{name}: status must be one of {VALID_STATUSES}")
        unknown = set(rule) - VALID_RULE_KEYS
        if unknown:
            raise ValueError(f"{name}: unknown rule keys {sorted(unknown)}")
        if "min" not in rule and "max" not in rule:
            raise ValueError(f"{name}: rule needs at least one of min or max")
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


if __name__ == "__main__":
    dataset = os.environ.get("AUDIT_DATASET", "sample")
    gate_results = check(build_report(*dataset_paths(dataset)), load_thresholds())
    for r in gate_results:
        state = "ok" if r.passed else ("FAIL" if r.enforced else "tracked-fail")
        print(f"{state:13} {r.name} = {r.value:.4g}")
    sys.exit(1 if failures(gate_results) else 0)
