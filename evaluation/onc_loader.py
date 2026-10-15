"""Load the public ONC Patient Matching Algorithm Challenge dataset as FHIR
Patient dicts, for use as this repo's test-case generation input
(labeled_pairs.py, population_cases.py, and the export_*.py manifest writers).

Column mapping started from the legacy production matching engine's own
create_patient_resource() transform and is now FHIR R4 conformant: empty
columns are omitted (never emitted as ""/[]), ALIAS becomes a separate
`use: nickname` name, and MOTHERS_MAIDEN_NAME maps to the standard
patient-mothersMaidenName extension (it is the mother's maiden name, not the
patient's own prior surname).

Values are copied through as-is (raw CSV case/punctuation) - this repo's own
generation pipeline does not normalize them (see session_13, which dropped
that step along with the removed matching-engine dependency). If you're testing your
own matching engine against the exported cases, apply your own normalization
convention first, same as you would for any other input.

ONC EnterpriseID uniqueness (verified 2026-08-31, session_12): every row across
all nine vendored shards under evaluation/fixtures/onc/ has a distinct
EnterpriseID - 1,000,000 rows, 1,000,000 unique ids, zero duplicates. This
means this specific vendored copy does NOT carry the "multiple records, same
underlying person, grouped by EnterpriseID" duplicate-linkage structure the
cross-org workgroup's current test-dataset proposal describes as ONC's built-in
answer key. See docs/sessions/completed/session_12.md for the full discussion and
why this repo's generation code (mutations.py's self-generated variants) does
not depend on that structure existing here. One piece of confirmed good news
this finding also settles: the "different EnterpriseID implies different
person" true-negative sampling assumption hard_negatives.py relies on is safe
for this dataset copy, since there is no found duplication to contradict it.
"""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List

_SAS_EPOCH = date(1900, 1, 1)
_GENDER_MAP = {
    "MALE": "male",
    "M": "male",
    "FEMALE": "female",
    "F": "female",
    "U": "unknown",
}
MOTHERS_MAIDEN_NAME_URL = (
    "http://hl7.org/fhir/StructureDefinition/patient-mothersMaidenName"
)


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _human_names(row: Dict[str, str]) -> List[Dict[str, Any]]:
    official: Dict[str, Any] = {"use": "official"}
    family = _clean(row.get("LAST"))
    if family:
        official["family"] = family
    given = [g for g in (_clean(row.get("FIRST")), _clean(row.get("MIDDLE"))) if g]
    if given:
        official["given"] = given
    suffix = _clean(row.get("SUFFIX"))
    if suffix:
        official["suffix"] = [suffix]
    names: List[Dict[str, Any]] = [official] if len(official) > 1 else []
    alias = _clean(row.get("ALIAS"))
    if alias:
        names.append({"use": "nickname", "text": alias})
    return names


def _decode_sas_date(raw: str) -> str:
    """ONC's DOB column is a SAS-style day-offset from 1900-01-01, minus 2.

    Matches the legacy production matching engine's own create_patient_resource()
    decoding exactly (confirmed via direct inspection of its CMS test suite,
    2026-07-29).
    """
    offset_days = int(raw) - 2
    return (_SAS_EPOCH + timedelta(days=offset_days)).isoformat()


def _row_to_patient(row: Dict[str, str]) -> Dict[str, Any]:
    patient: Dict[str, Any] = {
        "resourceType": "Patient",
        "id": row["EnterpriseID"],
        "gender": _GENDER_MAP.get(row.get("GENDER", "").upper(), "unknown"),
        "telecom": [],
        "address": [],
        "identifier": [],
    }
    names = _human_names(row)
    if names:
        patient["name"] = names
    mothers_maiden_name = _clean(row.get("MOTHERS_MAIDEN_NAME"))
    if mothers_maiden_name:
        patient["extension"] = [
            {"url": MOTHERS_MAIDEN_NAME_URL, "valueString": mothers_maiden_name}
        ]
    # The dataset's "Null" shard has intentionally-missing fields for incomplete-data
    # testing; the legacy production matching engine's transform only sets
    # birthDate when DOB is present (`if row["DOB"]:`) - mirrored here rather
    # than crashing.
    if row.get("DOB"):
        patient["birthDate"] = _decode_sas_date(row["DOB"])
    if row.get("PHONE"):
        patient["telecom"].append({"system": "phone", "value": row["PHONE"]})
    if row.get("PHONE2"):
        patient["telecom"].append({"system": "phone", "value": row["PHONE2"]})
    if row.get("EMAIL"):
        patient["telecom"].append({"system": "email", "value": row["EMAIL"]})
    if row.get("ADDRESS1"):
        lines = [row["ADDRESS1"]] + ([row["ADDRESS2"]] if row.get("ADDRESS2") else [])
        patient["address"].append(
            {
                "line": lines,
                "city": row.get("CITY", ""),
                "state": row.get("STATE", ""),
                "postalCode": row.get("ZIP", ""),
            }
        )
    if row.get("SSN"):
        patient["identifier"].append(
            {"system": "http://hl7.org/fhir/sid/us-ssn", "value": row["SSN"]}
        )
    return patient


def load_onc_patients(csv_paths: List[Path]) -> List[Dict[str, Any]]:
    """Load one or more ONC shard CSVs into normalized FHIR Patient dicts."""
    patients: List[Dict[str, Any]] = []
    for path in csv_paths:
        if ".." in str(path):
            raise ValueError(f"Invalid file path: {path!r}")
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                patients.append(_row_to_patient(row))
    return patients
