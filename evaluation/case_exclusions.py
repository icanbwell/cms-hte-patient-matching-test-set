"""Case exclusions: true-match cases the benchmark must not contain.

A generated true-match (query, candidate) pair is *excluded* when a registered
``ExclusionRule`` says the CMS Table 2 spec cannot, by design, link it. Keeping
such a pair would make recall measure "the engine can't do what the spec
dropped", which reads as an engine regression when it is not.

Exclusion is applied at generation time (``labeled_pairs.generate_raw_pairs``
and ``population_cases.build_population_dataset``), so regenerating the files
reproduces the exclusion with no hand edit. Only true matches are ever
excluded; negatives are never touched.

Adding a new exclusion
----------------------
1. Write a predicate ``(query, candidate) -> bool`` that is True for a pair to
   drop. Keep it as narrow as the spec change it encodes: a pair the spec
   still links, or that fails for an unrelated reason, must stay.
2. Register it in ``DEFAULT_RULES`` as an ``ExclusionRule`` with a stable
   ``name`` and a ``reason`` that cites the spec change.
3. Add a test in ``test_case_exclusions.py`` covering a pair it drops and the
   nearest pair it must keep.
4. Note the new rule and its counts in ``evaluation/cases/README.md``'s dataset
   changelog; removing pairs changes row counts, so consumers re-pin.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Dict, Set, Tuple

from mutations import get_nick_namer

Patient = Dict[str, Any]
Predicate = Callable[[Patient, Patient], bool]

# CMS Table 2 constrained fuzzy matching: Damerau-Levenshtein distance <= 1 and
# both strings >= 5 characters; DOB uses a +/-1 calendar-day tolerance instead.
MIN_FUZZY_LENGTH = 5
DOB_TOLERANCE_DAYS = 1


@dataclass(frozen=True)
class ExclusionRule:
    """A named reason to drop a true-match pair.

    Attributes:
        name: Stable identifier, used as the key in exclusion counts.
        reason: One line naming the spec change that makes the pair unmatchable.
        applies: True when the (query, candidate) true-match pair is dropped.
    """

    name: str
    reason: str
    applies: Predicate


# --------------------------------------------------------------------------
# Field helpers (normalized value sets, mirroring the matching engine's
# "any known value satisfies the field" semantics)
# --------------------------------------------------------------------------
# Letters NFKD leaves intact; the engine's unidecode transliterates them.
_TRANSLITERATE = str.maketrans(
    {"Ø": "O", "Ł": "L", "Đ": "D", "Æ": "AE", "Œ": "OE", "ß": "SS", "Þ": "TH"}
)


def _normalize_name(value: str) -> str:
    """Upper-case, fold diacritics and drop punctuation and all whitespace,
    approximating the engine's ``normalize_text`` (which uses unidecode)."""
    folded = value.upper().translate(_TRANSLITERATE)
    decomposed = unicodedata.normalize("NFKD", folded)
    letters = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^A-Z0-9]", "", letters)


def _names(patient: Patient, key: str) -> Set[str]:
    values: Set[str] = set()
    for entry in patient.get("name") or []:
        raw = entry.get(key)
        for v in raw if isinstance(raw, list) else [raw]:
            if v:
                normalized = _normalize_name(str(v))
                if normalized:
                    values.add(normalized)
    return values


def _phones(patient: Patient) -> Set[str]:
    """Usable phone numbers: 10-digit NANP shape (optional leading 1), not all
    one digit. The engine drops placeholder and invalid numbers before
    matching, so two such values must not count as a shared phone."""
    out: Set[str] = set()
    for t in patient.get("telecom") or []:
        if t.get("system") != "phone":
            continue
        digits = re.sub(r"\D", "", t.get("value") or "")
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if (
            len(digits) == 10
            and digits[0] in "23456789"
            and digits[3] in "23456789"
            and len(set(digits)) > 1
        ):
            out.add(digits)
    return out


def _zips(patient: Patient) -> Set[str]:
    """Postal codes as the engine compares them: digits only, ZIP+4 kept as
    XXXXX-XXXX, so 10001-1111 does not equal 10001-2222 or 10001."""
    out: Set[str] = set()
    for a in patient.get("address") or []:
        digits = re.sub(r"[^\d]", "", str(a.get("postalCode") or ""))
        if len(digits) == 9:
            out.add(f"{digits[:5]}-{digits[5:]}")
        elif digits:
            out.add(digits)
    return out


def _damerau(a: str, b: str) -> int:
    """Optimal-string-alignment (adjacent transposition = 1) edit distance."""
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


def _fuzzy_equal(query: Set[str], candidate: Set[str]) -> bool:
    if query & candidate:
        return True
    return any(
        len(q) >= MIN_FUZZY_LENGTH
        and len(c) >= MIN_FUZZY_LENGTH
        and _damerau(q, c) <= 1
        for q in query
        for c in candidate
    )


def _dob_within_tolerance(query: Patient, candidate: Patient) -> bool:
    """True when any Table 2 DOB comparison could succeed: both dates parse
    and differ by at most one day. A missing or malformed DOB fails closed, as
    it does in the engine, so it never satisfies a DOB-requiring rule."""
    try:
        q = date.fromisoformat(query.get("birthDate") or "")
        c = date.fromisoformat(candidate.get("birthDate") or "")
    except ValueError:
        return False
    return abs((q - c).days) <= DOB_TOLERANCE_DAYS


_SSN_SYSTEM = "http://hl7.org/fhir/sid/us-ssn"
_ITIN_SYSTEM = "urn:oid:2.16.840.1.113883.4.4"
_MBI_SYSTEM = "http://hl7.org/fhir/sid/us-mbi"
_NAMESPACE_CODES = {"RI", "MR", "AN", "PI"}


def _emails(patient: Patient) -> Set[str]:
    return {
        str(t["value"]).strip().lower()
        for t in patient.get("telecom") or []
        if t.get("system") == "email" and t.get("value")
    }


def _identifiers(patient: Patient) -> Dict[str, Set[str]]:
    """Identifier values by kind, following the engine's identifier extraction
    (SSN/ITIN keep only the last four digits; legal, member and namespace ids
    are scoped by assigner or system)."""
    out: Dict[str, Set[str]] = {
        k: set() for k in ("ssn4", "itin4", "mbi", "legal", "member", "namespace")
    }
    for ident in patient.get("identifier") or []:
        system = ident.get("system") or ""
        value = ident.get("value") or ""
        if not value:
            continue
        codes = {
            c.get("code") or "" for c in (ident.get("type") or {}).get("coding") or []
        }
        if system in (_SSN_SYSTEM, _ITIN_SYSTEM):
            last4 = value.replace("-", "").replace(" ", "")[-4:]
            if len(last4) == 4:
                out["ssn4" if system == _SSN_SYSTEM else "itin4"].add(last4)
        elif system == _MBI_SYSTEM:
            out["mbi"].add(value)
        elif "DL" in codes:
            assigner = (ident.get("assigner") or {}).get("display") or ""
            out["legal"].add(f"{assigner}|{value}" if assigner else value)
        elif "MB" in codes:
            if system:
                out["member"].add(f"{system}|{value}")
        elif "SN" in codes or codes & {"CMS-GRDN", "CMS-MTHR", "CMS-BEID"}:
            continue  # not used by any DOB-free flat rule
        elif codes & _NAMESPACE_CODES:
            out["namespace"].add(f"{system}|{value}" if system else value)
        elif system:
            out["namespace"].add(f"{system}|{value}")
    return out


def _first_names_with_nicknames(patient: Patient) -> Set[str]:
    """Given names plus nicknames of each name entry's primary (first) given
    name, which is all the engine's normalizer attaches."""
    names = _names(patient, "given")
    namer = get_nick_namer()
    for entry in patient.get("name") or []:
        given = entry.get("given") or []
        primary = _normalize_name(str(given[0])) if given and given[0] else ""
        if primary:
            names |= {
                _normalize_name(n) for n in namer.nicknames_of(primary.lower()) if n
            }
    return names


def _fields(patient: Patient) -> Dict[str, Set[str]]:
    return {
        "first": _first_names_with_nicknames(patient),
        "phone": _phones(patient),
        "email": _emails(patient),
        **_identifiers(patient),
    }


# The Category 1 rules that do not use DOB, as tuples of the field keys above
# that must each match exactly (CMS Table 2 rules 13-22, 25, 26).
_DOB_FREE_RULES: Tuple[Tuple[str, ...], ...] = (
    ("first", "phone", "ssn4"),
    ("first", "phone", "itin4"),
    ("first", "email", "ssn4"),
    ("first", "email", "itin4"),
    ("phone", "mbi"),
    ("phone", "legal"),
    ("email", "mbi"),
    ("email", "legal"),
    ("legal", "mbi"),
    ("namespace",),
    ("phone", "member"),
    ("email", "member"),
)


def _matches_a_dob_free_rule(query: Patient, candidate: Patient) -> bool:
    q, c = _fields(query), _fields(candidate)
    return any(all(q[k] & c[k] for k in rule) for rule in _DOB_FREE_RULES)


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------
def only_matchable_by_removed_rule_29(query: Patient, candidate: Patient) -> bool:
    """True when the pair satisfies removed rule 29 and no remaining rule can
    link it.

    Rule 29 was ``First Name* + Last Name* + Phone + ZIP`` (no DOB; names fuzzy,
    at most two fuzzy fields). Only pairs whose DOB is outside +/-1 day are
    considered: for those, every DOB-using rule fails, so the pair is dropped
    unless one of the 12 DOB-free rules (13-22, 25, 26) still links it. A pair
    with a DOB inside the tolerance is always kept, even if only rule 29 would
    have linked it, because a rule that needs a DOB and one more differing
    field is not decidable here. A pair that also differs in phone or ZIP never
    matched rule 29 and is kept.
    """
    if _dob_within_tolerance(query, candidate):
        return False
    first_match = _fuzzy_equal(
        _first_names_with_nicknames(query), _first_names_with_nicknames(candidate)
    )
    if not first_match:
        return False
    if not _fuzzy_equal(_names(query, "family"), _names(candidate, "family")):
        return False
    if not _phones(query) & _phones(candidate):
        return False
    if not _zips(query) & _zips(candidate):
        return False
    return not _matches_a_dob_free_rule(query, candidate)


RULE_29_REMOVED = ExclusionRule(
    name="rule_29_removed",
    reason=(
        "CMS removed Table 2 rule 29 (First Name* + Last Name* + Phone + ZIP, no "
        "DOB); with a DOB outside +/-1 day no remaining rule can link the pair"
    ),
    applies=only_matchable_by_removed_rule_29,
)

DEFAULT_RULES: Tuple[ExclusionRule, ...] = (RULE_29_REMOVED,)


# --------------------------------------------------------------------------
# Policy
# --------------------------------------------------------------------------
@dataclass
class ExclusionPolicy:
    """The active exclusion rules plus a running count of what each dropped.

    Generators call ``excludes`` for every true-match pair they are about to
    emit. ``counts`` is keyed by rule name so an export can report exactly what
    was removed.
    """

    rules: Tuple[ExclusionRule, ...] = DEFAULT_RULES
    counts: Counter = field(default_factory=Counter)

    def excludes(self, query: Patient, candidate: Patient) -> bool:
        for rule in self.rules:
            if rule.applies(query, candidate):
                self.counts[rule.name] += 1
                return True
        return False

    def summary(self) -> str:
        if not self.counts:
            return "no pairs excluded"
        return ", ".join(f"{name}={n}" for name, n in sorted(self.counts.items()))


def no_exclusions() -> ExclusionPolicy:
    """A policy that drops nothing, for tests or an unfiltered export."""
    return ExclusionPolicy(rules=())
