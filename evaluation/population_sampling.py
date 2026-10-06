"""Age-stratified sampling of ONC patients (session 15, Workstream C).

The committed samples take the first N rows of one alphabetically sorted ONC
shard, which inherits ONC's age skew (8% under 18, 21% aged 85+) and a surname
skew. `stratified_sample` instead draws, across ALL shards and one shard at a
time (no 1M-row list), a seeded random sample whose age-band counts match the
quotas for a target distribution (population_targets.py), plus a disjoint donor
pool drawn from the same bands.

Selection is a reservoir sample per band (algorithm R) driven by one seeded RNG,
so the result is deterministic for a given seed and batch order. Patients
without a parseable birth date are never sampled. Raises ValueError when ONC
cannot supply a band's quota (the message names the band and its supply).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from population_targets import AGE_BANDS, AS_OF, age_band_targets

Patient = Dict[str, Any]


def age_of(patient: Patient, as_of: date = AS_OF) -> int | None:
    """Whole-year-difference age as of `as_of`, or None without a usable birthDate."""
    try:
        return as_of.year - int(str(patient.get("birthDate") or "")[:4])
    except ValueError:
        return None


def band_of(age: int | None) -> str | None:
    if age is None or age < 0:
        return None
    for name, low, high in AGE_BANDS:
        if low <= age < high:
            return name
    return None


def band_quotas(n: int, targets: Mapping[str, float]) -> Dict[str, int]:
    """Integer per-band counts summing to exactly `n` (largest-remainder rounding)."""
    if n < 0:
        raise ValueError("n must be >= 0")
    total = sum(targets.values())
    exact = {band: n * share / total for band, share in targets.items()}
    quotas = {band: int(value) for band, value in exact.items()}
    leftover = n - sum(quotas.values())
    by_remainder = sorted(exact, key=lambda band: (quotas[band] - exact[band], band))
    for band in by_remainder[:leftover]:
        quotas[band] += 1
    return quotas


@dataclass(frozen=True)
class StratifiedSample:
    patients: List[Patient]
    donors: List[Patient]
    supply: Dict[str, int] = field(default_factory=dict)


def stratified_sample(
    batches: Iterable[Sequence[Patient]],
    n: int,
    *,
    donor_n: int = 0,
    seed: int = 0,
    targets: Mapping[str, float] | None = None,
    as_of: date = AS_OF,
) -> StratifiedSample:
    """A band-stratified sample of `n` patients and a disjoint `donor_n` donors.

    `batches` is consumed once, one batch (e.g. one ONC shard) at a time."""
    targets = dict(targets or age_band_targets())
    sample_quota = band_quotas(n, targets)
    donor_quota = band_quotas(donor_n, targets)
    rng = random.Random(f"{seed}:stratified_sample")
    reservoirs: Dict[str, List[Patient]] = {band: [] for band in targets}
    supply: Dict[str, int] = {band: 0 for band in targets}
    for batch in batches:
        for patient in batch:
            band = band_of(age_of(patient, as_of))
            if band not in reservoirs:
                continue
            supply[band] += 1
            size = sample_quota[band] + donor_quota[band]
            if len(reservoirs[band]) < size:
                reservoirs[band].append(patient)
            else:
                slot = rng.randrange(supply[band])
                if slot < size:
                    reservoirs[band][slot] = patient
    for band, reservoir in reservoirs.items():
        needed = sample_quota[band] + donor_quota[band]
        if len(reservoir) < needed:
            raise ValueError(
                f"age band {band!r}: need {needed} patients, ONC supplies {supply[band]}"
            )
    sample: List[Patient] = []
    donors: List[Patient] = []
    for band in targets:
        reservoir = reservoirs[band]
        rng.shuffle(reservoir)
        sample.extend(reservoir[: sample_quota[band]])
        donors.extend(reservoir[sample_quota[band] :])
    rng.shuffle(sample)
    rng.shuffle(donors)
    return StratifiedSample(patients=sample, donors=donors, supply=supply)
