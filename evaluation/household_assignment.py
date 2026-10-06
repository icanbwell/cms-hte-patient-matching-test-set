"""Household assignment for the "realistic" dataset (session 15, Workstream C).

ONC addresses are near-unique per record (about 1.03 patients per address,
against roughly 2.5 people per U.S. household), and contact values are
near-unique too. `assign_households` groups a sampled population into
households whose size distribution follows population_targets.py, gives every
household member the anchor adult's real address, and optionally shares the
anchor's phone and email with members. Identities (names, birth dates, SSNs,
ids) are never changed, except that children under 13 may lose their SSN
(a profile rate: young children often have none on file).

What this does and does not model:

- Most households are unrelated real records placed at one address
  (roommates, blended families whose surnames differ). A child is attached to
  an adult with the same surname when one is available, otherwise to any
  household with a free slot. The report counts the same-surname placements.
- Children under 13 ALWAYS carry the anchor adult's phone and email.
- The shape of the multi-person size distribution is an assumption: sizes 2-6
  with geometrically decaying weights, solved so the overall mean equals the
  target. The cited sources fix only the one-person share and the mean.

Deterministic for a seed; inputs are never mutated.
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List

from drift_profile import DriftProfile
from identity_guard import SSN_SYSTEM, normalize_phone, normalize_token
from population_sampling import age_of
from population_targets import (
    AS_OF,
    MEAN_HOUSEHOLD_SIZE,
    SINGLE_PERSON_HOUSEHOLD_SHARE,
)

Patient = Dict[str, Any]

MAX_HOUSEHOLD_SIZE = 6
UNDER_13 = 13
ADULT = 18
MIN_PARENT_AGE_GAP = 18


@dataclass(frozen=True)
class HouseholdReport:
    n_households: int
    mean_size: float
    n_minors: int
    n_same_surname_minors: int


@dataclass(frozen=True)
class HouseholdResult:
    patients: List[Patient]
    households: List[List[str]]
    report: HouseholdReport


def _multi_person_weights(mean_multi: float) -> List[float]:
    """Weights for sizes 2..6, geometric with ratio r chosen so the mean is `mean_multi`."""
    sizes = list(range(2, MAX_HOUSEHOLD_SIZE + 1))
    if not 2.0 < mean_multi < float(MAX_HOUSEHOLD_SIZE):
        raise ValueError(
            f"mean size of multi-person households must be in (2, {MAX_HOUSEHOLD_SIZE}), "
            f"got {mean_multi:.3f}"
        )

    def mean_for(ratio: float) -> float:
        weights = [ratio ** (size - 2) for size in sizes]
        return sum(s * w for s, w in zip(sizes, weights)) / sum(weights)

    low, high = 1e-9, 1e6
    for _ in range(200):
        mid = (low * high) ** 0.5
        if mean_for(mid) < mean_multi:
            low = mid
        else:
            high = mid
    ratio = (low * high) ** 0.5
    weights = [ratio ** (size - 2) for size in sizes]
    total = sum(weights)
    return [w / total for w in weights]


def household_sizes(
    n_patients: int,
    *,
    single_share: float,
    mean_size: float,
    rng: random.Random,
) -> List[int]:
    """Household sizes summing to exactly `n_patients`, shuffled."""
    if n_patients < 0:
        raise ValueError("n_patients must be >= 0")
    mean_multi = (mean_size - single_share) / (1.0 - single_share)
    multi_weights = _multi_person_weights(mean_multi)
    multi_sizes = list(range(2, MAX_HOUSEHOLD_SIZE + 1))
    sizes: List[int] = []
    remaining = n_patients
    while remaining > 0:
        if rng.random() < single_share:
            size = 1
        else:
            size = rng.choices(multi_sizes, weights=multi_weights)[0]
        size = min(size, remaining)
        sizes.append(size)
        remaining -= size
    return sizes


def _family(patient: Patient) -> str:
    names = patient.get("name") or []
    return normalize_token(names[0].get("family")) if names else ""


def _entries(patient: Patient, system: str) -> List[Dict[str, Any]]:
    return [t for t in patient.get("telecom") or [] if t.get("system") == system]


def _share_contact(
    member: Patient, anchor: Patient, system: str, *, replace_all: bool
) -> None:
    """Give `member` the anchor's `system` contact (first entry, or all of them)."""
    shared = _entries(anchor, system)
    if not shared:
        return
    kept = [t for t in member.get("telecom") or [] if t.get("system") != system]
    taken = shared if replace_all else shared[:1]
    member["telecom"] = kept + copy.deepcopy(taken)


def _drop_ssn(patient: Patient) -> None:
    patient["identifier"] = [
        i for i in patient.get("identifier") or [] if i.get("system") != SSN_SYSTEM
    ]


def shared_contact_case(a: Patient, b: Patient) -> str:
    """ "shared_contact" if the two records hold a normalized phone or email in
    common, else "same_address"."""

    def contacts(patient: Patient) -> set[str]:
        values = set()
        for entry in patient.get("telecom") or []:
            if entry.get("system") == "phone" and entry.get("value"):
                values.add("p:" + normalize_phone(entry["value"]))
            elif entry.get("system") == "email" and entry.get("value"):
                values.add("e:" + str(entry["value"]).strip().casefold())
        return values

    return "shared_contact" if contacts(a) & contacts(b) else "same_address"


def assign_households(
    patients: List[Patient],
    *,
    profile: DriftProfile | None = None,
    seed: int = 0,
    as_of: date = AS_OF,
    single_share: float = SINGLE_PERSON_HOUSEHOLD_SHARE.value,
    mean_size: float = MEAN_HOUSEHOLD_SIZE.value,
) -> HouseholdResult:
    profile = profile or DriftProfile()
    rng = random.Random(f"{seed}:households")
    people = copy.deepcopy(patients)
    ages = [age_of(p, as_of) for p in people]
    minors = [i for i, a in enumerate(ages) if a is not None and a < ADULT]
    adults = [i for i, a in enumerate(ages) if a is None or a >= ADULT]

    sizes = household_sizes(
        len(people), single_share=single_share, mean_size=mean_size, rng=rng
    )
    if len(adults) < len(sizes) or len(minors) > sum(s - 1 for s in sizes):
        raise ValueError(
            f"cannot house {len(minors)} minors and {len(adults)} adults in "
            f"{len(sizes)} households of mean size {len(people) / max(len(sizes), 1):.2f}"
        )

    rng.shuffle(adults)
    anchors = adults[: len(sizes)]
    spare_adults = adults[len(sizes) :]
    members: List[List[int]] = [[a] for a in anchors]
    free = [size - 1 for size in sizes]

    same_surname = 0
    order = list(minors)
    rng.shuffle(order)
    for minor in order:
        family = _family(people[minor])
        candidates = [h for h in range(len(sizes)) if free[h] > 0]
        matched = [
            h
            for h in candidates
            if family
            and _family(people[anchors[h]]) == family
            and (ages[anchors[h]] or 0) - (ages[minor] or 0) >= MIN_PARENT_AGE_GAP
        ]
        household = rng.choice(matched or candidates)
        same_surname += bool(matched)
        members[household].append(minor)
        free[household] -= 1
    for household in range(len(sizes)):
        while free[household] > 0:
            members[household].append(spare_adults.pop())
            free[household] -= 1

    ssn_absent = profile.rate("minor_ssn_absent")
    shared_phone = profile.rate("household_shared_phone")
    shared_email = profile.rate("household_shared_email")
    for household, indexes in enumerate(members):
        anchor = people[indexes[0]]
        for index in indexes[1:]:
            member = people[index]
            if anchor.get("address"):
                member["address"] = copy.deepcopy(anchor["address"])
            under_13 = ages[index] is not None and (ages[index] or 0) < UNDER_13
            if under_13:
                _share_contact(member, anchor, "phone", replace_all=True)
                _share_contact(member, anchor, "email", replace_all=True)
            else:
                if rng.random() < shared_phone:
                    _share_contact(member, anchor, "phone", replace_all=False)
                if rng.random() < shared_email:
                    _share_contact(member, anchor, "email", replace_all=False)
    for index in minors:
        if (ages[index] or 0) < UNDER_13 and rng.random() < ssn_absent:
            _drop_ssn(people[index])

    report = HouseholdReport(
        n_households=len(sizes),
        mean_size=len(people) / len(sizes) if sizes else 0.0,
        n_minors=len(minors),
        n_same_surname_minors=same_surname,
    )
    return HouseholdResult(
        patients=people,
        households=[[people[i]["id"] for i in indexes] for indexes in members],
        report=report,
    )
