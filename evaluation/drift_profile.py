"""Per-scenario emission rates for the true-match drift scenarios.

A rate is the probability that a given base patient gets one variant of that
scenario. The workgroup owns these numbers (session 15, Open Question 1): the
defaults below are PLACEHOLDERS chosen to exercise each scenario at a visible
volume, not measured real-world rates. Override with a JSON file:

    {"source": "who measured what, when", "rates": {"phone_churn": 0.4}}

Rates absent from the file default to 0.0 (scenario off).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Mapping

# Session-14 scenarios keep emitting for every applicable patient, exactly as before.
LEGACY_RATES: Dict[str, float] = {
    "ssn_dropped": 1.0,
    "marriage_variant": 1.0,
    "phone_variant": 1.0,
}

# PLACEHOLDERS - see module docstring. gender_drift stays off by default until
# the workgroup confirms whether administrative-sex disagreement should still
# be labeled an expected match (Open Question 4).
PLACEHOLDER_RATES: Dict[str, float] = {
    "surname_change": 0.15,
    "address_move": 0.20,
    "phone_churn": 0.50,
    "email_churn": 0.25,
    "gender_drift": 0.0,
    "placeholder": 0.15,
    # Workstream C (household_assignment.py): probability that a household
    # member shares the anchor adult's phone / email, and that a child under 13
    # has no SSN on file. Children under 13 ALWAYS take the anchor's
    # phone and email, or have none when the anchor has none.
    "household_shared_phone": 0.50,
    "household_shared_email": 0.50,
    "minor_ssn_absent": 0.70,
}

DEFAULT_SOURCE = (
    "PLACEHOLDER rates, not measured; supply the workgroup's measured "
    "cross-organization disagreement rates via a profile JSON file"
)


@dataclass(frozen=True)
class DriftProfile:
    rates: Mapping[str, float] = field(
        default_factory=lambda: {**LEGACY_RATES, **PLACEHOLDER_RATES}
    )
    source: str = DEFAULT_SOURCE

    def __post_init__(self) -> None:
        for name, rate in self.rates.items():
            if not 0.0 <= rate <= 1.0:
                raise ValueError(f"rate for {name!r} must be in [0, 1], got {rate}")

    def rate(self, name: str) -> float:
        return self.rates.get(name, 0.0)

    def without(self, *names: str) -> DriftProfile:
        """A copy with the named scenarios switched off."""
        return DriftProfile(
            rates={k: (0.0 if k in names else v) for k, v in self.rates.items()},
            source=self.source,
        )

    @classmethod
    def from_json(cls, path: Path) -> DriftProfile:
        with path.open() as f:
            data = json.load(f)
        return cls(rates=dict(data["rates"]), source=str(data.get("source", "")))
