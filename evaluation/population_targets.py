"""Real-world population targets for the "realistic" dataset (session 15, Workstream C).

Every number here is a cited public estimate or an explicit reviewer-supplied
approximation, never a guess. Age is measured as `AS_OF.year - birth year`, so
a dataset is deterministic regardless of the day it is built.

AS_OF is 2017-01-01, ONC's own vintage (its latest birth year is 2016). Measured
as of 2026 the same data has no one under age 10, so infants and toddlers (the
hardest children to match) could never be sampled, and ONC looks 8.7% under 18;
as of 2017 it is 20.1% under 18. Aged 85+ is 12.6% as of 2017 (21.3% as of 2026)
against about 2% nationally: the elderly skew is the one that persists. Open
Question 5: the workgroup may pin a different date or Census vintage.

Age bands (shares of the U.S. population):

- 0-17: 21.5% - U.S. Census Bureau, "United States and World Child
  Populations" (Vintage 2024 population estimates, as of July 1, 2024).
- 65+: 17.3% (57.8 million) in 2022 - Administration for Community Living,
  "2023 Profile of Older Americans" (May 2024), citing the Census Bureau.
- 85+: 6.5 million in 2022 (same source); as a share of the 2022 population
  implied by 57.8M / 17.3% (about 334.1M) that is 1.95%.
- 65-84 = 65+ minus 85+ (15.35%); 18-64 = the remainder (61.2%).

The 0-17 figure (2024) and the 65+/85+ figures (2022) come from different
vintages; the 18-64 band absorbs the difference. Pin one vintage when the
workgroup answers Open Question 5.

Households:

- 29% of U.S. households are one-person households (2024) - U.S. Census
  Bureau, "Nearly Two-Thirds of U.S. Households are Family Households"
  (America's Families and Living Arrangements, 2024).
- Mean household size 2.5: the workgroup reviewer's "roughly 2.5 nationally",
  an approximation not independently verified against a Census table. The shape of the
  multi-person size distribution is NOT given by these sources; see
  household_assignment.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, Tuple

# Fixed (not date.today()) so output is deterministic. See module docstring.
AS_OF = date(2017, 1, 1)

# (band name, inclusive lower age, exclusive upper age)
AGE_BANDS: Tuple[Tuple[str, int, int], ...] = (
    ("0-17", 0, 18),
    ("18-64", 18, 65),
    ("65-84", 65, 85),
    ("85+", 85, 200),
)


@dataclass(frozen=True)
class Target:
    value: float
    source: str


AGE_BAND_TARGETS: Dict[str, Target] = {
    "0-17": Target(
        0.215, "U.S. Census Bureau, Vintage 2024 population estimates (July 1, 2024)"
    ),
    "18-64": Target(
        0.612, "Remainder: 1 - 0-17 (21.5%) - 65+ (17.3%); mixed 2022/2024 vintages"
    ),
    "65-84": Target(
        0.1535, "65+ 17.3% (ACL 2023 Profile of Older Americans, 2022) minus 85+ 1.95%"
    ),
    "85+": Target(
        0.0195,
        "6.5M age 85+ / (57.8M / 17.3%) (ACL 2023 Profile of Older Americans, 2022)",
    ),
}

SINGLE_PERSON_HOUSEHOLD_SHARE = Target(
    0.29, "U.S. Census Bureau, America's Families and Living Arrangements: 2024"
)
MEAN_HOUSEHOLD_SIZE = Target(
    2.5,
    "Workgroup reviewer ('roughly 2.5 nationally'); not independently verified against a Census table",
)


def age_band_targets() -> Dict[str, float]:
    """Band name -> target share, in AGE_BANDS order; sums to 1."""
    return {name: AGE_BAND_TARGETS[name].value for name, _, _ in AGE_BANDS}
