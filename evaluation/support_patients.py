"""Small synthetic patient sets shared by the scenario tests (test-only data)."""

from __future__ import annotations

from typing import Any, Dict, List

from identity_guard import SSN_SYSTEM

Patient = Dict[str, Any]


def _base(id_: str, family: str, given: str) -> Patient:
    return {
        "resourceType": "Patient",
        "id": id_,
        "name": [{"family": family, "given": [given]}],
        "gender": "female",
        "birthDate": "1980-06-15",
        "telecom": [],
        "address": [],
        "identifier": [],
    }


def drift_population() -> List[Patient]:
    """Six distinct people, each with two phones, an email, an address, an SSN."""
    patients = []
    for i, family in enumerate(["Smith", "Jones", "Lee", "Okafor", "Garcia", "Chen"]):
        patient = _base(f"d{i}", family, f"Given{i}")
        patient["gender"] = "female" if i % 2 else "male"
        patient["birthDate"] = f"19{50 + i * 7}-0{i + 1}-1{i}"
        patient["telecom"] = [
            {"system": "phone", "value": f"347-100-000{i}"},
            {"system": "phone", "value": f"718-200-000{i}"},
            {"system": "email", "value": f"G{i}@EXAMPLE.COM"},
        ]
        patient["address"] = [
            {
                "line": [f"{i + 1} Main St"],
                "city": "NY",
                "state": "NY",
                "postalCode": f"1000{i}",
            }
        ]
        patient["identifier"] = [{"system": SSN_SYSTEM, "value": f"900-00-000{i}"}]
        patients.append(patient)
    return patients


def drift_donors() -> List[Patient]:
    """Held-out donor records: a phone, an email, a street and a surname each."""
    donors = []
    for i, family in enumerate(["Hart", "Ito", "Moreau"]):
        donor = _base(f"donor{i}", family, "Donor")
        donor["telecom"] = [
            {"system": "phone", "value": f"212-555-01{i}0"},
            {"system": "email", "value": f"D{i}@DONOR.COM"},
        ]
        donor["address"] = [
            {
                "line": [f"{90 + i} Elm St"],
                "city": "NY",
                "state": "NY",
                "postalCode": f"2000{i}",
            }
        ]
        donors.append(donor)
    return donors
