"""Dependency-free reference matchers used as the release gate's "known bad" yardstick."""

from __future__ import annotations

from typing import Any, Callable, Dict, Mapping

from identity_guard import identity_key, normalize_phone, normalize_token, ssn_of

Patient = Dict[str, Any]
Features = Mapping[str, Any]


def _telecom_values(patient: Patient, system: str) -> set[str]:
    values = set()
    for entry in patient.get("telecom") or []:
        if entry.get("system") != system:
            continue
        raw = str(entry.get("value") or "")
        token = normalize_phone(raw) if system == "phone" else raw.strip().casefold()
        if token:
            values.add(token)
    return values


def _street_key(patient: Patient) -> tuple[str, str] | None:
    addresses = patient.get("address") or []
    if not addresses:
        return None
    lines = addresses[0].get("line") or []
    street = normalize_token(lines[0]) if lines else ""
    zip_code = normalize_token(addresses[0].get("postalCode"))
    return (street, zip_code) if street and zip_code else None


def _family(patient: Patient) -> str:
    names = patient.get("name") or []
    return normalize_token(names[0].get("family")) if names else ""


def _first(patient: Patient) -> str:
    names = patient.get("name") or []
    given = (names[0].get("given") or []) if names else []
    return normalize_token(given[0]) if given else ""


def pair_features(a: Patient, b: Patient) -> Dict[str, bool]:
    """Boolean agreement flags for one (query, candidate) pair."""
    ssn_a, ssn_b = ssn_of(a), ssn_of(b)
    street_a, street_b = _street_key(a), _street_key(b)
    key_a, key_b = identity_key(a), identity_key(b)
    return {
        "phone": bool(_telecom_values(a, "phone") & _telecom_values(b, "phone")),
        "email": bool(_telecom_values(a, "email") & _telecom_values(b, "email")),
        "ssn": ssn_a is not None and ssn_a == ssn_b,
        "dob": bool(a.get("birthDate")) and a.get("birthDate") == b.get("birthDate"),
        "name_dob": key_a is not None and key_a == key_b,
        "family": bool(_family(a)) and _family(a) == _family(b),
        "given": bool(_first(a)) and _first(a) == _first(b),
        "address": street_a is not None and street_a == street_b,
    }


def _only(field: str) -> Callable[[Features], bool]:
    return lambda f: bool(f[field])


def _multi_field(f: Features) -> bool:
    score = (
        4 * f["ssn"]
        + 3 * f["name_dob"]
        + 2 * f["dob"]
        + 2 * f["given"]
        + 2 * f["family"]
        + 1 * f["address"]
        + 1 * f["phone"]
        + 1 * f["email"]
    )
    return score >= 6


SINGLE_FIELD_BASELINES: Dict[str, Callable[[Features], bool]] = {
    "phone_only": _only("phone"),
    "email_only": _only("email"),
    "ssn_only": _only("ssn"),
    "dob_only": _only("dob"),
    "name_dob_only": _only("name_dob"),
    "address_only": _only("address"),
}

MULTI_FIELD_BASELINE_NAME = "multi_field"

BASELINES: Dict[str, Callable[[Features], bool]] = {
    **SINGLE_FIELD_BASELINES,
    MULTI_FIELD_BASELINE_NAME: _multi_field,
}
