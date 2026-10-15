"""Shift birth dates forward so ONC's 2017 population reads as a current one.

ONC has no births after 2016, so measured as of today it has nobody under age
10 and the hardest children to match (infants and toddlers) cannot be sampled.
Sampling therefore runs on ONC's own vintage (population_targets.ONC_AS_OF), and
every sampled, donor and decoy record is then moved forward by
`DOB_SHIFT_YEARS` so that the same people have the same ages as of
population_targets.AS_OF. Month and day are kept, so DOB typo and swap
variants behave as before; a 29 February birth date moves to 28 February in a
non-leap year. No identifier other than the birth date is touched.
"""

from __future__ import annotations

import calendar
from typing import Any, Dict

Patient = Dict[str, Any]


def shift_birth_date_value(value: str, years: int) -> str:
    """`value` (ISO yyyy-mm-dd) with the year moved forward by `years`; anything
    else is returned unchanged."""
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        return value
    try:
        year, month, day = int(value[:4]), int(value[5:7]), int(value[8:10])
    except ValueError:
        return value
    year += years
    day = min(day, calendar.monthrange(year, month)[1])
    return f"{year:04d}-{month:02d}-{day:02d}"


def shift_birth_date(patient: Patient, years: int) -> Patient:
    """A shallow copy of `patient` with `birthDate` moved forward by `years`.
    `patient` is not modified. A patient with no birthDate is returned as is."""
    birth_date = patient.get("birthDate")
    if not birth_date:
        return patient
    return {**patient, "birthDate": shift_birth_date_value(str(birth_date), years)}
