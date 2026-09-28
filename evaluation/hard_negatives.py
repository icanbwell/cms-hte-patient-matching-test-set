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


def _full_name(patient: Patient) -> str:
    names = patient.get("name") or []
    if not names:
        return ""
    entry = names[0]
    given = entry.get("given") or []
    first = str(given[0]) if given else ""
    family = str(entry.get("family") or "")
    return f"{first} {family}".strip().upper()


def _levenshtein_distance(a: str, b: str, max_distance: int | None = None) -> int:
    """Standard edit distance, stdlib-only - session 13 confirmed rapidfuzz
    is not an actual dependency of this repo (cited only in a docstring,
    never imported), so this avoids adding one just for this.

    `max_distance`, if given, aborts as soon as every entry in the current
    row exceeds it (the true distance can only grow from there), returning
    `max_distance + 1` rather than the exact distance - callers that only
    need a "<= max_distance?" answer avoid the full O(len(a)*len(b)) matrix
    on pairs that are obviously too far apart."""
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    if max_distance is not None and abs(len(a) - len(b)) > max_distance:
        return max_distance + 1
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            current[j] = min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + cost,
            )
        if max_distance is not None and min(current) > max_distance:
            return max_distance + 1
        previous = current
    return previous[-1]


def mine_name_collision_negatives(
    patients: Iterable[Patient], *, max_name_distance: int = 1
) -> List[HardNegativeCandidate]:
    """Pairs of distinct-ID patients whose full name (first given name +
    family name, uppercased) is within `max_name_distance` edit distance of
    each other, but who share NEITHER postal code NOR date of birth - the
    inverse signal from mine_shared_address_hard_negatives() (name differs,
    ZIP+DOB match). Targets the failure mode Luke Breyer (Epic) flagged in
    the 2026-09-22 workgroup meeting: a matcher that over-weights name
    similarity alone, with no corroborating field, should still reject this
    pair.

    Blocked by the family name's first letter (an O(n) bucketing pass before
    an O(k^2) within-bucket comparison, k = bucket size) - mirrors
    mine_shared_address_hard_negatives()'s blocking rationale. A
    one-character edit at the very first letter of a family name (e.g.
    "Smith" vs. "Amith") would cross buckets and be missed; accepted as the
    same kind of blocking-key tradeoff every exact-key miner in this module
    already makes.

    Within a bucket, patients are sorted by full-name length and only
    compared against others within `max_name_distance` of that length (an
    edit-distance-<=max_name_distance pair can never differ in length by
    more than that), and `_levenshtein_distance`'s own early-abort skips the
    rest of a doomed comparison besides. This is a real constant-factor
    speedup (~4.5x measured on the vendored ONC shard at n=8000) but NOT an
    asymptotic-complexity fix: real surnames cluster tightly in length, so
    the length window still holds most of a large bucket and this remains
    effectively O(n^2) at scale (measured ~37s at n=8000, ~142s at n=16000 -
    consistent with the SYNTHETIC_DATA_SETUP.md "Memory & scale" section's
    warning about single-process scans over the full ~1,000,000-record
    dataset). Read that section - and re-measure this function specifically
    - before raising SAMPLE_SIZE past the low tens of thousands."""
    buckets: Dict[str, List[Patient]] = defaultdict(list)
    for patient in patients:
        family = _primary_family_name(patient).upper()
        if not family or not _postal_code(patient) or not patient.get("birthDate"):
            continue
        buckets[family[0]].append(patient)

    candidates: List[HardNegativeCandidate] = []
    for group in buckets.values():
        entries = sorted(
            ((patient, _full_name(patient)) for patient in group),
            key=lambda entry: len(entry[1]),
        )
        n = len(entries)
        for i in range(n):
            a, name_a = entries[i]
            for j in range(i + 1, n):
                b, name_b = entries[j]
                if len(name_b) - len(name_a) > max_name_distance:
                    break
                if a.get("id") == b.get("id"):
                    continue
                if _postal_code(a) == _postal_code(b) or a.get("birthDate") == b.get(
                    "birthDate"
                ):
                    continue
                if name_a == name_b:
                    continue
                distance = _levenshtein_distance(name_a, name_b, max_name_distance)
                if distance > max_name_distance:
                    continue
                candidates.append(
                    HardNegativeCandidate(
                        query=a,
                        candidate=b,
                        shared_fields={"name_distance": str(distance)},
                    )
                )
    return candidates
