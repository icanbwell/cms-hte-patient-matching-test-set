"""Same-person detection shared by every negative-pair generator and the audit."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, FrozenSet, Tuple

Patient = Dict[str, Any]

SSN_SYSTEM = "http://hl7.org/fhir/sid/us-ssn"

PLACEHOLDER_SSNS: FrozenSet[str] = frozenset(
    {
        "000000000",
        "111111111",
        "123456789",
        "999999999",
        "078051120",  # the Woolworth wallet-card SSN
    }
)


def normalize_token(value: object) -> str:
    """Casefold, strip diacritics, keep only letters and digits."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def normalize_phone(value: object) -> str:
    """Digits only, with a leading US country code dropped from 11-digit numbers."""
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 11 and digits.startswith("1"):
        return digits[1:]
    return digits


def is_placeholder_ssn(digits: str) -> bool:
    """True for known fake SSNs and any value the SSA never issues.

    Not 9 digits, one repeated digit, area 000/666/9xx, group 00, or serial 0000.
    """
    return (
        digits in PLACEHOLDER_SSNS
        or len(digits) != 9
        or len(set(digits)) == 1
        or digits[:3] in ("000", "666")
        or digits[0] == "9"
        or digits[3:5] == "00"
        or digits[5:] == "0000"
    )


def ssn_of(patient: Patient) -> str | None:
    """Digits-only SSN, or None if absent or a placeholder/invalid value."""
    for identifier in patient.get("identifier") or []:
        if identifier.get("system") == SSN_SYSTEM:
            digits = re.sub(r"\D", "", str(identifier.get("value") or ""))
            if digits and not is_placeholder_ssn(digits):
                return digits
    return None


def identity_key(patient: Patient) -> Tuple[str, str, str] | None:
    """(first given, family, birthDate) normalized, or None if any part is missing."""
    names = patient.get("name") or []
    if not names:
        return None
    given = names[0].get("given") or []
    first = normalize_token(given[0]) if given else ""
    family = normalize_token(names[0].get("family"))
    dob = str(patient.get("birthDate") or "")
    if not (first and family and dob):
        return None
    return (first, family, dob)


def is_possible_same_person(a: Patient, b: Patient) -> bool:
    """True if a and b share a real SSN, or share normalized first name + family + DOB."""
    ssn_a, ssn_b = ssn_of(a), ssn_of(b)
    if ssn_a is not None and ssn_a == ssn_b:
        return True
    key_a, key_b = identity_key(a), identity_key(b)
    return key_a is not None and key_a == key_b
