"""Load the public ONC Patient Matching Algorithm Challenge dataset as normalized
FHIR Patient dicts, for use as evaluation/rule_eval.py input.

Column mapping mirrors the legacy production matching engine's own
create_patient_resource() transform (confirmed via direct inspection of its CMS
test suite), extended to also populate MOTHERS_MAIDEN_NAME and ALIAS, which
that transform reads from the CSV but never maps into the output FHIR
resource.

Values are copied through as-is (raw CSV case/punctuation); callers must run the
result through patient_matching.normalization.NormalizationManager before handing
it to FieldExtractor, same as any other MatchingEngine caller.

ONC EnterpriseID uniqueness (verified 2026-08-31, session_12): every row across
all nine vendored shards under evaluation/fixtures/onc/ has a distinct
EnterpriseID - 1,000,000 rows, 1,000,000 unique ids, zero duplicates. This
means this specific vendored copy does NOT carry the "multiple records, same
underlying person, grouped by EnterpriseID" duplicate-linkage structure the
cross-org workgroup's current test-dataset proposal describes as ONC's built-in
answer key. See docs/sessions/pending/session_12.md for the full discussion and
why this repo's generation code (mutations.py's self-generated variants) does
not depend on that structure existing here. One piece of confirmed good news
this finding also settles: onc_baseline.py's "different EnterpriseID implies
different person" true-negative sampling assumption is safe for this dataset
copy, since there is no found duplication to contradict it.
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


def _decode_sas_date(raw: str) -> str:
    """ONC's DOB column is a SAS-style day-offset from 1900-01-01, minus 2.

    Matches the legacy production matching engine's own create_patient_resource()
    decoding exactly (confirmed via direct inspection of its CMS test suite,
    2026-07-29).
    """
    offset_days = int(raw) - 2
    return (_SAS_EPOCH + timedelta(days=offset_days)).isoformat()


def _row_to_patient(row: Dict[str, str]) -> Dict[str, Any]:
    given = [row["FIRST"]]
    if row.get("MIDDLE"):
        given.append(row["MIDDLE"])
    if row.get("ALIAS"):
        given.append(row["ALIAS"])
    family_names = [row["LAST"]]
    # Not mapped by the legacy production matching engine's transform - included
    # here so this repo's normalization/matching sees prior/maiden names per
    # Core Principle 10.
    if row.get("MOTHERS_MAIDEN_NAME"):
        family_names.append(row["MOTHERS_MAIDEN_NAME"])

    patient: Dict[str, Any] = {
        "resourceType": "Patient",
        "id": row["EnterpriseID"],
        "name": [
            {
                "family": fam,
                "given": given,
                "suffix": [row["SUFFIX"]] if row.get("SUFFIX") else [],
            }
            for fam in family_names
        ],
        "gender": _GENDER_MAP.get(row.get("GENDER", "").upper(), "unknown"),
        "telecom": [],
        "address": [],
        "identifier": [],
    }
    # The dataset's "Null" shard has intentionally-missing fields for incomplete-data
    # testing; the legacy production matching engine's transform only sets
    # birthDate when DOB is present (`if row["DOB"]:`) - mirrored here rather
    # than crashing.
    if row.get("DOB"):
        patient["birthDate"] = _decode_sas_date(row["DOB"])
    if row.get("PHONE"):
        patient["telecom"].append({"system": "phone", "value": row["PHONE"]})
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
