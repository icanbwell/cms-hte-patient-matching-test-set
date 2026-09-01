"""Population-query test tier: one record queried against a population of
candidates, expected answer a *set* (possibly empty, possibly several) - the
current cross-org workgroup Doc's ("A Shared Test Dataset for CMS Patient
Matching Compliance", current) second test kind, distinct from
labeled_pairs.py's per-provision pairs. See docs/sessions/pending/session_12.md
for the design rationale (Task 2) this module implements.

Reuses mutations.py/normalization_edge_cases.py/hard_negatives.py/
special_populations.py directly - the same generation logic labeled_pairs.py
and export_test_dataset.py already build on - rather than duplicating it. This
module's own job is only the regrouping: instead of "one row per (query,
candidate) pair," build "one row per query, holding its full candidate pool
and the subset of that pool which is a true match."

For each query patient:
  - The **known-match cluster** is its generated fuzzy-variant/normalization-
    edge-case candidates (never the query's own literal record - this mirrors
    FHIR Patient/$match's real shape of "find my other record(s)," not a
    trivial self-match).
  - The **decoy pool** is that query's mined hard-negative/special-population
    near-misses, topped up with random distractors from the broader sample up
    to `pool_size` (per the current Doc's own "forty near-misses" framing) -
    never displacing a true match to make room.

A query for which no true-match candidate was generated (e.g.
n_fuzzy_variants_per_patient=0 and include_normalization_edge_cases=False)
correctly produces an **empty** expected_match_ids - the current Doc calls
this out explicitly as a real case ("possibly empty"), not an edge case to
special-case away.

Known simplification vs. the pairwise tier (labeled_pairs.py): a
construct_institutional_negatives() pair fabricates the SAME synthetic
address on *both* sides, testing "do two institutional residents avoid
matching each other." This tier only injects the fabricated-address side into
the real query's decoy pool (the query keeps its real address), testing "does
a real query avoid matching a candidate located at a shared institutional
address" instead. Both are valid non-match tests; they are not identical, so
this is flagged rather than presented as full coverage of the same scenario.
Institutional candidates are namespaced with a "::institutional::<type>" id
suffix (not the plain ONC EnterpriseID) specifically to avoid colliding, in
the shared candidate registry, with that same person's real, address-intact
record used elsewhere as a plain distractor.

MEMORY & SCALE - same caution as labeled_pairs.py: this module normalizes its
own copy of `patients` independently (needed for random-distractor top-up),
on top of whatever labeled_pairs.py-style callers already normalized. At this
repo's documented default scale (one shard, sampled down via SAMPLE_SIZE) that
extra copy is a non-issue; see SYNTHETIC_DATA_SETUP.md's "Memory & scale"
section before raising SAMPLE_SIZE or POOL_SIZE.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Dict, List, Set

from hard_negatives import mine_shared_address_hard_negatives
from mutations import generate_fuzzy_variant
from normalization_edge_cases import diacritic_variant, punctuation_variant
from patient_matching.normalization.manager import NormalizationManager
from special_populations import (
    INSTITUTION_TYPES,
    construct_institutional_negatives,
    mine_shared_surname_household_negatives,
)

Patient = Dict[str, Any]

# Per the current Doc's own framing: "the genuinely hard failure is picking a
# plausible wrong candidate out of forty near-misses."
DEFAULT_POOL_SIZE = 40


@dataclass(frozen=True)
class PopulationCase:
    """One query patient plus its candidate pool and expected match subset.

    Attributes:
        query_id: Stable id for the query patient (its ONC EnterpriseID).
        query_patient: The query/"Outside Record" FHIR Patient resource.
        candidate_ids: Every candidate id in this query's pool, resolvable
            against a PopulationDataset.candidates registry - deterministic
            order given a fixed seed.
        expected_match_ids: The subset of candidate_ids that are the same
            person as the query - possibly empty (see module docstring).
        rationale: Which generation categories contributed to this pool
            (e.g. "population/fuzzy_variant+hard_negative"), for provenance.
    """

    query_id: str
    query_patient: Patient
    candidate_ids: List[str]
    expected_match_ids: List[str]
    rationale: str


@dataclass(frozen=True)
class PopulationDataset:
    """The full population-query tier: every query case, plus the shared
    candidate registry (id -> Patient) their candidate_ids resolve against.

    `candidates` deliberately holds every normalized input patient too (not
    only ones that ended up in some query's pool) - any of them may be
    referenced as a random distractor in a *different* query's pool built
    from the same call, per module docstring's "splitting an existing file"
    framing.
    """

    cases: List[PopulationCase]
    candidates: Dict[str, Patient]


def build_population_dataset(
    patients: List[Patient],
    *,
    pool_size: int = DEFAULT_POOL_SIZE,
    n_fuzzy_variants_per_patient: int = 1,
    include_normalization_edge_cases: bool = True,
    include_special_populations: bool = True,
    institutional_group_size: int = 3,
    seed: int = 0,
) -> PopulationDataset:
    """Build the population-query tier from ONC patients - see module
    docstring for the per-query pool-assembly rules."""
    normalizer = NormalizationManager()
    normalized = [normalizer.normalize(p) for p in patients]
    by_id: Dict[str, Patient] = {p["id"]: p for p in normalized}

    rng = random.Random(seed)
    topup_rng = random.Random(f"{seed}:population_topup")

    candidates: Dict[str, Patient] = dict(by_id)
    pool_members: Dict[str, List[str]] = {pid: [] for pid in by_id}
    pool_seen: Dict[str, Set[str]] = {pid: set() for pid in by_id}
    match_members: Dict[str, List[str]] = {pid: [] for pid in by_id}
    categories: Dict[str, Set[str]] = {pid: set() for pid in by_id}

    def add_candidate(
        query_id: str,
        candidate_id: str,
        patient: Patient,
        is_true_match: bool,
        category: str,
    ) -> None:
        candidates.setdefault(candidate_id, patient)
        if candidate_id in pool_seen[query_id]:
            return
        pool_seen[query_id].add(candidate_id)
        pool_members[query_id].append(candidate_id)
        if is_true_match:
            match_members[query_id].append(candidate_id)
        categories[query_id].add(category)

    for pid, patient in by_id.items():
        for _ in range(n_fuzzy_variants_per_patient):
            variant, mutation_type = generate_fuzzy_variant(patient, rng=rng)
            add_candidate(
                pid, f"{pid}::{mutation_type}", variant, True, "fuzzy_variant"
            )
        if include_normalization_edge_cases:
            diacritic = diacritic_variant(patient, rng=rng)
            add_candidate(
                pid, f"{pid}::diacritic", diacritic, True, "normalization_edge_case"
            )
            punctuated = punctuation_variant(patient, rng=rng)
            add_candidate(
                pid, f"{pid}::punctuation", punctuated, True, "normalization_edge_case"
            )

    for hard_negative in mine_shared_address_hard_negatives(normalized):
        add_candidate(
            hard_negative.query["id"],
            hard_negative.candidate["id"],
            hard_negative.candidate,
            False,
            "hard_negative",
        )

    if include_special_populations:
        for household in mine_shared_surname_household_negatives(normalized):
            add_candidate(
                household.query["id"],
                household.candidate["id"],
                household.candidate,
                False,
                "special_population",
            )
        for institution_type in INSTITUTION_TYPES:
            for institutional in construct_institutional_negatives(
                normalized,
                institution_type,
                group_size=institutional_group_size,
                rng=rng,
            ):
                # Namespaced id - the candidate body has a fabricated address
                # overwritten on top of a real EnterpriseID (see
                # special_populations.py's _with_synthetic_address), so it must
                # not share a registry key with that same person's plain,
                # address-intact record (module docstring's "Known
                # simplification").
                candidate_id = f"{institutional.candidate['id']}::institutional::{institution_type}"
                add_candidate(
                    institutional.query["id"],
                    candidate_id,
                    institutional.candidate,
                    False,
                    "special_population",
                )

    all_ids = list(by_id)
    cases: List[PopulationCase] = []
    for pid, patient in by_id.items():
        pool = list(pool_members[pid])
        true_matches = list(match_members[pid])

        if len(pool) < pool_size:
            distractors = [x for x in all_ids if x != pid and x not in pool_seen[pid]]
            topup_rng.shuffle(distractors)
            pool.extend(distractors[: pool_size - len(pool)])
        elif len(pool) > pool_size:
            # Never drop a true match to make room - trim decoys only.
            decoys = [c for c in pool if c not in match_members[pid]]
            pool = true_matches + decoys[: max(0, pool_size - len(true_matches))]

        cats = categories[pid]
        rationale = "population/" + "+".join(sorted(cats)) if cats else "population"
        cases.append(
            PopulationCase(
                query_id=pid,
                query_patient=patient,
                candidate_ids=pool,
                expected_match_ids=true_matches,
                rationale=rationale,
            )
        )

    return PopulationDataset(cases=cases, candidates=candidates)
