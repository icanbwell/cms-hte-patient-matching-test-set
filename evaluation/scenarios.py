"""Registry of per-patient true-match scenarios shared by both output tiers.

labeled_pairs.generate_raw_pairs() and population_cases.build_population_dataset()
iterate the SAME registry, so a scenario can no longer exist in one tier only
(session 15, finding F9). Every variant draws from its own RNG seeded by
(seed, scenario name, patient id): adding or reordering scenarios never
perturbs another scenario's output, and a patient's variant is identical in
both tiers.

Not in the registry (they keep their own generation): fuzzy variants,
normalization edge cases, and compound variants. Compound variants are
generated per tier (shared generator stream in the per-provision tier, a
per-patient RNG in the population tier), so their bodies match between tiers
only in the committed files, where the migration copied them from the sample
rows; registry scenarios match on regeneration too.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, Mapping, Sequence, Tuple

from drift_mutations import (
    address_move_variant,
    email_churn_variant,
    gender_drift_variant,
    phone_churn_variant,
    surname_change_variant,
)
from drift_profile import DriftProfile
from mutations import marriage_variant, phone_variant, ssn_dropped_variant
from placeholders import placeholder_variant

Patient = Dict[str, Any]


@dataclass(frozen=True)
class ScenarioContext:
    rng: random.Random
    donors: Sequence[Patient]
    next_patient: Patient | None


@dataclass(frozen=True)
class ScenarioResult:
    variant: Patient
    suffix: str
    strata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Scenario:
    name: str
    apply: Callable[[Patient, ScenarioContext], ScenarioResult | None]

    @property
    def pair_type(self) -> str:
        return self.name


def _ssn_dropped(patient: Patient, ctx: ScenarioContext) -> ScenarioResult | None:
    return ScenarioResult(ssn_dropped_variant(patient), "ssn_dropped")


def _marriage_variant(patient: Patient, ctx: ScenarioContext) -> ScenarioResult | None:
    if ctx.next_patient is None:
        return None
    return ScenarioResult(
        marriage_variant(patient, ctx.next_patient), "marriage_variant"
    )


def _phone_variant(patient: Patient, ctx: ScenarioContext) -> ScenarioResult | None:
    return ScenarioResult(phone_variant(patient), "phone_variant")


def _with_subtype(
    name: str, result: Tuple[Patient, str] | None
) -> ScenarioResult | None:
    if result is None:
        return None
    variant, subtype = result
    return ScenarioResult(variant, name, {"case": subtype})


def _surname_change(patient: Patient, ctx: ScenarioContext) -> ScenarioResult | None:
    return _with_subtype(
        "surname_change", surname_change_variant(patient, ctx.donors, ctx.rng)
    )


def _address_move(patient: Patient, ctx: ScenarioContext) -> ScenarioResult | None:
    return _with_subtype(
        "address_move", address_move_variant(patient, ctx.donors, ctx.rng)
    )


def _phone_churn(patient: Patient, ctx: ScenarioContext) -> ScenarioResult | None:
    return _with_subtype(
        "phone_churn", phone_churn_variant(patient, ctx.donors, ctx.rng)
    )


def _email_churn(patient: Patient, ctx: ScenarioContext) -> ScenarioResult | None:
    return _with_subtype(
        "email_churn", email_churn_variant(patient, ctx.donors, ctx.rng)
    )


def _gender_drift(patient: Patient, ctx: ScenarioContext) -> ScenarioResult | None:
    return _with_subtype("gender_drift", gender_drift_variant(patient, ctx.rng))


def _placeholder(patient: Patient, ctx: ScenarioContext) -> ScenarioResult | None:
    return _with_subtype("placeholder", placeholder_variant(patient, rng=ctx.rng))


# Order matters only for output ordering: the three session-14 scenarios keep
# their original relative order.
REGISTRY: Dict[str, Scenario] = {
    s.name: s
    for s in (
        Scenario("ssn_dropped", _ssn_dropped),
        Scenario("marriage_variant", _marriage_variant),
        Scenario("phone_variant", _phone_variant),
        Scenario("surname_change", _surname_change),
        Scenario("address_move", _address_move),
        Scenario("phone_churn", _phone_churn),
        Scenario("email_churn", _email_churn),
        Scenario("gender_drift", _gender_drift),
        Scenario("placeholder", _placeholder),
    )
}


def generate_scenario_variants(
    patient: Patient,
    *,
    next_patient: Patient | None,
    donors: Sequence[Patient],
    profile: DriftProfile,
    seed: int,
) -> Iterator[Tuple[Scenario, ScenarioResult]]:
    """Every registered scenario's variant for `patient`, honoring the
    profile's per-scenario rate. Scenarios that do not apply, or that leave
    the patient unchanged, yield nothing."""
    for name, scenario in REGISTRY.items():
        rate = profile.rate(name)
        rng = random.Random(f"{seed}:{name}:{patient['id']}")
        if rate <= 0.0 or (rate < 1.0 and rng.random() >= rate):
            continue
        result = scenario.apply(patient, ScenarioContext(rng, donors, next_patient))
        if result is None or result.variant == patient:
            continue
        yield scenario, result
