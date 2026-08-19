"""Special-population non-match pairs: the Google Doc's Section 2 named list of
high-risk populations (twins, shelters, nursing facilities, correctional
institutions, hotels/short-term housing, halfway houses, dormitories, group
homes, migrant camps, multi-generational households) beyond hard_negatives.py's
general shared-ZIP+DOB proxy.

Coincidental vs. constructed sharing:
  - mine_shared_surname_household_negatives() MINES real, already-coincidentally
    colliding ONC pairs (same postal code + family name, generational DOB gap) -
    the same "genuinely distinct records" discipline hard_negatives.py already
    established. This is the "multi-generational households" category.
  - construct_institutional_negatives() CONSTRUCTS the collision: ONC has no
    column marking a record as "resident of a shelter/nursing facility/etc.", so
    there are no naturally-occurring examples to mine. This function takes
    already mutually-distinct real ONC identities (different family name,
    different ID - the same identities are never fabricated) and overwrites
    only their address with one of a small, unambiguously-synthetic catalog of
    per-institution-type addresses (INSTITUTIONAL_ADDRESSES), then pairs them.
    The label (true non-match) is still correct because the underlying people
    really are distinct ONC records; only the address they're said to share is
    fabricated, and it's fabricated specifically to be recognizable as such
    (a "SYNTHETIC TEST ADDRESS" line, a reserved 00001-00008 ZIP block).

Literal twins (identical first name + last name + DOB + address) are
deliberately NOT constructed here - the CMS spec itself (SS IV.G) acknowledges
this exact case as unresolvable through field matching alone, so it is not a
"should not match" test case; see docs/sessions/pending/session_10.md's
"Out of scope".

Data-source scope: this module only mines or relabels real ONC records (Doc
Section 1's Option A) plus a small fabricated address catalog (Option B) - no
real de-identified company data (Option C) is used anywhere here.
"""

from __future__ import annotations

import copy
import random
from collections import defaultdict
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Tuple

from hard_negatives import HardNegativeCandidate

Patient = Dict[str, Any]

INSTITUTION_TYPES: Tuple[str, ...] = (
    "shelter",
    "nursing_facility",
    "correctional_institution",
    "hotel_short_term_housing",
    "halfway_house",
    "dormitory",
    "group_home",
    "migrant_camp",
)

# Reserved 000xx ZIP block (never a real USPS-assigned ZIP) plus an explicit
# "SYNTHETIC TEST ADDRESS" line prefix, so a reviewer or downstream consumer of
# this module's output can recognize a fabricated address at a glance, per the
# Doc's Design Principle 4 ("every fabricated identifier value should be
# unambiguously marked as synthetic").
INSTITUTIONAL_ADDRESSES: Dict[str, Dict[str, str]] = {
    "shelter": {
        "line": "SYNTHETIC TEST ADDRESS - 100 SHELTER WAY",
        "city": "TESTCITY",
        "state": "ZZ",
        "postalCode": "00001",
    },
    "nursing_facility": {
        "line": "SYNTHETIC TEST ADDRESS - 200 NURSING FACILITY DR",
        "city": "TESTCITY",
        "state": "ZZ",
        "postalCode": "00002",
    },
    "correctional_institution": {
        "line": "SYNTHETIC TEST ADDRESS - 300 CORRECTIONAL INSTITUTION RD",
        "city": "TESTCITY",
        "state": "ZZ",
        "postalCode": "00003",
    },
    "hotel_short_term_housing": {
        "line": "SYNTHETIC TEST ADDRESS - 400 SHORT TERM HOUSING BLVD",
        "city": "TESTCITY",
        "state": "ZZ",
        "postalCode": "00004",
    },
    "halfway_house": {
        "line": "SYNTHETIC TEST ADDRESS - 500 HALFWAY HOUSE LN",
        "city": "TESTCITY",
        "state": "ZZ",
        "postalCode": "00005",
    },
    "dormitory": {
        "line": "SYNTHETIC TEST ADDRESS - 600 DORMITORY HALL",
        "city": "TESTCITY",
        "state": "ZZ",
        "postalCode": "00006",
    },
    "group_home": {
        "line": "SYNTHETIC TEST ADDRESS - 700 GROUP HOME CT",
        "city": "TESTCITY",
        "state": "ZZ",
        "postalCode": "00007",
    },
    "migrant_camp": {
        "line": "SYNTHETIC TEST ADDRESS - 800 MIGRANT CAMP RD",
        "city": "TESTCITY",
        "state": "ZZ",
        "postalCode": "00008",
    },
}


def _primary_family_name(patient: Patient) -> str:
    names = patient.get("name") or []
    return str(names[0].get("family") or "") if names else ""


def _postal_code(patient: Patient) -> str:
    addresses = patient.get("address") or []
    return str(addresses[0].get("postalCode") or "") if addresses else ""


def _rng(rng: Optional[random.Random]) -> random.Random:
    return rng if rng is not None else random.Random()


def _with_synthetic_address(patient: Patient, institution_type: str) -> Patient:
    if institution_type not in INSTITUTIONAL_ADDRESSES:
        raise ValueError(f"Unknown institution_type: {institution_type!r}")
    patient = copy.deepcopy(patient)
    addr = INSTITUTIONAL_ADDRESSES[institution_type]
    patient["address"] = [
        {
            "line": [addr["line"]],
            "city": addr["city"],
            "state": addr["state"],
            "postalCode": addr["postalCode"],
        }
    ]
    return patient


def construct_institutional_negatives(
    patients: Iterable[Patient],
    institution_type: str,
    *,
    group_size: int = 3,
    rng: Optional[random.Random] = None,
) -> List[HardNegativeCandidate]:
    """Pair up `group_size` distinct, real ONC identities (different family
    name, different ID) at a single fabricated, unambiguously-synthetic
    address for `institution_type`, and return every pairwise combination
    within the group as a true-non-match candidate.

    Only the address is fabricated - the underlying identities are genuinely
    distinct ONC records, so the true-non-match label remains correct. See
    this module's docstring for why this differs from mining (no ONC record is
    naturally tagged as e.g. a shelter resident, so there is nothing to mine).
    """
    if institution_type not in INSTITUTIONAL_ADDRESSES:
        raise ValueError(f"Unknown institution_type: {institution_type!r}")
    rng = _rng(rng)
    pool = list(patients)
    rng.shuffle(pool)

    group: List[Patient] = []
    seen_family_names: set[str] = set()
    for patient in pool:
        family = _primary_family_name(patient).upper()
        if not family or family in seen_family_names:
            continue
        seen_family_names.add(family)
        group.append(_with_synthetic_address(patient, institution_type))
        if len(group) == group_size:
            break

    candidates: List[HardNegativeCandidate] = []
    for i in range(len(group)):
        for j in range(i + 1, len(group)):
            candidates.append(
                HardNegativeCandidate(
                    query=group[i],
                    candidate=group[j],
                    shared_fields={
                        "institution_type": institution_type,
                        "postalCode": INSTITUTIONAL_ADDRESSES[institution_type]["postalCode"],
                    },
                )
            )
    return candidates


def mine_shared_surname_household_negatives(
    patients: Iterable[Patient],
    *,
    min_age_gap_years: int = 15,
) -> List[HardNegativeCandidate]:
    """Mine real ONC pairs sharing a postal code AND family name, but with
    birth years far enough apart to represent a parent/child pair rather than
    the same person or a twin - the Doc's "multi-generational households"
    category.

    Deliberately the inverse filter from hard_negatives.py's
    mine_shared_address_hard_negatives() (which *excludes* same-family-name
    pairs to stay disjoint from mutation-style variants of one identity): here
    the shared family name is exactly the signal this category is testing.
    The min_age_gap_years requirement is what keeps this disjoint from a twin
    or fuzzy-variant scenario (same family name + near-identical DOB would be
    those cases instead, not this one).
    """
    buckets: Dict[Tuple[str, str], List[Patient]] = defaultdict(list)
    for patient in patients:
        zip_code = _postal_code(patient)
        family = _primary_family_name(patient).upper()
        if not zip_code or not family:
            continue
        buckets[(zip_code, family)].append(patient)

    candidates: List[HardNegativeCandidate] = []
    for (zip_code, family), group in buckets.items():
        if len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                dob_a, dob_b = a.get("birthDate"), b.get("birthDate")
                if a.get("id") == b.get("id") or not dob_a or not dob_b:
                    continue
                try:
                    gap_years = abs(date.fromisoformat(dob_a).year - date.fromisoformat(dob_b).year)
                except ValueError:
                    continue
                if gap_years < min_age_gap_years:
                    continue
                candidates.append(
                    HardNegativeCandidate(
                        query=a,
                        candidate=b,
                        shared_fields={
                            "postalCode": zip_code,
                            "family_name": family,
                            "age_gap_years": str(gap_years),
                        },
                    )
                )
    return candidates
