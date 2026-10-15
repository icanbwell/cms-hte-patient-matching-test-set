"""Structural FHIR R4 conformance checks for emitted Patient resources.

Pure Python, no dependency on the rest of the repo. This is a structural
floor (no empty values, bound code sets, typed SSN identifiers, unique ranks),
not a replacement for the official HL7 validator, which is run manually once
per release (session 16 design doc, Workstream 1).
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Iterator, List

Patient = Dict[str, Any]

SSN_SYSTEM = "http://hl7.org/fhir/sid/us-ssn"
V2_0203_SYSTEM = "http://terminology.hl7.org/CodeSystem/v2-0203"

NAME_USES = frozenset(
    {"usual", "official", "temp", "nickname", "anonymous", "old", "maiden"}
)
TELECOM_SYSTEMS = frozenset({"phone", "fax", "email", "pager", "url", "sms", "other"})

_EMPTY: tuple[str, List[Any], Dict[str, Any], None] = ("", [], {}, None)


def prune_empty(value: Any) -> Any:
    """A copy of `value` with "", [], {} and None removed recursively.

    0 and False are kept. FHIR forbids empty strings, arrays and objects, and
    some mutators leave them behind (e.g. ssn_dropped leaves identifier: [])."""
    if isinstance(value, dict):
        pruned = {key: prune_empty(item) for key, item in value.items()}
        return {key: item for key, item in pruned.items() if item not in _EMPTY}
    if isinstance(value, list):
        items = [prune_empty(item) for item in value]
        return [item for item in items if item not in _EMPTY]
    return value


def renumber_telecom_ranks(patient: Patient) -> Patient:
    """A copy of `patient` whose ranked telecom entries are renumbered 1..n per
    system in list order. Entries without a `rank` stay without one. Some
    mutators move or merge telecom entries and leave ranks stale or duplicated."""
    result = copy.deepcopy(patient)
    next_rank: Dict[str, int] = {}
    for contact in result.get("telecom") or []:
        if "rank" in contact:
            system = str(contact.get("system"))
            next_rank[system] = next_rank.get(system, 0) + 1
            contact["rank"] = next_rank[system]
    return result


def export_ready(patient: Patient) -> Patient:
    """The form of `patient` that is written to a release file."""
    return prune_empty(renumber_telecom_ranks(patient))


def is_noop_variant(original: Patient, variant: Patient) -> bool:
    """True when `variant` is indistinguishable from `original` in the form
    written to a release file (e.g. a mutation that only added an empty field
    that `prune_empty` then removes)."""
    return export_ready(variant) == export_ready(original)


def _empties(value: Any, path: str) -> Iterator[str]:
    if isinstance(value, dict):
        if not value and path:
            yield f"{path}: empty object"
        for key, item in value.items():
            yield from _empties(item, f"{path}.{key}" if path else key)
    elif isinstance(value, list):
        if not value:
            yield f"{path}: empty array"
        for index, item in enumerate(value):
            yield from _empties(item, f"{path}[{index}]")
    elif isinstance(value, str):
        if not value.strip():
            yield f"{path}: empty string"
    elif value is None:
        yield f"{path}: null"


def _has_coding(identifier: Dict[str, Any], code: str) -> bool:
    codings = (identifier.get("type") or {}).get("coding") or []
    return any(
        c.get("system") == V2_0203_SYSTEM and c.get("code") == code for c in codings
    )


def violations(patient: Patient) -> List[str]:
    """Human-readable conformance problems; an empty list means conformant."""
    found = list(_empties(patient, ""))
    for index, entry in enumerate(patient.get("name") or []):
        use = entry.get("use")
        if use is not None and use not in NAME_USES:
            found.append(f"name[{index}].use: {use!r} not in NameUse")
    ranks: Dict[str, List[Any]] = {}
    for index, contact in enumerate(patient.get("telecom") or []):
        system = contact.get("system")
        if system not in TELECOM_SYSTEMS:
            found.append(
                f"telecom[{index}].system: {system!r} not a ContactPointSystem"
            )
        if "^" in str(contact.get("value") or ""):
            found.append(f"telecom[{index}].value: contains '^'")
        if "rank" in contact:
            ranks.setdefault(str(system), []).append(contact["rank"])
    for system, values in ranks.items():
        if len(values) != len(set(values)):
            found.append(f"telecom: duplicate rank within system {system!r}")
    for index, identifier in enumerate(patient.get("identifier") or []):
        if identifier.get("system") == SSN_SYSTEM and not _has_coding(identifier, "SS"):
            found.append(f"identifier[{index}]: SSN identifier lacks type coding SS")
    return found
