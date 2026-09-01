"""Real-world prevalence estimates per test-case category, for the
`frequency_lookup` seam `export_test_dataset.build_test_case_records()`
exposes (see that module's `uniform_frequency()` and
`LabeledCaseRecord.frequency` docstring for why this exists).

FOR MAINTAINER REVIEW - not yet the default. Every value here is either:
  (a) a real, cited public-source estimate (has_public_estimate=True), or
  (b) an explicit "no public estimate found" placeholder
      (has_public_estimate=False, value pinned to NEUTRAL_FREQUENCY) -
      never a guessed number standing in for real data.

Sources are exclusively public (U.S. Census Bureau, CDC/NCHS, Pew Research
Center, peer-reviewed record-linkage literature) - no member-organization
client data, consistent with this backlog's Option A+B-only scoping (see
docs/sessions/index.md, 2026-08-16).

IMPORTANT CAVEAT ON WHAT THESE NUMBERS MEAN: these are rough, order-of-
magnitude population-prevalence estimates for how common the *scenario* is
(e.g., "what fraction of the population lives in a nursing facility"), not a
measurement of this repo's synthetic dataset or of any matching algorithm's
behavior. They exist so a consumer of evaluation/cases/*.jsonl can compute a
real-world-weighted aggregate metric across categories without needing this
repo's own generated case counts (which are a generation-parameter artifact -
see cases/README.md's "Frequency and real-world representativeness") to
mirror real-world proportions.

Research conducted 2026-08-16 (see docs/sessions/pending/session_10.md's
Task 9 execution notes for the full research trail).

SCOPE, per session 12: these estimates remain useful documentation/analysis metadata (how rare is
a given scenario, really), but are not a substitute for computing precision/FDR/F1/accuracy over
an actually-representative sample. The cross-org workgroup's finalized proposal resolves the
representativeness problem this module was built for differently than a per-category frequency
multiplier does - see evaluation/population_cases.py and evaluation/cases/README.md's "Frequency
and real-world representativeness" section for the population-query tier these metrics should be
computed over instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

NEUTRAL_FREQUENCY = 1.0


@dataclass(frozen=True)
class PrevalenceEstimate:
    """One category's real-world prevalence estimate, or an explicit
    placeholder when no public estimate could be found.

    Attributes:
        value: The frequency weight. Pinned to NEUTRAL_FREQUENCY when
            has_public_estimate is False - a placeholder must never silently
            double as a real small estimate.
        has_public_estimate: False means no citable public source was found
            for this category at the needed granularity; value is a
            placeholder, not a real estimate.
        is_direct_measurement: True if `value` is a direct measurement of
            the scenario itself (e.g. Census's own "nursing facility
            population" count). False if it's a proxy for something related
            but not identical (e.g. "Hispanic-origin population share" used
            as a proxy for "diacritic-bearing name prevalence"). Only
            meaningful when has_public_estimate is True.
        source: Citation (publisher, title, year).
        notes: Caveats - what the estimate actually measures, what it
            doesn't, and why (for placeholders: why no public estimate
            exists at this granularity).
    """

    value: float
    has_public_estimate: bool
    is_direct_measurement: bool
    source: str
    notes: str


# ---------------------------------------------------------------------------
# Group quarters / institutional categories.
# Primary source for all direct measurements below: U.S. Census Bureau,
# "8.2 Million People Counted at U.S. Group Quarters in the 2020 Census"
# (Aug 2021), https://www.census.gov/library/stories/2021/08/united-states-group-quarters-in-2020-census.html
# 2020 Census total resident population: 331,449,281.
# ---------------------------------------------------------------------------

_SHELTER = PrevalenceEstimate(
    value=0.0006,
    has_public_estimate=True,
    is_direct_measurement=True,
    source=(
        "U.S. Census Bureau, 'The Emergency and Transitional Shelter "
        "Population: 2020' (Oct 2024)"
    ),
    notes=(
        "188,889 people counted in emergency/transitional shelters in the 2020 "
        "Census = 0.06% of the total U.S. population. Direct measurement."
    ),
)

_NURSING_FACILITY = PrevalenceEstimate(
    value=0.0049,
    has_public_estimate=True,
    is_direct_measurement=True,
    source="U.S. Census Bureau, 2020 Census Group Quarters release (Aug 2021)",
    notes=(
        "1,627,046 people counted in nursing/skilled-nursing facilities in the "
        "2020 Census = 0.49% of total population (up 8.3% from 2010). Direct "
        "measurement."
    ),
)

_CORRECTIONAL_INSTITUTION = PrevalenceEstimate(
    value=0.0059,
    has_public_estimate=True,
    is_direct_measurement=True,
    source="U.S. Census Bureau, 2020 Census Group Quarters release (Aug 2021)",
    notes=(
        "1,967,297 people counted in correctional facilities for adults "
        "(federal/state prisons, local jails) in the 2020 Census = 0.59% of "
        "total population (down 13.1% from 2010). Direct measurement."
    ),
)

_DORMITORY = PrevalenceEstimate(
    value=0.0084,
    has_public_estimate=True,
    is_direct_measurement=True,
    source="U.S. Census Bureau, 2020 Census Group Quarters release (Aug 2021)",
    notes=(
        "2,792,097 people counted in college/university student housing in "
        "the 2020 Census = 0.84% of total population, the largest single "
        "group-quarters category (up 10.7% from 2010). Direct measurement."
    ),
)

_NO_INSTITUTIONAL_SPLIT_PUBLISHED = (
    "No separate national count is published for this category. The Census "
    "Bureau's catch-all 'Other noninstitutional facilities' total "
    "(1,365,146 people, 0.41% of total population, up 20.3% from 2010) "
    "bundles emergency/transitional shelters, soup kitchens, targeted "
    "nonsheltered outdoor locations, group homes intended for adults, "
    "residential treatment centers for adults, and workers' group living "
    "quarters/Job Corps centers into one number, with no further public "
    "breakdown by type. Subtracting the separately-published shelter figure "
    "(188,889) leaves roughly 1,176,257 people (~0.35% of the population) "
    "covering all the remaining sub-types combined - not evenly splittable "
    "across them without fabricating a ratio. Left at NEUTRAL_FREQUENCY "
    "rather than guessing an even split."
)

_HOTEL_SHORT_TERM_HOUSING = PrevalenceEstimate(
    value=NEUTRAL_FREQUENCY,
    has_public_estimate=False,
    is_direct_measurement=False,
    source="U.S. Census Bureau, 2020 Census Group Quarters release (Aug 2021)",
    notes="Hotels/motels used for transient/worker housing. "
    + _NO_INSTITUTIONAL_SPLIT_PUBLISHED,
)

_HALFWAY_HOUSE = PrevalenceEstimate(
    value=NEUTRAL_FREQUENCY,
    has_public_estimate=False,
    is_direct_measurement=False,
    source="U.S. Census Bureau, 2020 Census Group Quarters release (Aug 2021)",
    notes=(
        "Census classifies halfway houses as 'Correctional Residential "
        "Facilities,' folded into the institutional 'Correctional facilities "
        "for adults' figure (see correctional_institution, 0.59%) rather than "
        "published as its own sub-count. No public split of that 0.59% "
        "figure by facility sub-type exists, so this is left at "
        "NEUTRAL_FREQUENCY rather than guessing a fraction of it."
    ),
)

_GROUP_HOME = PrevalenceEstimate(
    value=NEUTRAL_FREQUENCY,
    has_public_estimate=False,
    is_direct_measurement=False,
    source="U.S. Census Bureau, 2020 Census Group Quarters release (Aug 2021)",
    notes=(
        "Non-correctional adult group homes (e.g. for people with "
        "disabilities). " + _NO_INSTITUTIONAL_SPLIT_PUBLISHED
    ),
)

_MIGRANT_CAMP = PrevalenceEstimate(
    value=NEUTRAL_FREQUENCY,
    has_public_estimate=False,
    is_direct_measurement=False,
    source="U.S. Census Bureau, 2020 Census Group Quarters release (Aug 2021)",
    notes=(
        "Falls under Census's 'workers' group living quarters and Job Corps "
        "centers' sub-type, itself part of the undifferentiated 'Other "
        "noninstitutional facilities' catch-all - see "
        "_NO_INSTITUTIONAL_SPLIT_PUBLISHED. Carolina Population Center's "
        "'Counting farmworkers in the 2020 Census' (2020) discusses "
        "enumeration challenges for this population but publishes no "
        "national prevalence figure either. " + _NO_INSTITUTIONAL_SPLIT_PUBLISHED
    ),
)

# ---------------------------------------------------------------------------
# Household/family structure.
# ---------------------------------------------------------------------------

_MULTI_GENERATIONAL_HOUSEHOLD = PrevalenceEstimate(
    value=0.18,
    has_public_estimate=True,
    is_direct_measurement=True,
    source=(
        "Pew Research Center, 'The Demographics of Multigenerational "
        "Households' (Mar 24, 2022), analysis of Census Bureau Current "
        "Population Survey data"
    ),
    notes=(
        "18% of the U.S. population (59.7 million people) lived in "
        "multigenerational family households as of March 2021, more than "
        "double the 1971 share. Direct measurement of the household "
        "structure this category represents."
    ),
)

# ---------------------------------------------------------------------------
# Name/identity data quality.
# ---------------------------------------------------------------------------

_DIACRITIC = PrevalenceEstimate(
    value=0.20,
    has_public_estimate=True,
    is_direct_measurement=False,
    source="U.S. Census Bureau population estimates (2024)",
    notes=(
        "Hispanic/Latino population was 20% of the total U.S. population as "
        "of July 1, 2024 (68.1 million people), used here as a PROXY for "
        "diacritic-bearing-name prevalence - NOT a direct measurement. "
        "Caveat: many Hispanic-origin individuals' names in U.S. "
        "administrative systems have diacritics stripped or never recorded; "
        "conversely, Vietnamese, Polish, French, and other name origins also "
        "carry diacritics and aren't captured by this figure. No direct "
        "public statistic on '% of administrative-record names containing a "
        "diacritic mark' was found."
    ),
)

_PUNCTUATION = PrevalenceEstimate(
    value=0.06,
    has_public_estimate=True,
    is_direct_measurement=False,
    source=(
        "Gooding & Kreider (U.S. Census Bureau researchers), 'Women's "
        "Marital Naming Choices in a Nationally Representative Sample'"
    ),
    notes=(
        "~6% of native-born married women chose a 'nonconventional' surname "
        "(hyphenated, double surname, or retained maiden name) at marriage - "
        "used here as a PROXY for hyphenated/punctuated-surname prevalence, "
        "NOT a direct measurement. Caveat: conflates hyphenation with other "
        "nonconventional choices (e.g. retaining a maiden name outright, "
        "which introduces no punctuation); covers only married women, not "
        "men, apostrophe surnames (e.g. O'Brien, D'Angelo - no public data "
        "source found for these at all), or non-marital hyphenated birth "
        "surnames common in Hispanic and Portuguese naming conventions (e.g. "
        "Garcia-Lopez). A narrower, less-representative alternative figure "
        "exists (Pew Research Center, Sept 2023: 5% of women in opposite-sex "
        "marriages hyphenated at marriage) - the Gooding & Kreider figure was "
        "chosen as the primary estimate since it's the peer-reviewed Census "
        "Bureau research figure, but both measure the same narrow slice "
        "(married women's choices at marriage), not general surname-"
        "punctuation prevalence across the whole population."
    ),
)

# ---------------------------------------------------------------------------
# Data-entry error categories (fuzzy_variant/*) and hard_negative.
# ---------------------------------------------------------------------------

_NO_PER_EDIT_TYPE_ERROR_RATE = (
    "No public source decomposes patient-record data-entry error rate by "
    "specific edit type (single-character typo vs. adjacent transposition vs. "
    "dropped letters vs. nickname/abbreviation substitution vs. DOB "
    "day/month/year/digit error). The closest available public figures "
    "measure a different, coarser thing - overall cross-record match/"
    "duplication failure, not a single edit's occurrence rate - and aren't "
    "reliable to split evenly across 10 dissimilar categories: Zech et al. "
    "2016 ('Measuring the Degree of Unmatched Patient Records in a Health "
    "Information Exchange', PMC4941843) found ~1.1238 unique identifiers per "
    "exact-match tuple within one health information exchange (~12% implied "
    "split rate), rising to ~1.2862 (~29%) for patients seen across multiple "
    "facilities; Pew Charitable Trusts (2018, citing ONC) commonly cites "
    "real-world cross-organization patient match rates 'as low as 50-60%'. "
    "Both are downstream linkage-failure rates driven by many causes at "
    "once (typos, address changes, missing fields, genuine system "
    "limitations), not a per-edit-type data-entry error rate. Left at "
    "NEUTRAL_FREQUENCY for every fuzzy_variant subtype rather than "
    "fabricating a decomposition this literature doesn't support."
)

_FUZZY_VARIANT_PLACEHOLDER = PrevalenceEstimate(
    value=NEUTRAL_FREQUENCY,
    has_public_estimate=False,
    is_direct_measurement=False,
    source=(
        "Zech et al. 2016 (PMC4941843); Pew Charitable Trusts 2018 "
        "'Enhanced Patient Matching' report citing ONC match-rate figures"
    ),
    notes=_NO_PER_EDIT_TYPE_ERROR_RATE,
)

_HARD_NEGATIVE = PrevalenceEstimate(
    value=NEUTRAL_FREQUENCY,
    has_public_estimate=False,
    is_direct_measurement=False,
    source="N/A",
    notes=(
        "hard_negative represents a coincidental field collision (two "
        "distinct people sharing ZIP+DOB), not a demographic scenario with a "
        "'how common is this' prevalence question in the same sense as the "
        "other categories - it's already governed by this repo's own "
        "P(collision) framework (the reference matching engine's "
        "matching/collision.py per-field u-probabilities), which is the correct tool for "
        "collision-probability questions, not a population-prevalence "
        "estimate. Left at NEUTRAL_FREQUENCY; out of scope for this module."
    ),
)

PREVALENCE_ESTIMATES: Dict[str, PrevalenceEstimate] = {
    "special_population/shelter": _SHELTER,
    "special_population/nursing_facility": _NURSING_FACILITY,
    "special_population/correctional_institution": _CORRECTIONAL_INSTITUTION,
    "special_population/hotel_short_term_housing": _HOTEL_SHORT_TERM_HOUSING,
    "special_population/halfway_house": _HALFWAY_HOUSE,
    "special_population/dormitory": _DORMITORY,
    "special_population/group_home": _GROUP_HOME,
    "special_population/migrant_camp": _MIGRANT_CAMP,
    "special_population/multi_generational_household": _MULTI_GENERATIONAL_HOUSEHOLD,
    "normalization_edge_case/diacritic": _DIACRITIC,
    "normalization_edge_case/punctuation": _PUNCTUATION,
    "hard_negative": _HARD_NEGATIVE,
    "fuzzy_variant/dob_day": _FUZZY_VARIANT_PLACEHOLDER,
    "fuzzy_variant/dob_month": _FUZZY_VARIANT_PLACEHOLDER,
    "fuzzy_variant/dob_year": _FUZZY_VARIANT_PLACEHOLDER,
    "fuzzy_variant/dob_swap": _FUZZY_VARIANT_PLACEHOLDER,
    "fuzzy_variant/dob_typo": _FUZZY_VARIANT_PLACEHOLDER,
    "fuzzy_variant/family_typo": _FUZZY_VARIANT_PLACEHOLDER,
    "fuzzy_variant/family_transpose": _FUZZY_VARIANT_PLACEHOLDER,
    "fuzzy_variant/family_drop_letters": _FUZZY_VARIANT_PLACEHOLDER,
    "fuzzy_variant/given_nickname": _FUZZY_VARIANT_PLACEHOLDER,
    "fuzzy_variant/given_abbreviate": _FUZZY_VARIANT_PLACEHOLDER,
}

# Not assigned to any test-case category (no twin cases are generated - see
# special_populations.py's module docstring and session_10.md's "Out of
# scope" - literal twins are a separate, unresolvable case per the CMS spec
# itself). Recorded here for documentation completeness only, per the
# maintainer's ask about frequency representation in general:
# CDC/NCHS, "Births: Final Data for 2023" (National Vital Statistics
# Reports Vol. 74, No. 1, Mar 18, 2025): 30.7 twin births per 1,000 live
# births in 2023 (~3.07%), down from a peak of ~33.9 per 1,000 in 2014.
TWIN_BIRTH_RATE_PER_1000_LIVE_BIRTHS_2023 = 30.7


def researched_frequency(rationale: str) -> float:
    """A `frequency_lookup` for export_test_dataset.build_test_case_records()
    using this module's researched estimates instead of the neutral default.

    `rationale` strings from format_rationale() sometimes carry parenthetical
    context (e.g. "hard_negative (postalCode=10001, birthDate=1980-01-01)")
    that isn't part of the category key - strip it before looking up. Falls
    back to NEUTRAL_FREQUENCY for any rationale not yet in
    PREVALENCE_ESTIMATES (e.g. a category added later before this module is
    updated for it), rather than raising.
    """
    key = rationale.split(" (")[0]
    estimate = PREVALENCE_ESTIMATES.get(key)
    return estimate.value if estimate is not None else NEUTRAL_FREQUENCY
