"""Same-person detection shared by every negative-pair generator and the audit."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import Any, Dict, FrozenSet, Iterable, List, Set, Tuple

from fhir_conformance import SSN_SYSTEM
from text_distance import levenshtein_distance

Patient = Dict[str, Any]

US_PHONE_DIGITS = 10

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


def _month_day_swapped(dob_a: str, dob_b: str) -> bool:
    """True if two ISO dates share a year and swap month and day (1980-03-11 / 1980-11-03)."""
    if len(dob_a) != 10 or len(dob_b) != 10 or dob_a[:4] != dob_b[:4]:
        return False
    return (
        dob_a[4] == dob_b[4] == "-"
        and dob_a[7] == dob_b[7] == "-"
        and dob_a[5:7] == dob_b[8:10]
        and dob_a[8:10] == dob_b[5:7]
    )


def _dobs_close(a: Patient, b: Patient) -> bool:
    """Birth dates within edit distance 1, or a month/day swap."""
    dob_a, dob_b = str(a.get("birthDate") or ""), str(b.get("birthDate") or "")
    if not (dob_a and dob_b):
        return False
    return levenshtein_distance(dob_a, dob_b, 1) <= 1 or _month_day_swapped(
        dob_a, dob_b
    )


def phone_set(patient: Patient) -> Set[str]:
    found = {
        normalize_phone(t.get("value"))
        for t in patient.get("telecom") or []
        if t.get("system") == "phone"
    }
    return {p for p in found if len(p) == US_PHONE_DIGITS}


def is_probable_duplicate(a: Patient, b: Patient) -> bool:
    """True if a and b are very likely one person recorded twice with a typo.

    Looser than is_possible_same_person (which is exact-match): ANY of
      - both have a real SSN and the SSNs are within edit distance 1;
      - they share a normalized 10-digit phone and the birth dates are close;
      - normalized first+family names are within edit distance 1 and the birth
        dates are close.
    "Close" means edit distance <= 1 on the ISO date or a month/day swap. A name
    match with a clearly different birth date is a legitimate hard negative and
    is not flagged."""
    ssn_a, ssn_b = ssn_of(a), ssn_of(b)
    if (
        ssn_a is not None
        and ssn_b is not None
        and levenshtein_distance(ssn_a, ssn_b, 1) <= 1
    ):
        return True
    if not _dobs_close(a, b):
        return False
    if phone_set(a) & phone_set(b):
        return True
    key_a, key_b = identity_key_names(a), identity_key_names(b)
    return (
        key_a is not None
        and key_b is not None
        and levenshtein_distance(key_a, key_b, 1) <= 1
    )


def identity_key_names(patient: Patient) -> str | None:
    """Normalized 'first family', or None if either is missing."""
    names = patient.get("name") or []
    if not names:
        return None
    given = names[0].get("given") or []
    first = normalize_token(given[0]) if given else ""
    family = normalize_token(names[0].get("family"))
    return f"{first} {family}" if first and family else None


def looks_like_same_person(a: Patient, b: Patient) -> bool:
    """The predicate every negative-pair generator applies: an exact same-person
    match (`is_possible_same_person`) or a typo duplicate (`is_probable_duplicate`)."""
    return is_possible_same_person(a, b) or is_probable_duplicate(a, b)


def _near_keys(text: str) -> Set[str]:
    """`text` and every one-character deletion of it: two strings within edit
    distance 1 always share at least one of these."""
    return {text} | {text[:i] + text[i + 1 :] for i in range(len(text))}


def _dob_block_keys(dob: str) -> Set[str]:
    keys = _near_keys(dob)
    if len(dob) == 10 and dob[4] == dob[7] == "-":
        keys.add(f"{dob[:4]}-{dob[8:10]}-{dob[5:7]}")  # month/day swap
    return keys


class ProbableDuplicateIndex:
    """Blocked lookup of every indexed patient that `is_probable_duplicate` would
    flag against a given record, without comparing it with every patient.

    `is_probable_duplicate` needs either SSNs within edit distance 1, or birth
    dates within edit distance 1 / a month-day swap (plus a shared phone or a
    near-identical name). Records sharing an SSN or birth-date block key are the
    only ones that can qualify, so only those are compared in full."""

    def __init__(self, patients: Iterable[Patient]) -> None:
        self._patients: Dict[str, Patient] = {}
        self._blocks: Dict[Tuple[str, str], List[str]] = defaultdict(list)
        for patient in patients:
            patient_id = patient.get("id")
            if patient_id is None:
                continue
            self._patients[patient_id] = patient
            for key in self._keys(patient):
                self._blocks[key].append(patient_id)

    @staticmethod
    def _keys(patient: Patient) -> Set[Tuple[str, str]]:
        keys: Set[Tuple[str, str]] = set()
        ssn = ssn_of(patient)
        if ssn is not None:
            keys |= {("ssn", k) for k in _near_keys(ssn)}
        dob = str(patient.get("birthDate") or "")
        if dob:
            keys |= {("dob", k) for k in _dob_block_keys(dob)}
        return keys

    def matching_ids(self, patient: Patient) -> Set[str]:
        """Ids of indexed patients that are probable duplicates of `patient`."""
        candidates: Set[str] = set()
        for key in self._keys(patient):
            candidates.update(self._blocks.get(key, ()))
        return {
            other_id
            for other_id in candidates
            if other_id != patient.get("id")
            and is_probable_duplicate(patient, self._patients[other_id])
        }


class SamePersonIndex:
    """O(1) lookup of every indexed patient id that could be the same person as
    a given record - the indexed equivalent of calling is_possible_same_person()
    against every patient."""

    def __init__(self, patients: Iterable[Patient]) -> None:
        self._by_ssn: Dict[str, List[str]] = defaultdict(list)
        self._by_key: Dict[Tuple[str, str, str], List[str]] = defaultdict(list)
        for patient in patients:
            patient_id = patient.get("id")
            if patient_id is None:
                continue
            ssn = ssn_of(patient)
            if ssn is not None:
                self._by_ssn[ssn].append(patient_id)
            key = identity_key(patient)
            if key is not None:
                self._by_key[key].append(patient_id)

    def matching_ids(self, patient: Patient) -> Set[str]:
        """Ids of indexed patients that could be `patient` (including its own id)."""
        found: Set[str] = set()
        ssn = ssn_of(patient)
        if ssn is not None:
            found.update(self._by_ssn.get(ssn, ()))
        key = identity_key(patient)
        if key is not None:
            found.update(self._by_key.get(key, ()))
        return found
