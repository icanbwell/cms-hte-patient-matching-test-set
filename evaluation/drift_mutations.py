"""True-match drift mutators (session 15, Workstream B).

Each function returns `(variant, subtype)`, or None when the scenario cannot
apply to this patient (missing field, no usable donor value). New values come
from `donors`: real ONC records held out of the generated set, so no
identifier is fabricated. Donors are distinct records, but a donated value can
coincidentally equal a value held by an in-set patient. Inputs are never
mutated.
"""

from __future__ import annotations

import copy
import random
from typing import Any, Dict, List, Sequence, Tuple

from identity_guard import normalize_phone, normalize_token
from mutations import generate_fuzzy_variant

Patient = Dict[str, Any]
Result = Tuple[Patient, str] | None

GENDER_DRIFT: Dict[str, Tuple[str, ...]] = {
    "male": ("female", "unknown"),
    "female": ("male", "unknown"),
    "unknown": ("male", "female"),
}


def _family_tokens(patient: Patient) -> set[str]:
    return {normalize_token(n.get("family")) for n in patient.get("name") or []}


def _street(address: Dict[str, Any]) -> str:
    lines = address.get("line") or []
    street = normalize_token(lines[0]) if lines else ""
    zip_code = normalize_token(address.get("postalCode"))
    return f"{street}|{zip_code}" if street and zip_code else ""


def surname_change_variant(
    patient: Patient, donors: Sequence[Patient], rng: random.Random
) -> Result:
    """A name change (e.g. marriage) whose new surname is NOT present anywhere
    on `patient`, so it cannot be recovered from a stored prior-name entry.
    Subtypes: no_history (new surname only), prior_name_on_target (the old
    surname kept as a `use: maiden` entry), hyphenated (old-new)."""
    names = patient.get("name") or []
    prior = str(names[0].get("family") or "") if names else ""
    if not prior:
        return None
    existing = _family_tokens(patient)
    options = sorted(
        {
            str(d["name"][0]["family"])
            for d in donors
            if d.get("name")
            and d["name"][0].get("family")
            and normalize_token(d["name"][0]["family"]) not in existing
        }
    )
    if not options:
        return None
    new = rng.choice(options)
    subtype = rng.choice(["no_history", "prior_name_on_target", "hyphenated"])
    base = {k: v for k, v in names[0].items() if k != "family"}
    variant = copy.deepcopy(patient)
    if subtype == "no_history":
        variant["name"] = [{**copy.deepcopy(base), "family": new}]
    elif subtype == "prior_name_on_target":
        variant["name"] = [
            {**copy.deepcopy(base), "family": new},
            {**copy.deepcopy(base), "family": prior, "use": "maiden"},
        ]
    else:
        variant["name"] = [{**copy.deepcopy(base), "family": f"{prior}-{new}"}]
    return variant, subtype


def address_move_variant(
    patient: Patient, donors: Sequence[Patient], rng: random.Random
) -> Result:
    """A move: the other system holds a different, real address. Subtypes:
    current_vs_prior (target carries only the new address) and
    history_on_one_side (target carries the new address as `home` and the old
    one as `old`). Prefers a same-state donor address. No dates are invented."""
    addresses = patient.get("address") or []
    if not addresses or not _street(addresses[0]):
        return None
    old = addresses[0]
    donated = [
        d["address"][0]
        for d in donors
        if d.get("address")
        and _street(d["address"][0])
        and _street(d["address"][0]) != _street(old)
    ]
    same_state = [a for a in donated if a.get("state") == old.get("state")]
    pool = same_state or donated
    if not pool:
        return None
    new = copy.deepcopy(rng.choice(sorted(pool, key=_street)))
    subtype = rng.choice(["current_vs_prior", "history_on_one_side"])
    variant = copy.deepcopy(patient)
    if subtype == "current_vs_prior":
        variant["address"] = [new]
    else:
        variant["address"] = [
            {**new, "use": "home"},
            {**copy.deepcopy(old), "use": "old"},
        ]
    return variant, subtype


def _normalize_contact(system: str, value: object) -> str:
    return (
        normalize_phone(value)
        if system == "phone"
        else str(value or "").strip().casefold()
    )


def _contact_churn(
    patient: Patient, donors: Sequence[Patient], rng: random.Random, system: str
) -> Result:
    telecom = patient.get("telecom") or []
    own: List[int] = [i for i, t in enumerate(telecom) if t.get("system") == system]
    own_values = {_normalize_contact(system, telecom[i].get("value")) for i in own}
    donated = sorted(
        {
            str(t["value"])
            for d in donors
            for t in d.get("telecom") or []
            if t.get("system") == system
            and t.get("value")
            and _normalize_contact(system, t["value"]) not in own_values
        }
    )
    subtype = rng.choice(["replaced", "dropped"]) if own else "added"
    if subtype == "replaced" and not donated:
        subtype = "dropped"
    variant = copy.deepcopy(patient)
    new_telecom = variant.setdefault("telecom", [])
    if subtype == "dropped":
        del new_telecom[own[0]]
    else:
        if not donated:
            return None
        entry = {"system": system, "value": rng.choice(donated)}
        if subtype == "replaced":
            new_telecom[own[0]] = entry
        else:
            new_telecom.append(entry)
    return variant, subtype


def phone_churn_variant(
    patient: Patient, donors: Sequence[Patient], rng: random.Random
) -> Result:
    """Contact churn on phone: replaced (a donor's number), dropped (first
    number removed) or added (patient had none). Unlike session 14's
    phone_variant it does not need a PHONE2 value."""
    return _contact_churn(patient, donors, rng, "phone")


def email_churn_variant(
    patient: Patient, donors: Sequence[Patient], rng: random.Random
) -> Result:
    """Contact churn on email; same subtypes as phone_churn_variant."""
    return _contact_churn(patient, donors, rng, "email")


def gender_drift_variant(patient: Patient, rng: random.Random) -> Result:
    """Administrative-sex disagreement, composed with one fuzzy edit so gender
    is not the only differing field. Subtype is "<from>_to_<to>"."""
    current = str(patient.get("gender") or "unknown")
    if current not in GENDER_DRIFT:
        return None
    new = rng.choice(GENDER_DRIFT[current])
    drifted = copy.deepcopy(patient)
    drifted["gender"] = new
    variant, _ = generate_fuzzy_variant(drifted, rng=rng)
    return variant, f"{current}_to_{new}"
