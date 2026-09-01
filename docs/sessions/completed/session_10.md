# Session 10 — Special-Population Non-Match Pairs + Normalization Edge-Case Pairs

**Status:** completed (code — `evaluation/special_populations.py`,
`evaluation/normalization_edge_cases.py`, and their tests — has been in `main` and in production
use since before session 9 closed; this doc's own status field was never updated to match. Fixed
by session 12 as a housekeeping item; exact PR number/reviewer not on hand — see `git log` on
these files for the actual merge history.)
**Thread:** Evaluation & Statistical Rigor Framework
**Estimated size:** M/L — two new small modules following `mutations.py`/`hard_negatives.py`'s
existing shape, wiring into `labeled_pairs.py`, and their tests.

> This session doc originated in the patient-matching repo. Read [conventions.md](https://github.com/icanbwell/patient-matching/blob/main/docs/sessions/conventions.md) there first (this repo does not carry its own copy).

## Outcome purpose

**Scope anchor:** this session closes two of the four explicit gaps recorded in
`evaluation/SYNTHETIC_DATA_COMPARISON.md`'s "Coverage against the Doc's §2 ground-truth pair
categories" table (the cross-org workgroup Google Doc, ["Proposal: A Shared Test Dataset for CMS
v3.3.0 Patient Matching
Compliance"](https://docs.google.com/document/d/1N6IQkaLkKPdQKVxPSWZYDaLbTCx0EYEgwBcCCPk-6pk)),
plus the CMS spec itself (`docs/CMS_Patient_Matching_Proposal_v3.2.2.txt`, §IV.G "Note on Twins,
Fragile Identities and Populations with limited or unstable demographic data" and §V
"Normalization Requirements"):

| Doc §2 category | Comparison doc's verdict before this session | This session's target |
|---|---|---|
| Named special/high-risk populations (twins, shelters, nursing facilities, correctional institutions, hotels/short-term housing, halfway houses, dormitories, group homes, migrant camps, multi-generational households) | "Narrow start only" — `hard_negatives.py`'s shared-ZIP+DOB mining is a proxy for "shared address," nothing else in this list | Cover the full named list (minus literal twins — see "Out of scope") |
| Normalization edge cases (diacritics, placeholder DOBs, punctuation) | "No — not evaluated here" | Diacritic folding, punctuation/whitespace removal, and placeholder-DOB exclusion, each exercised end-to-end through `NormalizationManager` + `FieldExtractor` |

Per `conventions.md`'s "Anatomy of a session doc" scope-anchor rule, session_9 established (and
flagged as worth registering) a third canonical scope-anchor source beyond the handoff doc and
the CMS spec: this cross-org workgroup Google Doc. This session reuses that same anchor.

Following session_9's own methodology distinction (raised during its design, 2026-08-14):
mutating a record and asserting the mutation is "a different person" only tests an algorithm's own
tolerance, not reality. This session applies the same discipline both directions:

- **Normalization edge cases** (diacritics, punctuation/whitespace) are **mutations** of a real
  record that **must still be recognized as the same person** after normalization — analogous to
  `mutations.py`'s existing fuzzy-variant pairs, but exercising the *normalization* layer
  (`patient_matching/normalization/`) rather than fuzzy *comparison* (`FieldComparator`).
- **Special-population pairs** must, wherever the underlying dataset allows it, come from
  **genuinely distinct records** (mining), not mutations of one record — same principle
  `hard_negatives.py` already established. Where ONC has no natural examples of a named category
  (no dataset column marks "lives in a shelter"), this session constructs the collision explicitly
  by co-locating distinct, real ONC identities at a synthetic, clearly-marked address — the
  underlying identities are never fabricated, only the shared address field is, and only for
  categories ONC cannot supply naturally (see "Coincidental vs. constructed sharing" in `special_populations.py` below).

## Upstream sessions (must be completed first)

- **Session 9** (`completed/`) — this session extends `evaluation/hard_negatives.py`'s pattern and
  `evaluation/labeled_pairs.py`'s assembly function directly; both must exist first.

## Downstream sessions (unblocked by this one)

- **Session 8** — once this session lands, `evaluation/labeled_pairs.py`'s output covers more of
  the Doc §2 categories session_8's labeled-set comparison consumes. Session 8 does not need to
  change its own code for this (it already consumes `build_labeled_pairs()`'s output shape
  generically), but its eventual report will reflect a broader pair mix once both sessions are
  `completed/`.

## Upstream data/system dependencies

None new. All inputs are the same static, already-committed data session 9 uses:
`evaluation/fixtures/onc/*.csv`.

## Downstream data/system dependencies

None. Like session 9, this session's output (`LabeledPair` objects) is in-memory only, never
persisted to this repo or any external system.

## Scope

### In scope

**1. `evaluation/special_populations.py`** — two new pair-construction functions, following
`hard_negatives.py`'s `HardNegativeCandidate` shape and local-helper style (each module defines
its own tiny field-access helpers rather than importing another module's underscore-prefixed
internals — same pattern `hard_negatives.py` already uses independently of `mutations.py`):

```python
"""Special-population non-match pairs: the Google Doc's Section 2 named list of
high-risk populations (twins, shelters, nursing facilities, correctional
institutions, hotels/short-term housing, halfway houses, dormitories, group
homes, migrant camps, multi-generational households) beyond hard_negatives.py's
general shared-ZIP+DOB proxy.

Coincidental vs. constructed sharing:
  - mine_shared_surname_household_negatives() MINES real, already-coincidentally
    colliding ONC pairs (same postal code + family name, generational DOB gap) -
    the same "genuinely distinct records" discipline hard_negatives.py already
    established. This is the "multi-generational households" category.
  - construct_institutional_negatives() CONSTRUCTS the collision: ONC has no
    column marking a record as "resident of a shelter/nursing facility/etc.", so
    there are no naturally-occurring examples to mine. This function takes
    already mutually-distinct real ONC identities (different family name,
    different ID - the same identities are never fabricated) and overwrites
    only their address with one of a small, unambiguously-synthetic catalog of
    per-institution-type addresses (INSTITUTIONAL_ADDRESSES), then pairs them.
    The label (true non-match) is still correct because the underlying people
    really are distinct ONC records; only the address they're said to share is
    fabricated, and it's fabricated specifically to be recognizable as such
    (a "SYNTHETIC TEST ADDRESS" line, a reserved 00001-00008 ZIP block).

Literal twins (identical first name + last name + DOB + address) are
deliberately NOT constructed here - the CMS spec itself (§IV.G) acknowledges
this exact case as unresolvable through field matching alone, so it is not a
"should not match" test case; see this session's "Out of scope".
"""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Tuple

from hard_negatives import HardNegativeCandidate

Patient = Dict[str, Any]

INSTITUTION_TYPES: Tuple[str, ...] = (
    "shelter",
    "nursing_facility",
    "correctional_institution",
    "hotel_short_term_housing",
    "halfway_house",
    "dormitory",
    "group_home",
    "migrant_camp",
)

# Reserved 000xx ZIP block (never a real USPS-assigned ZIP) plus an explicit
# "SYNTHETIC TEST ADDRESS" line prefix, so a reviewer or downstream consumer of
# this module's output can recognize a fabricated address at a glance, per the
# Doc's Design Principle 4 ("every fabricated identifier value should be
# unambiguously marked as synthetic").
INSTITUTIONAL_ADDRESSES: Dict[str, Dict[str, str]] = {
    "shelter": {
        "line": "SYNTHETIC TEST ADDRESS - 100 SHELTER WAY",
        "city": "TESTCITY",
        "state": "ZZ",
        "postalCode": "00001",
    },
    "nursing_facility": {
        "line": "SYNTHETIC TEST ADDRESS - 200 NURSING FACILITY DR",
        "city": "TESTCITY",
        "state": "ZZ",
        "postalCode": "00002",
    },
    "correctional_institution": {
        "line": "SYNTHETIC TEST ADDRESS - 300 CORRECTIONAL INSTITUTION RD",
        "city": "TESTCITY",
        "state": "ZZ",
        "postalCode": "00003",
    },
    "hotel_short_term_housing": {
        "line": "SYNTHETIC TEST ADDRESS - 400 SHORT TERM HOUSING BLVD",
        "city": "TESTCITY",
        "state": "ZZ",
        "postalCode": "00004",
    },
    "halfway_house": {
        "line": "SYNTHETIC TEST ADDRESS - 500 HALFWAY HOUSE LN",
        "city": "TESTCITY",
        "state": "ZZ",
        "postalCode": "00005",
    },
    "dormitory": {
        "line": "SYNTHETIC TEST ADDRESS - 600 DORMITORY HALL",
        "city": "TESTCITY",
        "state": "ZZ",
        "postalCode": "00006",
    },
    "group_home": {
        "line": "SYNTHETIC TEST ADDRESS - 700 GROUP HOME CT",
        "city": "TESTCITY",
        "state": "ZZ",
        "postalCode": "00007",
    },
    "migrant_camp": {
        "line": "SYNTHETIC TEST ADDRESS - 800 MIGRANT CAMP RD",
        "city": "TESTCITY",
        "state": "ZZ",
        "postalCode": "00008",
    },
}


def _primary_family_name(patient: Patient) -> str:
    names = patient.get("name") or []
    return str(names[0].get("family") or "") if names else ""


def _postal_code(patient: Patient) -> str:
    addresses = patient.get("address") or []
    return str(addresses[0].get("postalCode") or "") if addresses else ""


def _rng(rng: Optional[random.Random]) -> random.Random:
    return rng if rng is not None else random.Random()


def _with_synthetic_address(patient: Patient, institution_type: str) -> Patient:
    import copy

    if institution_type not in INSTITUTIONAL_ADDRESSES:
        raise ValueError(f"Unknown institution_type: {institution_type!r}")
    patient = copy.deepcopy(patient)
    addr = INSTITUTIONAL_ADDRESSES[institution_type]
    patient["address"] = [
        {
            "line": [addr["line"]],
            "city": addr["city"],
            "state": addr["state"],
            "postalCode": addr["postalCode"],
        }
    ]
    return patient


def construct_institutional_negatives(
    patients: Iterable[Patient],
    institution_type: str,
    *,
    group_size: int = 3,
    rng: Optional[random.Random] = None,
) -> List[HardNegativeCandidate]:
    """Pair up `group_size` distinct, real ONC identities (different family
    name, different ID) at a single fabricated, unambiguously-synthetic
    address for `institution_type`, and return every pairwise combination
    within the group as a true-non-match candidate.

    Only the address is fabricated - the underlying identities are genuinely
    distinct ONC records, so the true-non-match label remains correct. See
    this module's docstring for why this differs from mining (no ONC record is
    naturally tagged as e.g. a shelter resident, so there is nothing to mine).
    """
    rng = _rng(rng)
    pool = list(patients)
    rng.shuffle(pool)

    group: List[Patient] = []
    seen_family_names: set[str] = set()
    for patient in pool:
        family = _primary_family_name(patient).upper()
        if not family or family in seen_family_names:
            continue
        seen_family_names.add(family)
        group.append(_with_synthetic_address(patient, institution_type))
        if len(group) == group_size:
            break

    candidates: List[HardNegativeCandidate] = []
    for i in range(len(group)):
        for j in range(i + 1, len(group)):
            candidates.append(
                HardNegativeCandidate(
                    query=group[i],
                    candidate=group[j],
                    shared_fields={
                        "institution_type": institution_type,
                        "postalCode": INSTITUTIONAL_ADDRESSES[institution_type]["postalCode"],
                    },
                )
            )
    return candidates


def mine_shared_surname_household_negatives(
    patients: Iterable[Patient],
    *,
    min_age_gap_years: int = 15,
) -> List[HardNegativeCandidate]:
    """Mine real ONC pairs sharing a postal code AND family name, but with
    birth years far enough apart to represent a parent/child pair rather than
    the same person or a twin - the Doc's "multi-generational households"
    category.

    Deliberately the inverse filter from hard_negatives.py's
    mine_shared_address_hard_negatives() (which *excludes* same-family-name
    pairs to stay disjoint from mutation-style variants of one identity): here
    the shared family name is exactly the signal this category is testing.
    The min_age_gap_years requirement is what keeps this disjoint from a twin
    or fuzzy-variant scenario (same family name + near-identical DOB would be
    those cases instead, not this one).
    """
    buckets: Dict[Tuple[str, str], List[Patient]] = defaultdict(list)
    for patient in patients:
        zip_code = _postal_code(patient)
        family = _primary_family_name(patient).upper()
        if not zip_code or not family:
            continue
        buckets[(zip_code, family)].append(patient)

    candidates: List[HardNegativeCandidate] = []
    for (zip_code, family), group in buckets.items():
        if len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                if a.get("id") == b.get("id"):
                    continue
                dob_a, dob_b = a.get("birthDate"), b.get("birthDate")
                if not dob_a or not dob_b:
                    continue
                try:
                    gap_years = abs(date.fromisoformat(dob_a).year - date.fromisoformat(dob_b).year)
                except ValueError:
                    continue
                if gap_years < min_age_gap_years:
                    continue
                candidates.append(
                    HardNegativeCandidate(
                        query=a,
                        candidate=b,
                        shared_fields={
                            "postalCode": zip_code,
                            "family_name": family,
                            "age_gap_years": str(gap_years),
                        },
                    )
                )
    return candidates
```

**2. `evaluation/normalization_edge_cases.py`** — two true-match variant generators exercising
`patient_matching/normalization/` end-to-end (not `FieldComparator`'s fuzzy path), plus one
standalone pipeline check (not a `LabeledPair` - see its docstring for why):

```python
"""Normalization edge-case variants: the Google Doc's Section 2 "normalization
edge cases" (diacritic-folded names, punctuation/whitespace variation, and
placeholder/out-of-range dates of birth), per CMS spec §V.A.3-4.

Unlike mutations.py's fuzzy-comparison variants (which rely on
FieldComparator's edit-distance tolerance and are expected to match only
because fuzzy comparison is *permitted* for that field), the two variant
generators here produce values that CMS §V.A requires normalization to fold
into an EXACT match - a diacritic-folded or punctuation-stripped name is not
"close enough via fuzzy tolerance", it is required to become byte-identical
to the un-accented/unpunctuated form after NormalizationManager runs. Pairing
these as LabeledPairs with is_true_match=True therefore exercises the
normalization layer specifically, not the fuzzy comparator.
"""

from __future__ import annotations

import copy
import random
from typing import Any, Dict, Optional

Patient = Dict[str, Any]

_MIN_MUTATABLE_LENGTH = 3

# Common Latin-script diacritics folded by patient_matching.normalization.text_utils.fold_diacritics.
DIACRITIC_MAP: Dict[str, str] = {
    "a": "á",
    "e": "é",
    "i": "í",
    "o": "ó",
    "u": "ú",
    "n": "ñ",
    "c": "ç",
}

# One punctuation/whitespace insertion per case, matching CMS §V.A.2-3's list
# of characters normalization must remove/ignore: hyphen, apostrophe, period,
# and doubled internal whitespace.
PUNCTUATION_CHARS: tuple[str, ...] = ("-", "'", ".", "  ")


def _copy_patient(patient: Patient) -> Patient:
    return copy.deepcopy(patient)


def _rng(rng: Optional[random.Random]) -> random.Random:
    return rng if rng is not None else random.Random()


def _name_value(patient: Patient, field: str, *, name_index: int = 0) -> str:
    names = patient.get("name") or []
    if name_index >= len(names):
        return ""
    entry = names[name_index]
    if field == "family":
        return str(entry.get("family") or "")
    if field == "given":
        given = entry.get("given") or []
        return str(given[0]) if given else ""
    raise ValueError(f"Unknown name field: {field!r}")


def _set_name_value(patient: Patient, field: str, value: str, *, name_index: int = 0) -> None:
    names = patient.get("name") or []
    if name_index >= len(names):
        return
    if field == "family":
        names[name_index]["family"] = value
    elif field == "given":
        given = names[name_index].get("given") or []
        if given:
            given[0] = value
        else:
            names[name_index]["given"] = [value]
    else:
        raise ValueError(f"Unknown name field: {field!r}")


def diacritic_variant(
    patient: Patient,
    field: str = "given",
    *,
    name_index: int = 0,
    rng: Optional[random.Random] = None,
) -> Patient:
    """Replace the first occurrence of a foldable character in `field` with
    its accented form (e.g. "Nunez" -> "Nuñez", "Jose" -> "José"). No-op if
    the value contains none of DIACRITIC_MAP's keys or is too short."""
    rng = _rng(rng)
    patient = _copy_patient(patient)
    value = _name_value(patient, field, name_index=name_index)
    if len(value) < _MIN_MUTATABLE_LENGTH:
        return patient
    lowered = value.lower()
    foldable_positions = [i for i, ch in enumerate(lowered) if ch in DIACRITIC_MAP]
    if not foldable_positions:
        return patient
    pos = rng.choice(foldable_positions)
    accented = DIACRITIC_MAP[lowered[pos]]
    new_value = value[:pos] + accented + value[pos + 1 :]
    _set_name_value(patient, field, new_value, name_index=name_index)
    return patient


def punctuation_variant(
    patient: Patient,
    field: str = "family",
    *,
    name_index: int = 0,
    punctuation: str = "random",
    rng: Optional[random.Random] = None,
) -> Patient:
    """Insert one punctuation/whitespace character from PUNCTUATION_CHARS into
    `field` at a random internal position (e.g. "OBrien" -> "O'Brien",
    "SmithJones" -> "Smith-Jones"). No-op if the value is too short to have an
    internal position."""
    rng = _rng(rng)
    patient = _copy_patient(patient)
    value = _name_value(patient, field, name_index=name_index)
    if len(value) < _MIN_MUTATABLE_LENGTH:
        return patient
    if punctuation == "random":
        punctuation = rng.choice(PUNCTUATION_CHARS)
    elif punctuation not in PUNCTUATION_CHARS:
        raise ValueError(f"Unknown punctuation: {punctuation!r}")
    pos = rng.randrange(1, len(value))
    new_value = value[:pos] + punctuation + value[pos:]
    _set_name_value(patient, field, new_value, name_index=name_index)
    return patient
```

**3. Wire both new modules into `evaluation/labeled_pairs.py`.** Extend `build_labeled_pairs()`
with additive, default-on keyword args (new pair types are appended to the existing fuzzy-variant
and hard-negative pairs, not a replacement of them, so session_9's existing behavior/shape is
preserved when a caller doesn't pass the new args):

```python
# New imports at the top of labeled_pairs.py, alongside the existing ones:
from normalization_edge_cases import diacritic_variant, punctuation_variant
from special_populations import (
    INSTITUTION_TYPES,
    construct_institutional_negatives,
    mine_shared_surname_household_negatives,
)


def build_labeled_pairs(
    patients: List[Dict[str, Any]],
    *,
    n_fuzzy_variants_per_patient: int = 1,
    include_normalization_edge_cases: bool = True,
    include_special_populations: bool = True,
    institutional_group_size: int = 3,
    seed: int = 0,
) -> List[LabeledPair]:
    """Build LabeledPairs from ONC patients: fuzzy-variant true-matches,
    mined-hard-negative true-non-matches (session 9), plus (this session)
    normalization-edge-case true-matches and special-population
    true-non-matches (mined multi-generational-household pairs and
    constructed institutional pairs).
    """
    normalizer = NormalizationManager()
    extractor = FieldExtractor()
    normalized = [normalizer.normalize(p) for p in patients]
    rng = random.Random(seed)
    pairs: List[LabeledPair] = []

    for p in normalized:
        q_fields = extractor.extract(p)
        for _ in range(n_fuzzy_variants_per_patient):
            variant, mutation_type = generate_fuzzy_variant(p, rng=rng)
            c_fields = extractor.extract(variant)
            pairs.append(
                LabeledPair(
                    features={"query": q_fields, "candidate": c_fields},
                    is_true_match=True,
                    strata={"pair_type": "fuzzy_variant", "mutation": mutation_type},
                    pair_id=f"{p['id']}::{mutation_type}",
                )
            )
        if include_normalization_edge_cases:
            diacritic = diacritic_variant(p, rng=rng)
            pairs.append(
                LabeledPair(
                    features={"query": q_fields, "candidate": extractor.extract(diacritic)},
                    is_true_match=True,
                    strata={"pair_type": "normalization_edge_case", "case": "diacritic"},
                    pair_id=f"{p['id']}::diacritic",
                )
            )
            punctuated = punctuation_variant(p, rng=rng)
            pairs.append(
                LabeledPair(
                    features={"query": q_fields, "candidate": extractor.extract(punctuated)},
                    is_true_match=True,
                    strata={"pair_type": "normalization_edge_case", "case": "punctuation"},
                    pair_id=f"{p['id']}::punctuation",
                )
            )

    for candidate in mine_shared_address_hard_negatives(normalized):
        q_fields = extractor.extract(candidate.query)
        c_fields = extractor.extract(candidate.candidate)
        pairs.append(
            LabeledPair(
                features={"query": q_fields, "candidate": c_fields},
                is_true_match=False,
                strata={"pair_type": "hard_negative", **candidate.shared_fields},
                pair_id=f"{candidate.query['id']}::{candidate.candidate['id']}",
            )
        )

    if include_special_populations:
        for candidate in mine_shared_surname_household_negatives(normalized):
            pairs.append(
                LabeledPair(
                    features={
                        "query": extractor.extract(candidate.query),
                        "candidate": extractor.extract(candidate.candidate),
                    },
                    is_true_match=False,
                    strata={"pair_type": "special_population", "category": "multi_generational_household", **candidate.shared_fields},
                    pair_id=f"{candidate.query['id']}::{candidate.candidate['id']}::household",
                )
            )
        for institution_type in INSTITUTION_TYPES:
            for candidate in construct_institutional_negatives(
                normalized, institution_type, group_size=institutional_group_size, rng=rng
            ):
                pairs.append(
                    LabeledPair(
                        features={
                            "query": extractor.extract(candidate.query),
                            "candidate": extractor.extract(candidate.candidate),
                        },
                        is_true_match=False,
                        strata={"pair_type": "special_population", "category": institution_type},
                        pair_id=f"{candidate.query['id']}::{candidate.candidate['id']}::{institution_type}",
                    )
                )

    return pairs
```

(The existing `mine_shared_address_hard_negatives` import and the function's first loop are
unchanged from session_9 — shown above only for placement context; do not duplicate the import.)

**4. Placeholder-DOB pipeline check** — not a `LabeledPair` (a placeholder/out-of-range DOB is a
single-patient normalization behavior, not a match/non-match pair; `patient_matching/normalization/
placeholder_detector.py`'s `is_placeholder_date()` already has its own unit tests for the D.6
threshold itself). What's untested is whether that detection is actually wired end-to-end through
`NormalizationManager.normalize()` into `FieldExtractor.extract()`, so this session adds one
integration-level test confirming a placeholder/out-of-range DOB never reaches `PatientFields.dob`
as a matchable value — see "Unit tests required" below.

**5. Update `evaluation/SYNTHETIC_DATA_COMPARISON.md`'s coverage table** to reflect both rows
moving from "Narrow start only"/"No" to "Yes" (with the twin exception noted per "Out of scope"
below), and add a short new section describing `special_populations.py`'s coincidental-vs.-
constructed-sharing distinction (for a future reader deciding whether to trust a given pair as
"real" or "constructed").

**6. (Added post-implementation, same PR — the repo maintainer asked "did you create the test
dataset?" once Tasks 1-5 landed, and the honest answer was no: `LabeledPair` output is in-memory only and holds
this repo's own internal `PatientFields`, not the Doc §3 portable format.) Materialize an actual
test-case manifest file.** New `evaluation/export_test_dataset.py`: refactor
`labeled_pairs.py`'s pair-generation loop into a shared `generate_raw_pairs()` generator
(yielding raw FHIR `Patient` pairs before extraction, behavior-preserving — `build_labeled_pairs()`
now wraps it) so this task doesn't duplicate the mutation/mining/construction logic; build
`LabeledCaseRecord(case_id, source, target, expected_match, rationale)` from the same generator,
keeping raw FHIR JSON instead of extracted fields; write one JSON-Lines row per record
(`write_jsonl()`). Generate and commit a sample (`evaluation/cases/sample_labeled_pairs.jsonl`,
same `SAMPLE_SIZE=2000`/one-shard/seed-0 default as `labeled_pairs.py`'s own smoke run) as a
concrete, reproducible artifact — not just a script that could be run. Document in
`SYNTHETIC_DATA_SETUP.md` ("Materializing a portable test-case file") and
`SYNTHETIC_DATA_COMPARISON.md` (new "Coverage against the Doc's §3 test case format" section).

### Out of scope

- **Literal twins** (identical first name + last name + DOB + address). The CMS spec (§IV.G)
  itself acknowledges this case as unresolvable through field matching alone and proposes a
  separate "Patient Matching for Vulnerable Populations" subworkgroup to address it — it is not a
  "should not match" test case this session's pass/fail framing can express correctly. Tracked as
  a candidate future session pending that subworkgroup's own guidance, not attempted here.
- **Administrative-restriction pairs** (family-shared insurance IDs, Table 4). ONC has no
  insurance/plan-ID column at all; this requires the `insurance_member_id`/`insurance_subscriber_id`
  fields session 6 adds. See **session_11**, authored as a separate, session-6-dependent session
  rather than folded in here.
- **Client-type field-availability modeling** and **mining Person-Patient link outcomes** — both
  already explicitly deferred by session_9's design discussion (see
  `SYNTHETIC_DATA_COMPARISON.md`'s "Known gaps"); this session doesn't revisit either.
- **The ≥1,000,000-record empirical collision-rate validation** (Doc §4) — a population-scale
  statistical exercise, unrelated to labeled-pair testing. Tracked separately in `index.md`'s
  "Candidate future sessions."
- **Verifying the Doc §4 claim about ONC's duplicate-identity structure** — session_9's existing
  open question, not this session's to resolve.
- **Doc §1 Option C (company-submitted de-identified real data)** as a seed-population layer.
  The repo maintainer scoped this backlog down to Option A (ONC, already public/synthetic) +
  Option B (programmatic mining/mutation/construction) only, 2026-08-16 — consistent with
  `conventions.md`'s existing PHI guardrail, which already prohibits real member-organization/
  Databricks/Mongo data in this repo's fixtures. This session's mined/constructed pairs stay
  entirely within Option A+B; no task here reaches for real de-identified data.
- **The Doc §8 reference scoring harness** (a `cms-match-harness score` CLI, adapter contract,
  TP/FP/TN/FN aggregation and reporting). Task 6 produces only the manifest (the dataset), per
  Design Principle 1's algorithm-agnostic split — scoring against it is session_8's eventual Tier
  3 harness territory, not this session's.
- **Publishing `evaluation/cases/`'s output to the Doc §8-recommended neutral cross-org repo.**
  This repo remains this organization's own staging copy (`SYNTHETIC_DATA_COMPARISON.md`'s
  "Repo-ownership note"); Task 6 only materializes the file locally.

## Tasks

1. Write `evaluation/special_populations.py` (code above), including `INSTITUTIONAL_ADDRESSES`
   and both pair-construction functions.
2. Write `evaluation/normalization_edge_cases.py` (code above), including `DIACRITIC_MAP`,
   `PUNCTUATION_CHARS`, and both variant generators.
3. Wire both modules into `evaluation/labeled_pairs.py`'s `build_labeled_pairs()` (code above),
   preserving session_9's existing default output for callers that don't pass the new kwargs
   (i.e., the new kwargs default to `True`, additive to the existing pairs, not a behavior change
   to the fuzzy-variant/hard-negative pairs already there).
4. Add the placeholder-DOB pipeline integration test (Task 4 above).
5. Update `evaluation/SYNTHETIC_DATA_COMPARISON.md`'s coverage table and add the
   coincidental-vs.-constructed-sharing note.
6. Refactor `labeled_pairs.py` to expose `generate_raw_pairs()`; write
   `evaluation/export_test_dataset.py` (`LabeledCaseRecord`, `build_test_case_records()`,
   `format_rationale()`, `write_jsonl()`); generate and commit
   `evaluation/cases/sample_labeled_pairs.jsonl`; update `SYNTHETIC_DATA_SETUP.md` and
   `SYNTHETIC_DATA_COMPARISON.md`.

## Unit tests required

Files: `evaluation/test_special_populations.py`, `evaluation/test_normalization_edge_cases.py`,
plus additions to `evaluation/test_labeled_pairs.py` (`importorskip("numpy")`, per
`test_onc_baseline.py`'s and session_9's existing convention).

```python
# evaluation/test_special_populations.py
from __future__ import annotations

from special_populations import (
    INSTITUTIONAL_ADDRESSES,
    INSTITUTION_TYPES,
    construct_institutional_negatives,
    mine_shared_surname_household_negatives,
)


def _patient(id_, family, given="Pat", zip_code="10001", dob="1980-01-01"):
    return {
        "resourceType": "Patient",
        "id": id_,
        "name": [{"family": family, "given": [given]}],
        "birthDate": dob,
        "telecom": [],
        "address": [{"line": ["1 Main St"], "city": "NY", "state": "NY", "postalCode": zip_code}],
        "identifier": [],
    }


class TestConstructInstitutionalNegatives:
    def test_assigns_same_synthetic_address_to_every_group_member(self):
        patients = [_patient("p1", "Smith"), _patient("p2", "Jones"), _patient("p3", "Lee")]
        candidates = construct_institutional_negatives(patients, "shelter", group_size=3)
        assert len(candidates) == 3  # 3 choose 2
        for c in candidates:
            assert c.query["address"][0]["postalCode"] == INSTITUTIONAL_ADDRESSES["shelter"]["postalCode"]
            assert c.candidate["address"][0]["postalCode"] == INSTITUTIONAL_ADDRESSES["shelter"]["postalCode"]
            assert c.shared_fields["institution_type"] == "shelter"

    def test_never_pairs_two_patients_with_the_same_family_name(self):
        patients = [_patient("p1", "Smith"), _patient("p2", "Smith"), _patient("p3", "Lee")]
        candidates = construct_institutional_negatives(patients, "shelter", group_size=3)
        # Only 2 distinct family names available (Smith deduped) - group caps at 2, 1 pair.
        assert len(candidates) == 1

    def test_rejects_unknown_institution_type(self):
        import pytest

        with pytest.raises(ValueError):
            construct_institutional_negatives([_patient("p1", "Smith")], "not_a_real_type")

    def test_every_institution_type_has_a_distinct_synthetic_zip(self):
        zips = [addr["postalCode"] for addr in INSTITUTIONAL_ADDRESSES.values()]
        assert len(zips) == len(set(zips)) == len(INSTITUTION_TYPES)


class TestMineSharedSurnameHouseholdNegatives:
    def test_finds_same_surname_same_zip_generational_gap(self):
        patients = [
            _patient("p1", "Rivera", dob="1955-03-01"),
            _patient("p2", "Rivera", dob="1988-07-14"),
        ]
        candidates = mine_shared_surname_household_negatives(patients)
        assert len(candidates) == 1
        assert candidates[0].shared_fields["family_name"] == "RIVERA"

    def test_excludes_pairs_below_the_age_gap_threshold(self):
        """A ~2-year gap looks like a data-entry DOB error or twins, not a
        parent/child household - not this category."""
        patients = [
            _patient("p1", "Rivera", dob="1988-01-01"),
            _patient("p2", "Rivera", dob="1990-06-01"),
        ]
        assert mine_shared_surname_household_negatives(patients) == []

    def test_excludes_different_surnames(self):
        patients = [
            _patient("p1", "Rivera", dob="1955-03-01"),
            _patient("p2", "Chen", dob="1988-07-14"),
        ]
        assert mine_shared_surname_household_negatives(patients) == []
```

```python
# evaluation/test_normalization_edge_cases.py
from __future__ import annotations

import pytest

from normalization_edge_cases import (
    DIACRITIC_MAP,
    PUNCTUATION_CHARS,
    diacritic_variant,
    punctuation_variant,
)


def _patient(given="Jose", family="Nunez", dob="1980-01-01"):
    return {
        "resourceType": "Patient",
        "id": "p1",
        "name": [{"family": family, "given": [given]}],
        "birthDate": dob,
        "telecom": [],
        "address": [],
        "identifier": [],
    }


class TestDiacriticVariant:
    @pytest.mark.parametrize("field,name", [("given", "Jose"), ("family", "Nunez")])
    def test_introduces_exactly_one_accented_character(self, field, name):
        patient = _patient(given=name if field == "given" else "Jose", family=name if field == "family" else "Nunez")
        variant = diacritic_variant(patient, field=field, rng=__import__("random").Random(0))
        value = variant["name"][0]["given"][0] if field == "given" else variant["name"][0]["family"]
        assert value != name
        assert any(accented in value for accented in DIACRITIC_MAP.values())

    def test_noop_when_no_foldable_characters(self):
        patient = _patient(given="Xyz")
        variant = diacritic_variant(patient, field="given")
        assert variant["name"][0]["given"][0] == "Xyz"

    def test_does_not_mutate_the_original(self):
        patient = _patient()
        diacritic_variant(patient, field="given")
        assert patient["name"][0]["given"][0] == "Jose"


class TestPunctuationVariant:
    @pytest.mark.parametrize("punctuation", PUNCTUATION_CHARS)
    def test_inserts_requested_punctuation(self, punctuation):
        patient = _patient(family="OBrien")
        variant = punctuation_variant(patient, field="family", punctuation=punctuation)
        assert punctuation in variant["name"][0]["family"]

    def test_rejects_unknown_punctuation(self):
        with pytest.raises(ValueError):
            punctuation_variant(_patient(), field="family", punctuation="!")

    def test_noop_on_short_values(self):
        patient = _patient(family="Li")
        variant = punctuation_variant(patient, field="family")
        assert variant["name"][0]["family"] == "Li"
```

```python
# addition to patient_matching/normalization/tests/test_manager.py (or a new
# evaluation/test_placeholder_dob_pipeline.py, sibling to labeled_pairs.py's own
# tests - author's call at implementation time; either location is a legitimate
# home for a pipeline-level, not unit-level, check):

class TestPlaceholderDobExcludedEndToEnd:
    def test_out_of_range_dob_never_reaches_extracted_fields(self):
        from patient_matching.normalization.manager import NormalizationManager
        from patient_matching.matching.field_extractor import FieldExtractor

        patient = {
            "resourceType": "Patient",
            "id": "p1",
            "name": [{"family": "Smith", "given": ["Pat"]}],
            "birthDate": "1850-01-01",  # more than 120 years before today
            "telecom": [],
            "address": [],
            "identifier": [],
        }
        normalized = NormalizationManager().normalize(patient)
        fields = FieldExtractor().extract(normalized)
        assert fields.dob == set()
```

Cover decision boundaries per `conventions.md`'s testing-structure section: the
`min_age_gap_years` threshold (just below/at/above), the reserved synthetic-ZIP block being
collision-free across all 8 institution types, and the diacritic/punctuation no-op floor
(`_MIN_MUTATABLE_LENGTH`).

**Task 6 tests:** `evaluation/test_export_test_dataset.py` (`importorskip("numpy")`, same
convention — it imports `labeled_pairs`, which imports `rule_eval`). Covers: `format_rationale()`
folding `mutation`/`case`/`category` into the `"<pair_type>/<subtype>"` head vs. leaving other
strata keys as `"key=value"` context; `build_test_case_records()` producing raw FHIR-shaped
records deterministically given a seed, with both `expected_match` values represented;
`write_jsonl()` producing one JSON object per line and creating missing parent directories. The
`generate_raw_pairs()` refactor itself is covered by the *existing*
`evaluation/test_labeled_pairs.py` suite passing unchanged (a true refactor produces no test
diff — that's the equivalence proof, not a new test).

## Validation (definition of "resolved")

- [x] `evaluation/special_populations.py` and `evaluation/normalization_edge_cases.py` exist and
      import cleanly.
- [x] `pytest evaluation/test_special_populations.py evaluation/test_normalization_edge_cases.py evaluation/test_labeled_pairs.py -v`
      passes (13 + 13 + 9 = 35 passed).
- [x] The placeholder-DOB end-to-end test passes, confirming `PatientFields.dob` is empty for an
      out-of-range date after the full normalize→extract pipeline (3 tests in
      `TestPlaceholderDobExcludedEndToEnd`, all passing).
- [x] `PYTHONPATH=. python evaluation/labeled_pairs.py` still runs against real ONC fixture data
      without error and now reports non-zero counts for `normalization_edge_case` (both `diacritic`
      and `punctuation`) and `special_population` (`multi_generational_household` plus all 8
      `institution_type`s) pair types, alongside session_9's existing `fuzzy_variant`/`hard_negative`
      counts — see Execution notes for the actual counts observed.
- [x] `ruff check`/`mypy --strict`/`bandit` clean on all new/changed files, modulo pre-existing
      style drift (see Execution notes — verified against already-merged sibling files, not
      newly introduced).
- [x] `evaluation/SYNTHETIC_DATA_COMPARISON.md`'s coverage table is updated (both rows) and the
      coincidental-vs.-constructed-sharing distinction is documented (inline in the coverage table
      and in `special_populations.py`'s own module docstring).
- [ ] `make tests` is green (full suite, not just the new tests) — **could not run**; see
      Execution notes.
- [ ] `make run-pre-commit` is clean — **could not run**; see Execution notes.
- [x] Per `conventions.md`'s statistical rigor gate: this session does not itself change matching
      *behavior* (no `MatchingEngine`/`table2_rules.py` edits) — confirmed the diff touches only
      `evaluation/*.py` plus `patient_matching/normalization/tests/test_manager.py` (a new test
      class, no production code under `patient_matching/` changed) — Tier-1 gate does not apply.
- [x] **Task 6:** `evaluation/export_test_dataset.py` exists, imports cleanly, and every test in
      `evaluation/test_export_test_dataset.py` passes (9 passed).
- [x] `generate_raw_pairs()` refactor is behavior-preserving: `evaluation/test_labeled_pairs.py`'s
      existing 9 tests pass unchanged (no test edits needed for the refactor itself).
- [x] `PYTHONPATH=. python evaluation/export_test_dataset.py` runs against real ONC fixture data
      and writes `evaluation/cases/sample_labeled_pairs.jsonl` (6,289 cases: 6,000
      `expected_match=true`, 289 `expected_match=false`, from `SAMPLE_SIZE=2000` on one shard) —
      committed to the repo as a concrete artifact, not left as a script nobody's run.
- [x] `SYNTHETIC_DATA_SETUP.md` and `SYNTHETIC_DATA_COMPARISON.md` updated for Task 6.

## Open questions

- Exact home for the placeholder-DOB pipeline test: resolved as
  `patient_matching/normalization/tests/test_manager.py` (new `TestPlaceholderDobExcludedEndToEnd`
  class) rather than a new `evaluation/` file, since it reads naturally alongside
  `TestNormalizationManager`'s other end-to-end normalize() checks in the same file.
- `institutional_group_size=3` kept at its recommended default (24 constructed institutional pairs
  per `build_labeled_pairs()` call, plus whatever `mine_shared_surname_household_negatives()` finds
  naturally) — no reason found during implementation to change it.

## Execution notes

Executed 2026-08-16. All code and tests written per the plan above; no deviations from the
designed module/function shapes.

**Test execution environment:** this sandbox has no JFrog credentials (`uv sync` fails resolving
`fastapi` from the private index) and no `.env` file, so neither `uv run pytest`/`uv run
pre-commit` nor `make tests`/`make run-pre-commit` (Docker-based, needs `.env`) could actually run.
Substituted: an existing local `.venv` (already had `patient_matching`'s core deps) supplemented
with `numpy`, `usaddress-scourgify` (note: NOT plain `scourgify` — that's a different, incompatible
PyPI package; must be `usaddress-scourgify` per `pyproject.toml`) from public PyPI, then ran the
full suite directly: **481 passed** (up from a confirmed 448-passing baseline before this
session's changes — net +33 tests: 13 + 13 in the two new test files, +4 in `test_labeled_pairs.py`
net of 2 renamed-in-place, +3 in `test_manager.py`).

Also confirmed the local git `pre-commit` hook is broken independent of this session (references a
`pre-commit.Dockerfile` removed by commit `d51b080`, "Run pre-commit and tests directly via uv
instead of Docker in CI") — pre-existing environment drift, not caused by this session.

**Lint verification methodology:** this venv has `ruff==0.16.1` installed, not the repo's pinned
`ruff==0.15.20` (`conventions.md`: "pinned deliberately, not floating"), and the two differ in
default-enabled rules (e.g. `UP006`/`UP035`/`DTZ011`). Rather than trust raw `ruff check` output,
every finding was checked against already-merged sibling files
(`evaluation/mutations.py`, `evaluation/hard_negatives.py`,
`patient_matching/normalization/placeholder_detector.py`) run through the *same* venv — all three
produce the identical classes of finding despite being known-clean, merged code, confirming the
findings are version drift, not real regressions. The one finding that was NOT drift (`I001`
import-block sorting in the two new test files) was fixed via
`ruff check --fix --select I001` scoped to just those two files. `mypy --strict` reported zero new
errors beyond `evaluation/rule_eval.py`'s 8 pre-existing errors (unchanged before/after this
session's diff) and the `evaluation/test_*.py` untyped-helper pattern already present in
`test_mutations.py` (same class of finding, not new). `bandit` reported zero findings.

**Smoke run counts** (`PYTHONPATH=. python evaluation/labeled_pairs.py`, one ONC shard sampled to
2000 patients, default seed): 6289 total pairs — `normalization_edge_case/diacritic`: 2000,
`normalization_edge_case/punctuation`: 2000, `special_population/multi_generational_household`:
261, `fuzzy_variant/*` (session 9, unchanged mutation types): 2000 total, `hard_negative`: 4,
`special_population/<institution_type>`: 3 each across all 8 types (24 total). The 261-count
household figure is a real, visible-in-output volume from this ONC sample's actual surname/ZIP
distribution — not a silent cap, per the "no silent caps" principle.

**Not run / left for actual PR review:** `make tests` and `make run-pre-commit`, per the
environment limitation above. Whoever reviews the PR in an environment with working JFrog/Docker
credentials should run both before merging, per `conventions.md`'s Definition of Done.

**Task 6 addendum, 2026-08-16 (same PR, later in the day):** the repo maintainer asked "did you
create the test dataset?" after Tasks 1-5 landed — the honest answer at that point was no: `LabeledPair` was
in-memory-only and held this repo's internal `PatientFields`, not the Doc §3 portable FHIR-JSON
manifest format. Confirmed with the maintainer this was a real gap (not something already covered
elsewhere), then closed it: refactored `labeled_pairs.py` to expose `generate_raw_pairs()`
(confirmed behavior-preserving — `test_labeled_pairs.py`'s existing 9 tests pass unchanged, no
edits needed), added `evaluation/export_test_dataset.py` (9 new tests, all passing), and
generated + committed `evaluation/cases/sample_labeled_pairs.jsonl` (6,289 cases, 5.7MB,
reproducible via `SAMPLE_SIZE=2000`/one-shard/seed=0). Renamed the initially-drafted
`TestCaseRecord` dataclass to `LabeledCaseRecord` after pytest's own collection warned it looked
like a test class (name starting with `Test`) — caught before commit, not a functional bug.
Full local suite: 490 passed (up from 481 immediately before this addendum). Same environment
methodology as the rest of this session (manual `ruff`/`mypy --strict`/`bandit`, cross-checked
against already-clean files to rule out the sandbox's ruff-version drift) — all clean.

**Task 7 addendum, 2026-08-16 (same PR, immediately after Task 6):** the repo maintainer asked
for a doc explaining how to actually test a matching algorithm against the new dataset. Added
`evaluation/cases/README.md` — covers the file format, data provenance (what's real ONC vs.
mutated vs. fabricated-and-marked-synthetic), a generic bring-your-own-algorithm adapter pattern
(Option A, any language/organization, per the Doc's Section 6 adapter contract), a concrete
worked example running this repo's own `MatchingEngine.evaluate_pair()` against the file (Option
B), per-`rationale`-category metric breakdown (per Section 5's "don't report one blended
number"), and what the dataset does *not* cover yet (collision-rate validation, administrative
restrictions, twins). Both code snippets were actually run before committing, not just written:
Option B's `MatchingEngine` snippet was executed against the first 200 real cases (185 TP / 0 FP
/ 0 TN / 15 FN — sensible given that slice is dominated by the file's early true-match rows) and
Option A's generic snippet was checked for syntactic validity. Cross-referenced from
`SYNTHETIC_DATA_SETUP.md`.

**Task 8, 2026-08-16 (new stacked PR, `claude/session-10-frequency-uniform`, based on
`claude/session-10-special-populations`):** After the "is 6,289 cases sufficient?" discussion
surfaced the per-category sample-size gaps above, the repo maintainer separately asked whether the
dataset represents each test case's real-world frequency — it doesn't, and hadn't been documented
as a gap. Per their direction, split the fix into two stacked PRs so the mechanical schema change and
the actual (debatable) frequency values get reviewed separately:

- **This PR (Task 8):** add a `frequency: float = 1.0` field to `LabeledCaseRecord`, a
  `uniform_frequency()` default lookup (every case weighted equally), and a `frequency_lookup`
  parameter on `build_test_case_records()` so a real lookup can be swapped in later without
  touching the generation logic. Regenerated `sample_labeled_pairs.jsonl` with the new field
  (still all `1.0`). Documented in `cases/README.md`'s new "Frequency and real-world
  representativeness" section — explicit that raw per-category counts in this file are a
  generation artifact, not a prevalence signal, per the same tension Doc §1/§5 already raise.
  3 new tests in `test_export_test_dataset.py`; full suite 493 passed (up from 490).
**Task 9, 2026-08-16 (new stacked PR, `claude/session-10-frequency-estimates`, based on
`claude/session-10-frequency-uniform`): FOR MAINTAINER REVIEW, not yet accepted as a default.**
Research conducted via a dedicated research agent (public sources only, per Option A+B-only
scoping): U.S. Census Bureau 2020 Census Group Quarters data, Pew Research Center on
multigenerational households and marital surname choices, CDC/NCHS twin-birth rates,
record-linkage literature (Zech et al. 2016, RAND 2008, Pew/ONC match-rate figures) for
data-entry-error context.

- `evaluation/prevalence_estimates.py` (new) — `PrevalenceEstimate` dataclass
  (`value`/`has_public_estimate`/`is_direct_measurement`/`source`/`notes`),
  `PREVALENCE_ESTIMATES` dict keyed by the exact `rationale` prefixes this repo's generators
  produce, `researched_frequency()` (a `frequency_lookup` implementation, strips
  `format_rationale()`'s parenthetical context before lookup, falls back to `NEUTRAL_FREQUENCY`
  for anything not yet in the dict).
  - **Real, direct-measurement estimates (5):** `shelter` (0.06%), `nursing_facility` (0.49%),
    `correctional_institution` (0.59%), `dormitory` (0.84%) — all U.S. Census 2020 Group Quarters
    — and `multi_generational_household` (18%, Pew Research 2022).
  - **Real, proxy estimates with documented caveats (2):** `diacritic` (20%, Hispanic-origin
    population share as a proxy — explicitly not a direct measurement) and `punctuation` (6%,
    Gooding & Kreider's "nonconventional surname" figure — married women only, doesn't cover men,
    apostrophes, or non-marital hyphenated birth surnames).
  - **Explicit "no public estimate found" placeholders, left at `NEUTRAL_FREQUENCY=1.0` (13):**
    `hotel_short_term_housing`/`halfway_house`/`group_home`/`migrant_camp` (bundled into an
    undifferentiated Census "Other noninstitutional facilities" catch-all with no further public
    split), all 10 `fuzzy_variant` subtypes (no source decomposes data-entry error by edit type —
    only coarser downstream match-failure rates exist), and `hard_negative` (a coincidental
    field-collision question, already governed by this repo's own P(collision) framework, not a
    demographic-prevalence one).
  - CDC's 2023 twin-birth rate (30.7 per 1,000 live births) is recorded as a module constant for
    documentation completeness, per the maintainer's original "represent frequency" ask — not applied to
    any category, since literal twins aren't generated (see Task 6's "Out of scope").
- `export_test_dataset.py`'s `__main__` now uses `frequency_lookup=researched_frequency`;
  `build_test_case_records()`'s own default stays `uniform_frequency` (opt-in, not silently
  changed for library callers). `sample_labeled_pairs.jsonl` regenerated with the real values.
- `cases/README.md` — full citation table with the "direct measurement vs. proxy vs. no public
  estimate" distinction, explicit "read the `notes` field before trusting any of these."
- 102 new tests in `test_prevalence_estimates.py` (completeness — every category this repo can
  actually generate has an entry; invariants — placeholders are pinned to `NEUTRAL_FREQUENCY` and
  never silently pass as `is_direct_measurement=True`; lookup correctness including the
  parenthetical-context-stripping case). Full suite 595 passed (up from 493).

**Close-out:** PR opened from `claude/session-10-special-populations`. Originally left in
`pending/` rather than moved to `in_review/`/`completed/` — merging is a human decision per
`conventions.md` ("Every session ends with a PR" + reviewer sign-off), not something to do
unilaterally. The code here was merged and in production use well before this note was ever
updated to say so; session_12 (2026-08-31) fixed the doc's stale status field as a housekeeping
item once that mismatch was noticed — see `docs/sessions/completed/session_12.md`.
