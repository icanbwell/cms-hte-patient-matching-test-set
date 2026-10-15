"""Reverse-blocking near-miss finder (session 16, Workstream 2).

Given the sampled query patients, stream every ONC shard once and keep real
records that resemble a query without being the same person: shared DOB+ZIP,
a near-identical name, siblings, a shared address, phone, email, or just a
birth date. This replaces mining pairs inside the 2,000-record sample, where
two colliding records almost never both appear.

Per record the finder looks its keys up in a small index built from the
queries (O(1) each), so there is no pairwise comparison and no 1M-record list.
Edit distance <= 1 on names uses a deletion neighborhood: a query registers its
name and every single-character deletion, a record looks up the same set, and
a hit is verified with a real edit-distance check.

Decoys are real ONC records, never fabricated, and are never the query, never
in `exclude_ids` (the sample and donor ids), and never
`is_possible_same_person` or `is_probable_duplicate` (typo duplicate) of the
query, nor of the query's pre-household original when `originals` is given
(household assignment drops minors' SSNs, which would hide an SSN match). Per (query, kind) at most
`per_kind_cap` decoys are kept, by seeded reservoir sampling, so a common DOB
or surname cannot flood a query.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Collection, Dict, Iterable, List, Mapping, Sequence, Set, Tuple

from identity_guard import (
    identity_key_names,
    is_possible_same_person,
    is_probable_duplicate,
    normalize_token,
    phone_set,
)
from text_distance import levenshtein_distance

Patient = Dict[str, Any]

SIBLING_MAX_AGE_GAP_YEARS = 3
DEFAULT_PER_KIND_CAP = 3

# Priority order: a record qualifying under several kinds is filed under the first.
KINDS: Tuple[str, ...] = (
    "dob_zip",
    "name",
    "sibling",
    "address",
    "phone",
    "email",
    "dob_only",
    "surname_zip",
)

PAIR_TYPE_BY_KIND: Dict[str, str] = {
    "dob_zip": "hard_negative",
    "name": "name_collision_negative",
    "sibling": "sibling_negative",
    "address": "near_miss_negative",
    "phone": "near_miss_negative",
    "email": "near_miss_negative",
    "dob_only": "near_miss_negative",
    "surname_zip": "near_miss_negative",
}


@dataclass(frozen=True)
class NearMiss:
    query: Patient
    decoy: Patient
    kind: str
    shared_fields: Mapping[str, str]

    @property
    def query_id(self) -> str:
        return str(self.query["id"])

    @property
    def pair_type(self) -> str:
        return PAIR_TYPE_BY_KIND[self.kind]


@dataclass(frozen=True)
class NearMissResult:
    near_misses: List[NearMiss]
    yield_by_kind: Dict[str, Dict[str, int]]


def _primary(patient: Patient) -> Dict[str, Any]:
    names = patient.get("name") or []
    return names[0] if names else {}


def _raw_family(patient: Patient) -> str:
    return str(_primary(patient).get("family") or "")


def _family(patient: Patient) -> str:
    return normalize_token(_raw_family(patient))


def _first(patient: Patient) -> str:
    given = _primary(patient).get("given") or []
    return normalize_token(given[0]) if given else ""


def _full_name(patient: Patient) -> str:
    return identity_key_names(patient) or ""


def _dob(patient: Patient) -> str:
    return str(patient.get("birthDate") or "")


def _birth_year_gap(a: Patient, b: Patient) -> int | None:
    try:
        return abs(int(_dob(a)[:4]) - int(_dob(b)[:4]))
    except ValueError:
        return None


def _address(patient: Patient) -> Dict[str, Any]:
    addresses = patient.get("address") or []
    return addresses[0] if addresses else {}


def _raw_zip(patient: Patient) -> str:
    return str(_address(patient).get("postalCode") or "")


def _zip(patient: Patient) -> str:
    return normalize_token(_raw_zip(patient))


def _street(patient: Patient) -> str:
    lines = _address(patient).get("line") or []
    return normalize_token(lines[0]) if lines else ""


def _emails(patient: Patient) -> Set[str]:
    return {
        str(t["value"]).strip().casefold()
        for t in patient.get("telecom") or []
        if t.get("system") == "email" and t.get("value")
    }


def _deletions(text: str) -> Set[str]:
    return {text[:i] + text[i + 1 :] for i in range(len(text))}


class _QueryIndex:
    def __init__(self, queries: Sequence[Patient]) -> None:
        self.queries: Dict[str, Patient] = {str(q["id"]): q for q in queries}
        self._dob_zip: Dict[Tuple[str, str], List[str]] = defaultdict(list)
        self._name: Dict[str, List[str]] = defaultdict(list)
        self._surname_zip: Dict[Tuple[str, str], List[str]] = defaultdict(list)
        self._address: Dict[Tuple[str, str], List[str]] = defaultdict(list)
        self._phone: Dict[str, List[str]] = defaultdict(list)
        self._email: Dict[str, List[str]] = defaultdict(list)
        self._dob: Dict[str, List[str]] = defaultdict(list)
        for query_id, query in self.queries.items():
            dob, zip_, family, street = (
                _dob(query),
                _zip(query),
                _family(query),
                _street(query),
            )
            if dob and zip_:
                self._dob_zip[(dob, zip_)].append(query_id)
            name = _full_name(query)
            if name:
                for key in {name} | _deletions(name):
                    self._name[key].append(query_id)
            if family and zip_:
                self._surname_zip[(family, zip_)].append(query_id)
            if street and zip_:
                self._address[(street, zip_)].append(query_id)
            for phone in phone_set(query):
                self._phone[phone].append(query_id)
            for email in _emails(query):
                self._email[email].append(query_id)
            if dob:
                self._dob[dob].append(query_id)

    def keys_hit(self, record: Patient) -> Dict[str, Set[str]]:
        """query id -> the key families the record shares with that query."""
        hit: Dict[str, Set[str]] = defaultdict(set)
        dob, zip_, family, street = (
            _dob(record),
            _zip(record),
            _family(record),
            _street(record),
        )
        if dob and zip_:
            for query_id in self._dob_zip.get((dob, zip_), ()):
                hit[query_id].add("dob_zip")
        name = _full_name(record)
        if name:
            for key in {name} | _deletions(name):
                for query_id in self._name.get(key, ()):
                    hit[query_id].add("name")
        if family and zip_:
            for query_id in self._surname_zip.get((family, zip_), ()):
                hit[query_id].add("surname_zip")
        if street and zip_:
            for query_id in self._address.get((street, zip_), ()):
                hit[query_id].add("address")
        for phone in phone_set(record):
            for query_id in self._phone.get(phone, ()):
                hit[query_id].add("phone")
        for email in _emails(record):
            for query_id in self._email.get(email, ()):
                hit[query_id].add("email")
        if dob:
            for query_id in self._dob.get(dob, ()):
                hit[query_id].add("dob")
        return hit


def _classify(
    query: Patient, record: Patient, keys: Set[str]
) -> Tuple[str, Dict[str, str]] | None:
    same_family = _family(query) == _family(record)
    same_first = _first(query) == _first(record)
    if "dob_zip" in keys and not same_family:
        return "dob_zip", {"postalCode": _raw_zip(record), "birthDate": _dob(record)}
    if "name" in keys and _dob(query) != _dob(record) and _zip(query) != _zip(record):
        distance = levenshtein_distance(_full_name(query), _full_name(record), 1)
        if distance <= 1:
            return "name", {"name_distance": str(distance)}
    if "surname_zip" in keys and not same_first:
        gap = _birth_year_gap(query, record)
        if gap is not None and gap <= SIBLING_MAX_AGE_GAP_YEARS:
            return "sibling", {
                "age_gap_years": str(gap),
                "family_name": _raw_family(record),
                "postalCode": _raw_zip(record),
            }
    if "address" in keys and not same_family:
        return "address", {"shared": "address"}
    if "phone" in keys and not same_family:
        return "phone", {"shared": "phone"}
    if "email" in keys and not same_family:
        return "email", {"shared": "email"}
    if "dob" in keys and not same_family and not same_first:
        return "dob_only", {"shared": "birthDate"}
    if "surname_zip" in keys and not same_first:
        return "surname_zip", {"shared": "surname+postalCode"}
    return None


def _same_person_as(query: Patient, record: Patient) -> bool:
    return is_possible_same_person(query, record) or is_probable_duplicate(
        query, record
    )


def _reservoir_offer(
    pool: List[NearMiss],
    miss: NearMiss,
    seen_count: int,
    cap: int,
    rng: random.Random,
) -> None:
    """Algorithm-R step: keep `miss` (the `seen_count`-th candidate for its
    slot) in `pool` with probability `cap / seen_count` once the pool is full."""
    if len(pool) < cap:
        pool.append(miss)
        return
    position = rng.randrange(seen_count)
    if position < cap:
        pool[position] = miss


def _interleave(per_kind: Mapping[str, List[NearMiss]]) -> List[NearMiss]:
    ordered = {
        kind: sorted(per_kind.get(kind, []), key=lambda m: str(m.decoy["id"]))
        for kind in KINDS
    }
    longest = max((len(v) for v in ordered.values()), default=0)
    return [
        ordered[kind][position]
        for position in range(longest)
        for kind in KINDS
        if position < len(ordered[kind])
    ]


def find_near_misses(
    queries: Sequence[Patient],
    batches: Iterable[Sequence[Patient]],
    *,
    exclude_ids: Collection[str] = (),
    per_kind_cap: int = DEFAULT_PER_KIND_CAP,
    seed: int = 0,
    originals: Mapping[str, Patient] | None = None,
) -> NearMissResult:
    """Stream `batches` once and return up to `per_kind_cap` real look-alikes
    per (query, kind). See the module docstring. `originals` maps a query id to
    its pre-household record; decoys are also screened against it."""
    index = _QueryIndex(queries)
    excluded = set(exclude_ids)
    rngs = {qid: random.Random(f"{seed}:near_miss:{qid}") for qid in index.queries}
    kept: Dict[Tuple[str, str], List[NearMiss]] = defaultdict(list)
    seen: Counter[Tuple[str, str]] = Counter()
    for batch in batches:
        for record in batch:
            record_id = str(record.get("id"))
            if record_id in excluded:
                continue
            for query_id, keys in index.keys_hit(record).items():
                query = index.queries[query_id]
                if record_id == query_id or _same_person_as(query, record):
                    continue
                original = (originals or {}).get(query_id)
                if original is not None and _same_person_as(original, record):
                    continue
                found = _classify(query, record, keys)
                if found is None:
                    continue
                kind, shared = found
                slot = (query_id, kind)
                seen[slot] += 1
                miss = NearMiss(
                    query=query, decoy=record, kind=kind, shared_fields=shared
                )
                _reservoir_offer(
                    kept[slot], miss, seen[slot], per_kind_cap, rngs[query_id]
                )
    near_misses: List[NearMiss] = []
    for query_id in sorted(index.queries):
        near_misses.extend(
            _interleave({kind: kept.get((query_id, kind), []) for kind in KINDS})
        )
    yield_by_kind = {
        kind: {
            "queries": sum(1 for (_, k), pool in kept.items() if k == kind and pool),
            "kept": sum(len(pool) for (_, k), pool in kept.items() if k == kind),
            "seen": sum(count for (_, k), count in seen.items() if k == kind),
        }
        for kind in KINDS
    }
    return NearMissResult(near_misses=near_misses, yield_by_kind=yield_by_kind)
