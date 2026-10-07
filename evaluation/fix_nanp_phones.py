"""One-off: make every phone in the committed case files NANP-valid.

The committed `evaluation/cases/*.jsonl` are curated snapshots (they cannot be
regenerated reproducibly - see `export_realistic_dataset.py`), so instead of
regenerating them this rewrites only phone strings, in place, with the same
deterministic mapping the loader now applies (`onc_loader.make_nanp_valid`).
Nothing else in any record changes, and the mapping is idempotent.

Run from the repo root:

    PYTHONPATH=evaluation uv run python evaluation/fix_nanp_phones.py [CASES_DIR]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterator

from onc_loader import make_nanp_valid

DEFAULT_CASES_DIR = Path(__file__).resolve().parent / "cases"
# (file, keys whose value is a FHIR Patient dict; "patient" for candidates)
_PATIENT_KEYS = {
    "sample_labeled_pairs.jsonl": ("source", "target"),
    "population_queries.jsonl": ("query",),
    "population_candidates.jsonl": ("patient",),
}


def _phone_entries(patient: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    for entry in patient.get("telecom") or []:
        if entry.get("system") == "phone" and entry.get("value"):
            yield entry


def fix_record(record: Dict[str, Any], keys: tuple[str, ...]) -> int:
    """Rewrite invalid phones on the named patient dicts; return how many changed."""
    changed = 0
    for key in keys:
        for entry in _phone_entries(record[key]):
            fixed = make_nanp_valid(entry["value"])
            if fixed != entry["value"]:
                entry["value"] = fixed
                changed += 1
    return changed


def fix_file(path: Path, keys: tuple[str, ...]) -> int:
    lines = []
    changed = 0
    with path.open() as f:
        for line in f:
            record = json.loads(line)
            changed += fix_record(record, keys)
            lines.append(json.dumps(record))
    path.write_text("\n".join(lines) + "\n")
    return changed


def main(argv: list[str]) -> int:
    cases_dir = Path(argv[1]) if len(argv) > 1 else DEFAULT_CASES_DIR
    for name, keys in _PATIENT_KEYS.items():
        print(f"{name}: {fix_file(cases_dir / name, keys)} phone values rewritten")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
