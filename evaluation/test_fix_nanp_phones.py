"""Unit tests for fix_nanp_phones.py."""

from __future__ import annotations

import json
from pathlib import Path

from fix_nanp_phones import fix_file, fix_record


def _patient(phone: str) -> dict:
    return {
        "resourceType": "Patient",
        "telecom": [
            {"system": "phone", "value": phone},
            {"system": "email", "value": "a@b.com"},
        ],
    }


def test_fix_record_rewrites_only_invalid_phones_on_named_keys() -> None:
    record = {
        "source": _patient("917-130-8285"),
        "target": _patient("347-984-6839"),
        "other": _patient("917-130-8285"),
    }
    assert fix_record(record, ("source", "target")) == 1
    assert record["source"]["telecom"][0]["value"] == "917-230-8285"
    assert record["target"]["telecom"][0]["value"] == "347-984-6839"
    assert record["other"]["telecom"][0]["value"] == "917-130-8285"
    assert record["source"]["telecom"][1]["value"] == "a@b.com"


def test_fix_file_is_idempotent_and_preserves_other_content(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    rec = {"source": _patient("917-130-8285"), "name": "K\u00e1THERINE"}
    path.write_text(json.dumps(rec) + "\n")

    assert fix_file(path, ("source",)) == 1
    first = path.read_text()
    assert fix_file(path, ("source",)) == 0
    assert path.read_text() == first
    assert "K\\u00e1THERINE" in first
