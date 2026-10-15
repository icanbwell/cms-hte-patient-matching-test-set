"""Add same-surname adults to the sample so more children can live with one (BAI-1160).

A random 2,000-of-1M sample almost never contains a same-surname adult for a
sampled child (91 of 430 minors do). This module streams the ONC shards once for
ONC-derived adult records that share a surname with a child who has none, adds enough of
them to reach a target share of children with a same-surname adult, and drops the
same number of other adults from the same age band, so the sample size and every
age-band count are unchanged and the age-band gate still holds.

An added adult must have a street address and postal code (so a child can share it) and be a plausible parent: 18 to 50 years older than the child
(`household_assignment.is_plausible_parent_gap`; without the upper bound the
first version added "parents" a median 52 years older, every one of the 85+ band).
An adult who already covers a child is never swapped out, whichever surname that
is. If the age window makes the target unreachable the result reports the share
actually reached; it is never padded.

A same-surname adult is only a proxy for a parent: mothers often have a different
surname, and the relationship is assumed, not known. The target is a placeholder
(`minors_with_same_surname_adult` in drift_profile.py), not a measured share.

Everything runs at ONC's own vintage (population_targets.ONC_AS_OF), before the
birth-date shift. Deterministic for a seed; inputs are never mutated.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Set

from household_assignment import ADULT, has_home_address, is_plausible_parent_gap
from identity_guard import normalize_token
from population_sampling import age_of
from population_targets import ONC_AS_OF

Patient = Dict[str, Any]

DEFAULT_PER_SURNAME_CAP = 4


@dataclass(frozen=True)
class FamilyAdultsResult:
    patients: List[Patient]
    n_added: int
    n_covered_before: int
    n_covered_after: int
    n_minors: int
    added_parent_age_gaps: List[int]


def _family(patient: Patient) -> str:
    names = patient.get("name") or []
    return normalize_token(names[0].get("family")) if names else ""


def _band_of_adult(age: int) -> str:
    return "18-64" if age < 65 else ("65-84" if age < 85 else "85+")


def _is_covered(minor_age: int, adult_ages: Sequence[int]) -> bool:
    return any(is_plausible_parent_gap(a - minor_age) for a in adult_ages)


def find_adult_candidates(
    batches: Iterable[Sequence[Patient]],
    needed: Mapping[str, Sequence[int]],
    *,
    exclude_ids: Set[str],
    per_surname_cap: int,
    seed: int,
    as_of: date = ONC_AS_OF,
) -> Dict[str, List[Patient]]:
    """Stream `batches` once and keep, per surname in `needed`, up to
    `per_surname_cap` ONC-derived adults who are a plausible parent (18 to 50 years
    older) of at least one of that surname's uncovered children (`needed` maps
    surname -> those children's ages). Kept by seeded reservoir sampling."""
    kept: Dict[str, List[Patient]] = {s: [] for s in needed}
    seen: Dict[str, int] = {s: 0 for s in needed}
    rngs = {s: random.Random(f"{seed}:family_adults:{s}") for s in needed}
    for batch in batches:
        for record in batch:
            surname = _family(record)
            if surname not in needed or str(record.get("id")) in exclude_ids:
                continue
            if not has_home_address(record):
                continue  # could not share an address with the child
            age = age_of(record, as_of)
            if (
                age is None
                or age < ADULT
                or not any(is_plausible_parent_gap(age - c) for c in needed[surname])
            ):
                continue
            seen[surname] += 1
            pool = kept[surname]
            if len(pool) < per_surname_cap:
                pool.append(record)
            else:
                slot = rngs[surname].randrange(seen[surname])
                if slot < per_surname_cap:
                    pool[slot] = record
    return {s: pool for s, pool in kept.items() if pool}


def add_family_adults(
    patients: Sequence[Patient],
    batches_factory: Any,
    *,
    target_share: float,
    exclude_ids: Set[str],
    seed: int,
    per_surname_cap: int = DEFAULT_PER_SURNAME_CAP,
    as_of: date = ONC_AS_OF,
) -> FamilyAdultsResult:
    """`patients` with enough ONC-derived same-surname adults swapped in that at least
    `target_share` of the children have one (as far as the shards allow).
    `batches_factory` is a zero-argument callable returning the shard batches."""
    if not 0.0 <= target_share <= 1.0:
        raise ValueError(f"target_share must be in [0, 1], got {target_share}")
    people = list(patients)
    ages = [age_of(p, as_of) for p in people]
    minors = [i for i, a in enumerate(ages) if a is not None and a < ADULT]
    adults = [i for i, a in enumerate(ages) if a is None or a >= ADULT]
    adult_ages_by_family: Dict[str, List[int]] = {}
    for i in adults:
        if ages[i] is not None and _family(people[i]) and has_home_address(people[i]):
            adult_ages_by_family.setdefault(_family(people[i]), []).append(ages[i] or 0)

    def covered(i: int) -> bool:
        family = _family(people[i])
        return bool(family) and _is_covered(
            ages[i] or 0, adult_ages_by_family.get(family, ())
        )

    n_covered_before = sum(covered(i) for i in minors)
    wanted = math.ceil(target_share * len(minors)) - n_covered_before
    if wanted <= 0 or not minors:
        return FamilyAdultsResult(
            people, 0, n_covered_before, n_covered_before, len(minors), []
        )

    rng = random.Random(f"{seed}:family_adults")
    uncovered = [i for i in minors if _family(people[i]) and not covered(i)]
    needed: Dict[str, List[int]] = {}
    for i in uncovered:
        needed.setdefault(_family(people[i]), []).append(ages[i] or 0)
    candidates = find_adult_candidates(
        batches_factory(),
        needed,
        exclude_ids=exclude_ids | {str(p.get("id")) for p in people},
        per_surname_cap=per_surname_cap,
        seed=seed,
        as_of=as_of,
    )

    rng.shuffle(uncovered)
    # Never swap out an adult who already covers a child (any surname), nor one
    # who shares a surname with an uncovered child.
    minor_ages_by_family: Dict[str, List[int]] = {}
    for i in minors:
        if _family(people[i]):
            minor_ages_by_family.setdefault(_family(people[i]), []).append(ages[i] or 0)
    protected = {
        i
        for i in adults
        if _family(people[i]) in needed
        or (
            ages[i] is not None
            and any(
                is_plausible_parent_gap((ages[i] or 0) - c)
                for c in minor_ages_by_family.get(_family(people[i]), ())
            )
        )
    }
    victims_by_band: Dict[str, List[int]] = {}
    for i in adults:
        if i not in protected and ages[i] is not None:
            victims_by_band.setdefault(_band_of_adult(ages[i] or 0), []).append(i)
    for victims in victims_by_band.values():
        rng.shuffle(victims)

    removed: Set[int] = set()
    added: List[Patient] = []
    added_gaps: List[int] = []
    newly_covered = 0
    used: Set[str] = set()
    for i in uncovered:
        if newly_covered >= wanted:
            break
        family = _family(people[i])
        if covered_by_added(family, ages[i] or 0, added, as_of):
            newly_covered += 1
            continue
        pool = [
            c
            for c in candidates.get(family, ())
            if str(c["id"]) not in used
            and is_plausible_parent_gap((age_of(c, as_of) or 0) - (ages[i] or 0))
        ]
        if not pool:
            continue
        adult = pool[0]
        band = _band_of_adult(age_of(adult, as_of) or 0)
        victims = victims_by_band.get(band, [])
        if not victims:
            continue
        removed.add(victims.pop())
        used.add(str(adult["id"]))
        added.append(adult)
        added_gaps.append((age_of(adult, as_of) or 0) - (ages[i] or 0))
        newly_covered += 1

    kept = [p for index, p in enumerate(people) if index not in removed]
    result = kept + added
    rng.shuffle(result)
    n_after = _count_covered(result, as_of)
    return FamilyAdultsResult(
        result, len(added), n_covered_before, n_after, len(minors), added_gaps
    )


def covered_by_added(
    family: str, minor_age: int, added: Sequence[Patient], as_of: date
) -> bool:
    return any(
        _family(a) == family
        and is_plausible_parent_gap((age_of(a, as_of) or 0) - minor_age)
        for a in added
    )


def _count_covered(patients: Sequence[Patient], as_of: date) -> int:
    ages = [age_of(p, as_of) for p in patients]
    adult_ages: Dict[str, List[int]] = {}
    for p, a in zip(patients, ages):
        if a is not None and a >= ADULT and _family(p) and has_home_address(p):
            adult_ages.setdefault(_family(p), []).append(a)
    return sum(
        1
        for p, a in zip(patients, ages)
        if a is not None
        and a < ADULT
        and _family(p)
        and _is_covered(a, adult_ages.get(_family(p), ()))
    )
