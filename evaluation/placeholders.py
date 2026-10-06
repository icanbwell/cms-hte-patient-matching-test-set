"""Well-known placeholder values and the scenarios built from them.

Real records routinely carry dummy values where the true one was unknown at
registration. Two scenarios use them:

- `placeholder_variant` (true match): one side carries a placeholder in one
  field; every other field still matches. DOB placeholders are deliberately
  excluded here: a placeholder DOB leaves a pair matchable only by rules that
  ignore DOB, which the CMS spec removed (BAI-1061).
- `construct_placeholder_collision_negatives` (true non-match): two distinct
  real people are given the SAME placeholder in one field; a matcher must not
  treat that shared dummy value as evidence.

Only the placeholder value is written; the underlying identities are real ONC
records and are never fabricated.
"""

from __future__ import annotations

import copy
import random
from typing import Any, Dict, Iterable, List, Tuple

from hard_negatives import HardNegativeCandidate
from identity_guard import SSN_SYSTEM, is_possible_same_person, normalize_token

Patient = Dict[str, Any]

SSN_PLACEHOLDERS: Tuple[str, ...] = (
    "000-00-0000",
    "999-99-9999",
    "123-45-6789",
    "111-11-1111",
)
PHONE_PLACEHOLDERS: Tuple[str, ...] = ("000-000-0000", "555-555-5555", "999-999-9999")
GIVEN_PLACEHOLDERS: Tuple[str, ...] = ("UNKNOWN", "BABY BOY", "BABY GIRL")
ADDRESS_PLACEHOLDERS: Tuple[str, ...] = ("HOMELESS", "UNKNOWN")
DOB_PLACEHOLDERS: Tuple[str, ...] = ("1900-01-01", "1901-01-01")

CATALOG: Dict[str, Tuple[str, ...]] = {
    "ssn": SSN_PLACEHOLDERS,
    "phone": PHONE_PLACEHOLDERS,
    "given": GIVEN_PLACEHOLDERS,
    "address": ADDRESS_PLACEHOLDERS,
    "dob": DOB_PLACEHOLDERS,
}

# Fields a true-match placeholder may use (no "dob": see module docstring).
POSITIVE_FIELDS: Tuple[str, ...] = ("ssn", "phone", "given", "address")
# Fields two strangers may share a placeholder in.
COLLISION_FIELDS: Tuple[str, ...] = ("ssn", "phone", "dob")


def apply_placeholder(
    patient: Patient, field: str, value: str, *, create_missing: bool = False
) -> Patient:
    """A copy of `patient` with `field` set to the placeholder `value`.

    With create_missing=False a record that lacks the field is returned
    unchanged (callers treat "unchanged" as "scenario does not apply");
    with True the field is added (used for collisions, where both sides must
    carry the shared dummy)."""
    modified = copy.deepcopy(patient)
    if field == "dob":
        if modified.get("birthDate") or create_missing:
            modified["birthDate"] = value
    elif field == "ssn":
        for identifier in modified.get("identifier") or []:
            if identifier.get("system") == SSN_SYSTEM:
                identifier["value"] = value
                break
        else:
            if create_missing:
                modified.setdefault("identifier", []).append(
                    {"system": SSN_SYSTEM, "value": value}
                )
    elif field == "phone":
        for entry in modified.get("telecom") or []:
            if entry.get("system") == "phone":
                entry["value"] = value
                break
        else:
            if create_missing:
                modified.setdefault("telecom", []).append(
                    {"system": "phone", "value": value}
                )
    elif field == "given":
        names = modified.get("name") or []
        if names and names[0].get("given"):
            names[0]["given"][0] = value
    elif field == "address":
        addresses = modified.get("address") or []
        if addresses and addresses[0].get("line"):
            addresses[0]["line"] = [value]
    else:
        raise ValueError(f"Unknown placeholder field: {field!r}")
    return modified


def placeholder_variant(
    patient: Patient, *, rng: random.Random
) -> Tuple[Patient, str] | None:
    """One placeholder in a random present field, or None if no field applies.
    Returns (variant, field)."""
    options = [
        f for f in POSITIVE_FIELDS if apply_placeholder(patient, f, "x") != patient
    ]
    if not options:
        return None
    field = rng.choice(sorted(options))
    return apply_placeholder(patient, field, rng.choice(CATALOG[field])), field


def _family(patient: Patient) -> str:
    names = patient.get("name") or []
    return normalize_token(names[0].get("family")) if names else ""


def construct_placeholder_collision_negatives(
    patients: Iterable[Patient],
    field: str,
    *,
    max_pairs: int = 100,
    rng: random.Random,
) -> List[HardNegativeCandidate]:
    """Pair distinct real people (different family names, not possibly the
    same person) and give BOTH the same placeholder in `field`. Each patient
    is used at most once; up to `max_pairs` pairs, in a seeded shuffle."""
    if field not in COLLISION_FIELDS:
        raise ValueError(f"field must be one of {COLLISION_FIELDS}, got {field!r}")
    pool = list(patients)
    rng.shuffle(pool)
    candidates: List[HardNegativeCandidate] = []
    unused: List[Patient] = []
    for patient in pool:
        if len(candidates) >= max_pairs:
            break
        partner = next(
            (
                other
                for other in unused
                if _family(other)
                and _family(patient)
                and _family(other) != _family(patient)
                and not is_possible_same_person(other, patient)
            ),
            None,
        )
        if partner is None:
            unused.append(patient)
            continue
        unused.remove(partner)
        value = rng.choice(CATALOG[field])
        candidates.append(
            HardNegativeCandidate(
                query=apply_placeholder(partner, field, value, create_missing=True),
                candidate=apply_placeholder(patient, field, value, create_missing=True),
                shared_fields={"case": field, "placeholder_value": value},
            )
        )
    return candidates
