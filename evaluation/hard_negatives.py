"""Mining real, distinct-record hard-negative pairs from the ONC dataset.

A "hard negative" here means two *genuinely different* people (distinct
EnterpriseIDs) whose records nonetheless collide on several high-signal
fields - the Google Doc's ("Proposal: A Shared Test Dataset for CMS v3.3.0
Patient Matching Compliance") Section 2 "distinct individuals sharing an
address" special-population category, and the closest available proxy for it
in the ONC dataset's field set (it has no household/family-relationship
column).

This is deliberately NOT the mutations.py approach applied to negative pairs:
mutating a record and asserting the result is "a different person" would only
be testing whether a matcher's fuzzy tolerance is *too* generous - a
statement about the algorithm, not about reality. A genuine hard negative
requires two records that were never derived from each other. See
SYNTHETIC_DATA_COMPARISON.md for the full discussion (this distinction was
raised directly during design, 2026-08-14 internal chat).

Caveat - read before treating this module's output as ground truth: it
assumes distinct EnterpriseIDs in the ONC dataset denote distinct people.
Direct inspection of the dataset (flat, alphabetically-sharded CSVs, one row
per EnterpriseID, no duplicate-cluster column) and of a prior internal
self-match test suite (a self-match-only design that never relied on this
assumption - it only checks whether each record's top match is itself) turned
up nothing in this repo corroborating - or refuting - the claim made in the
Google Doc's Section 4, that datasets "like" the ONC Challenge dataset
intentionally contain multiple records for the same synthetic person under
different IDs. Treat pairs mined here as hard-negative *candidates* pending
independent verification of that claim against ONC's own published
methodology, not as confirmed ground truth. See SYNTHETIC_DATA_COMPARISON.md
(session 12 resolves this for this repo's specific vendored dataset copy).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Tuple

Patient = Dict[str, Any]


@dataclass(frozen=True)
class HardNegativeCandidate:
    """One mined pair, plus which fields collided (the blocking key) so a
    reviewer can see why the pair was surfaced."""

    query: Patient
    candidate: Patient
    shared_fields: Mapping[str, str]


def _primary_family_name(patient: Patient) -> str:
    names = patient.get("name") or []
    return str(names[0].get("family") or "") if names else ""


def _postal_code(patient: Patient) -> str:
    addresses = patient.get("address") or []
    return str(addresses[0].get("postalCode") or "") if addresses else ""


def mine_shared_address_hard_negatives(
    patients: Iterable[Patient],
) -> List[HardNegativeCandidate]:
    """Pairs of distinct-ID patients sharing a postal code and date of birth,
    but with a genuinely different primary family name.

    Sharing a ZIP + DOB is coincidence-adjacent enough to stress-test a
    matcher's non-match boundary; requiring a *different* family name (rather
    than just a different ID) rules out the trivial case of two records that
    are actually mutations.py-style variants of one underlying identity,
    keeping this module's output disjoint from that one's.

    Blocking by (postalCode, birthDate) is O(n) rather than O(n^2): each
    patient is placed in exactly one bucket, and only within-bucket pairs
    (a small fraction of the full population) are ever compared. The `n`
    itself is the caller's responsibility, though - this function assumes
    `patients` is already a reasonably-sized, already-in-memory list. See
    SYNTHETIC_DATA_SETUP.md's "Memory & scale" section before passing it the
    full ~1,000,000-record ONC dataset at once.
    """
    buckets: Dict[Tuple[str, str], List[Patient]] = defaultdict(list)
    for patient in patients:
        zip_code = _postal_code(patient)
        dob = patient.get("birthDate", "")
        if not zip_code or not dob:
            continue
        buckets[(zip_code, dob)].append(patient)

    candidates: List[HardNegativeCandidate] = []
    for (zip_code, dob), group in buckets.items():
        if len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                if a.get("id") == b.get("id"):
                    continue
                if _primary_family_name(a).upper() == _primary_family_name(b).upper():
                    continue
                candidates.append(
                    HardNegativeCandidate(
                        query=a,
                        candidate=b,
                        shared_fields={"postalCode": zip_code, "birthDate": dob},
                    )
                )
    return candidates
