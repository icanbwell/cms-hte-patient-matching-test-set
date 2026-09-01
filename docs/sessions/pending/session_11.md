# Session 11 — Administrative-Restriction & Insurance-Identifier Labeled Pairs

**Status:** pending — partially superseded by session 13, needs re-scoping before it can proceed
as written. Session 13 removed this repo's git dependency on the reference matching engine entirely
(this repo only produces test data now). The data-fabrication piece below (synthetic
insurance-identifier values) is likely still valid as-is - it never needed the engine. But this
doc's wiring into `build_labeled_pairs()` (deleted; `generate_raw_pairs()` remains and is the right
place to wire into instead), its `NormalizationManager`/`FieldExtractor` usage, and its planned
regression guard in the reference matching engine's `matching/tests/test_table2_rules.py` all assume
the removed dependency and need rethinking. See `docs/sessions/completed/session_13.md`.
**Thread:** Evaluation & Statistical Rigor Framework
**Estimated size:** M/L — one new fabrication module (the repo's first genuinely *programmatic*
synthetic-patient generator, not a mutation/mining of real ONC records), its wiring into
`labeled_pairs.py`, and tests.

> This session doc originated in the repo this test-data generation code was split out of. See that repo's own session-doc conventions if you need them (not carried over here).

## Outcome purpose

**Scope anchor:** the last unaddressed row of `evaluation/SYNTHETIC_DATA_COMPARISON.md`'s
coverage table (the cross-org workgroup Google Doc's §2 categories) not covered by session_10:
**"Administrative Restrictions (e.g. family-shared insurance IDs)" — "No — not attempted this PR;
ONC's field set has no insurance/plan-ID column to construct this from."** This session closes
that gap, plus supplies true-match ground truth for the Member-ID/Subscriber-ID-anchored Table 2
rules (27-32) that session_6 adds. Also directly implements the workgroup Doc §1's **Option B**
("generate synthetic data programmatically... to deliberately construct the CMS-specific
scenarios [the bulk seed population] lacks") for the one field category ONC categorically cannot
supply — every prior synthetic-data session in this repo (9, 10) mutated or mined *real* ONC
records; this is the first session that fabricates a new field value outright (an insurance
identifier), because there is nothing in ONC to mine or mutate for this category.

CMS spec cross-reference (`docs/CMS_Patient_Matching_Proposal_v3.2.2.txt`'s successor content,
per session_6): §IV.D's Table 4 flags **"Subscriber ID + DOB + Payer namespace"** (P(collision) =
1e-10) as passing the numeric threshold but administratively restricted — "Subscriber ID is
shared across family members; DOB is also shared among twins... The combination does not include
an individually discriminating name field." This session's administrative-restriction scenario is
a direct construction of exactly that risk: twins (or any two family members who happen to share a
DOB) on the same family insurance plan.

## Upstream sessions (must be completed first)

- **Session 6** (`pending/`, not yet started) — **hard dependency.** This session cannot be coded
  until session_6 lands `PatientFields.insurance_member_ids`/`insurance_subscriber_ids` and
  `zip_codes`, and — critically — until `field_extractor.py`'s `_extract_identifiers` actually
  implements the FHIR `identifier.type.coding` code(s) it keys off of (session_6's Task 1
  explicitly deferred that exact code choice to its own implementation time). Do not start this
  session before session_6 is in `completed/` — per the "start the next session" protocol's step
  3, stop and tell the lead engineer if asked to start this session early.
- **Session 10** (`completed/`) — not a code dependency (this session's fabrication module is
  independent of session_10's mining/mutation modules), but both extend `labeled_pairs.py`'s
  `build_labeled_pairs()`. Session 10's code has already landed (see
  `docs/sessions/completed/session_10.md`), so this note is now moot — no coordination needed.

## Downstream sessions (unblocked by this one)

None yet authored. Feeds the same `labeled_pairs.py` output session_8 eventually consumes.

## Upstream data/system dependencies

None new (static ONC fixtures, same as prior sessions) — this session fabricates identifier
*values*, not real Coverage data, so it takes no dependency on the reference matching engine's
`fhir_client/`, Databricks, or any live payer system.

## Downstream data/system dependencies

None. `LabeledPair` output is in-memory only, per every prior session in this thread.

## Scope

### In scope

**1. `evaluation/synthetic_insurance_patients.py`** — the fabrication module:

```python
"""Synthetic insurance-identifier patient fabrication - the Google Doc's
("Proposal: A Shared Test Dataset for CMS v3.3.0 Patient Matching Compliance")
Section 1 Option B ("generate synthetic data programmatically... to
deliberately construct the CMS-specific scenarios [the bulk seed population]
lacks"), applied to the one category ONC categorically cannot supply:
insurance Member ID / Subscriber ID / Payer-namespace fields. ONC has no
insurance column at all, so unlike mutations.py/hard_negatives.py/
special_populations.py (which mutate or mine real ONC records), every
identifier value here is wholly fabricated - never derived from a real
Coverage record. Demographics (name, DOB) are still borrowed from real ONC
records (themselves a published, non-PHI synthetic dataset) to keep
distributions realistic; only the insurance identifiers are new, and they are
fabricated under an obviously-synthetic payer namespace (an *.example.org
URI - an IANA-reserved domain that can never resolve to a real payer) and an
obviously-synthetic assigner display name, per the Doc's Design Principle 4
("every fabricated identifier value should be unambiguously marked as
synthetic").

FHIR identifier type-code note, read before editing MEMBER_ID_TYPE_CODE /
SUBSCRIBER_ID_TYPE_CODE below: session_6 (docs/sessions/pending/session_6.md,
Task 1) commits to extracting insurance_member_id/insurance_subscriber_id via
Patient.identifier entries, but deliberately deferred the exact type.coding
code(s) to its own implementation time (resolved by reading how the reference matching engine's
fhir_client/ and ial2_extraction/ modules actually
attach Coverage-derived identifiers to a Patient dict this engine receives).
Before writing this module for real, read field_extractor.py's
_extract_identifiers as session_6 actually left it, and set these two
constants to match - this is an execution-time detail inherited directly
from session_6, not a new open question. The values below are this session's
best-effort placeholder pending that check.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

Patient = Dict[str, Any]

SYNTHETIC_PAYER_NAMESPACE = "https://synthetic-test-payer.example.org/fhir/sid/insurance-id"
SYNTHETIC_ASSIGNER_DISPLAY = "SYNTHETIC TEST PAYER"

# See module docstring - verify these against session_6's actual
# field_extractor.py implementation before relying on this module.
MEMBER_ID_TYPE_CODE = "MB"
SUBSCRIBER_ID_TYPE_CODE = "SUBSCRIBER"


def _with_insurance_identifier(patient: Patient, *, code: str, value: str) -> Patient:
    patient = copy.deepcopy(patient)
    identifiers = list(patient.get("identifier") or [])
    identifiers.append(
        {
            "system": SYNTHETIC_PAYER_NAMESPACE,
            "value": value,
            "type": {"coding": [{"code": code}]},
            "assigner": {"display": SYNTHETIC_ASSIGNER_DISPLAY},
        }
    )
    patient["identifier"] = identifiers
    return patient


@dataclass(frozen=True)
class FamilyPlanFixture:
    """A fabricated family insurance plan: one subscriber base ID shared by
    every member, each carrying its own distinct dependent-suffixed Member ID
    plus the shared Subscriber ID."""

    subscriber_base_id: str
    members: Tuple[Patient, ...]


def build_family_plan(
    base_patients: List[Patient],
    *,
    subscriber_base_id: str,
    force_shared_dob: bool = False,
) -> FamilyPlanFixture:
    """Attach a shared, fabricated Subscriber ID plus a per-member, distinct
    Member ID (base ID + two-digit dependent suffix, matching the CMS spec's
    "00"-for-subscriber/"01"-onward-for-dependents convention) to each of
    `base_patients`.

    `force_shared_dob=True` additionally overwrites every member's birthDate
    to the first member's value, for constructing the Table 4 "Subscriber ID
    + DOB" administrative-restriction scenario (e.g. twins on one family
    plan). Without it, members keep their own distinct real ONC DOBs - the
    realistic default for this module's true-match, Member-ID-anchored
    fixtures.
    """
    if not base_patients:
        raise ValueError("build_family_plan requires at least one base patient")
    members = []
    shared_dob = base_patients[0].get("birthDate")
    for suffix, patient in enumerate(base_patients):
        member_id = f"{subscriber_base_id}-{suffix:02d}"
        member = _with_insurance_identifier(patient, code=MEMBER_ID_TYPE_CODE, value=member_id)
        member = _with_insurance_identifier(
            member, code=SUBSCRIBER_ID_TYPE_CODE, value=subscriber_base_id
        )
        if force_shared_dob:
            member["birthDate"] = shared_dob
        members.append(member)
    return FamilyPlanFixture(subscriber_base_id=subscriber_base_id, members=tuple(members))


def member_id_true_match_pairs(fixture: FamilyPlanFixture) -> List[Tuple[Patient, Patient]]:
    """Each member paired with an identical copy of itself (query vs.
    responder record) - full Member ID + Payer namespace + demographics all
    matching - exercises Table 2 rules 27-30 (Member-ID-anchored, always-on
    per session_6)."""
    return [(copy.deepcopy(m), copy.deepcopy(m)) for m in fixture.members]


def subscriber_id_administrative_restriction_pairs(
    fixture: FamilyPlanFixture,
) -> List[Tuple[Patient, Patient]]:
    """Every distinct pair of family-plan members: same Subscriber ID + Payer
    namespace, different Member ID, and (when the fixture was built with
    force_shared_dob=True) the same DOB - the Table 4 "Subscriber ID + DOB"
    combination that clears the P(collision) threshold but is
    administratively excluded. Expect NO match under Table 2 as implemented -
    there is no approved rule using Subscriber ID + DOB alone (rules 31-32
    additionally require a discriminating first/last name field, which these
    fixtures deliberately do not share)."""
    pairs = []
    members = fixture.members
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            pairs.append((members[i], members[j]))
    return pairs


def recycled_member_id_negative_pairs(
    fixture_a: FamilyPlanFixture, fixture_b: FamilyPlanFixture
) -> List[Tuple[Patient, Patient]]:
    """Pair each member of `fixture_a` against the same-index member of
    `fixture_b` after overwriting fixture_b's Member ID to reuse fixture_a's -
    simulating a payer recycling a disenrolled member's ID (per the spec's
    §IV.H "Recyclability" discussion) for a genuinely different person, whose
    demographics (name, DOB) differ. Expect NO match: every approved
    Member-ID rule pairs Member ID with at least one demographic field
    specifically to mitigate this risk, so this is a regression guard on that
    design principle, not a new rule to add."""
    pairs = []
    for member_a, member_b in zip(fixture_a.members, fixture_b.members):
        recycled = copy.deepcopy(member_b)
        recycled["identifier"] = [
            ident
            for ident in recycled.get("identifier", [])
            if ident.get("type", {}).get("coding", [{}])[0].get("code") != MEMBER_ID_TYPE_CODE
        ]
        recycled = _with_insurance_identifier(
            recycled,
            code=MEMBER_ID_TYPE_CODE,
            value=next(
                ident["value"]
                for ident in member_a.get("identifier", [])
                if ident.get("type", {}).get("coding", [{}])[0].get("code") == MEMBER_ID_TYPE_CODE
            ),
        )
        pairs.append((member_a, recycled))
    return pairs
```

**2. Wire into `evaluation/labeled_pairs.py`** — add a new, separately-callable function (not
folded into `build_labeled_pairs()`'s per-ONC-patient loop, since this module operates on small,
explicitly-constructed family groups rather than the full sampled patient list):

```python
def build_insurance_identifier_pairs(
    patients: List[Dict[str, Any]], *, seed: int = 0
) -> List[LabeledPair]:
    """Build LabeledPairs for the insurance-identifier Table 2 rules (27-32)
    and the Table 4 Subscriber-ID administrative restriction, using
    synthetic_insurance_patients.py's fabricated family-plan fixtures. Takes
    at least 4 real ONC patients as demographic donors (2 two-person family
    plans) - callers typically pass a small slice of an already-loaded/
    normalized patient list, not the full sample.
    """
    if len(patients) < 4:
        raise ValueError("build_insurance_identifier_pairs needs at least 4 base patients")
    normalizer = NormalizationManager()
    extractor = FieldExtractor()
    normalized = [normalizer.normalize(p) for p in patients[:4]]

    plan_a = build_family_plan(normalized[:2], subscriber_base_id="SYN-SUB-0001", force_shared_dob=True)
    plan_b = build_family_plan(normalized[2:4], subscriber_base_id="SYN-SUB-0002")

    pairs: List[LabeledPair] = []
    for i, (query, candidate) in enumerate(member_id_true_match_pairs(plan_a)):
        pairs.append(
            LabeledPair(
                features={"query": extractor.extract(query), "candidate": extractor.extract(candidate)},
                is_true_match=True,
                strata={"pair_type": "insurance_member_id_match"},
                pair_id=f"synthetic-member-match-{i}",
            )
        )
    for i, (query, candidate) in enumerate(subscriber_id_administrative_restriction_pairs(plan_a)):
        pairs.append(
            LabeledPair(
                features={"query": extractor.extract(query), "candidate": extractor.extract(candidate)},
                is_true_match=False,
                strata={"pair_type": "administrative_restriction", "combination": "subscriber_id_dob"},
                pair_id=f"synthetic-admin-restriction-{i}",
            )
        )
    for i, (query, candidate) in enumerate(recycled_member_id_negative_pairs(plan_a, plan_b)):
        pairs.append(
            LabeledPair(
                features={"query": extractor.extract(query), "candidate": extractor.extract(candidate)},
                is_true_match=False,
                strata={"pair_type": "recycled_member_id_negative"},
                pair_id=f"synthetic-recycled-{i}",
            )
        )
    return pairs
```

Called separately from `build_labeled_pairs()` (not merged into it) because it needs a small,
explicit slice of donor patients rather than the full sampled list — wire it into
`labeled_pairs.py`'s `__main__` block as an additional, clearly-labeled section of the printed
summary, alongside (not replacing) the existing counts.

**3. Regression guard in the reference matching engine's `matching/tests/test_table2_rules.py`** (extends
session_6's own `test_first_last_dob_zip_never_appears` pattern to this session's restriction):

```python
def test_subscriber_id_dob_alone_never_appears(self):
    """Table 4's flagged administrative restriction - Subscriber ID + DOB
    without a discriminating name field must never be constructible as a
    rule, under either ENABLE_HOUSEHOLD_RISK_RULES setting."""
    for rule in APPROVED_RULES:
        field_names = {rf.name for rf in rule.fields}
        if "insurance_subscriber_id" in field_names:
            assert field_names & {"first_name", "last_name"}, (
                f"Rule {rule.rule_id} combines Subscriber ID with DOB but no "
                "discriminating name field - see session_11's administrative-"
                "restriction scope."
            )
```

**4. Update `evaluation/SYNTHETIC_DATA_COMPARISON.md`'s coverage table**, marking "Administrative
Restrictions" as covered, with a short note on the fabrication-vs-mining distinction (linking to
session_10's coincidental-vs-constructed-sharing note for the parallel concept).

### Out of scope

- **Any change to `field_extractor.py`'s actual identifier-extraction logic.** That's session_6's
  job; this session only fabricates FHIR `Patient.identifier` entries shaped to match whatever
  session_6 actually implements, verified at execution time (see module docstring's note).
- **The Table 4 "Subscriber ID + Group Number + Payer namespace" restriction** — a second
  administratively-restricted combination the spec flags, but it depends on a `group_number` field
  this repo has no plans to extract (session_6 doesn't add it either). Not attempted; flag as a
  candidate future addition if `group_number` extraction is ever added.
- **The Member ID + Payer namespace alone** row (Table 4) — it fails the P(collision) threshold
  outright (1e-6, not administratively excluded), so there's no meaningful "should not match" case
  to construct beyond what session_6's rule definitions themselves already prevent (no rule uses
  Member ID without another field). Not a distinct test case.
- **≥1,000,000-record validation, twins-without-insurance, client-type modeling** — same
  exclusions as session_10, unrelated to this session's insurance-identifier focus.
- **Doc §1 Option C (company-submitted de-identified real data)**, e.g. sourcing real
  family-plan/Subscriber-ID structures from an actual payer feed instead of fabricating them.
  The repo maintainer scoped this backlog down to Option A + Option B only, 2026-08-16 — this session's
  fabrication approach (synthetic identifiers over real-but-public ONC demographics) is already
  entirely Option A+B; no Option C data is used or planned here.

## Tasks

1. **Before writing any code**, confirm session_6 is in `completed/` and read its actual
   `field_extractor.py` `_extract_identifiers` implementation to fix
   `MEMBER_ID_TYPE_CODE`/`SUBSCRIBER_ID_TYPE_CODE` in `synthetic_insurance_patients.py` to match
   (see that module's docstring note) — do not assume the placeholder values above are correct.
2. Write `evaluation/synthetic_insurance_patients.py` (code above, with Task 1's corrected
   constants).
3. Write `evaluation/labeled_pairs.py`'s `build_insurance_identifier_pairs()` (code above) and
   wire it into the `__main__` block's printed summary.
4. Add the Table 4 regression guard to the reference matching engine's `matching/tests/test_table2_rules.py`.
5. Update `evaluation/SYNTHETIC_DATA_COMPARISON.md`.

## Unit tests required

File: `evaluation/test_synthetic_insurance_patients.py`.

```python
from __future__ import annotations

import pytest

from synthetic_insurance_patients import (
    MEMBER_ID_TYPE_CODE,
    SUBSCRIBER_ID_TYPE_CODE,
    SYNTHETIC_PAYER_NAMESPACE,
    build_family_plan,
    member_id_true_match_pairs,
    recycled_member_id_negative_pairs,
    subscriber_id_administrative_restriction_pairs,
)


def _patient(id_, family="Rivera", given="Ana", dob="1970-05-01"):
    return {
        "resourceType": "Patient",
        "id": id_,
        "name": [{"family": family, "given": [given]}],
        "birthDate": dob,
        "telecom": [],
        "address": [],
        "identifier": [],
    }


class TestBuildFamilyPlan:
    def test_every_member_shares_the_subscriber_id(self):
        fixture = build_family_plan(
            [_patient("p1"), _patient("p2", given="Luis")], subscriber_base_id="SYN-SUB-TEST"
        )
        for member in fixture.members:
            ids = {i["value"] for i in member["identifier"] if i["type"]["coding"][0]["code"] == SUBSCRIBER_ID_TYPE_CODE}
            assert ids == {"SYN-SUB-TEST"}

    def test_every_member_has_a_distinct_member_id(self):
        fixture = build_family_plan(
            [_patient("p1"), _patient("p2", given="Luis")], subscriber_base_id="SYN-SUB-TEST"
        )
        member_ids = [
            i["value"]
            for m in fixture.members
            for i in m["identifier"]
            if i["type"]["coding"][0]["code"] == MEMBER_ID_TYPE_CODE
        ]
        assert len(member_ids) == len(set(member_ids)) == 2

    def test_force_shared_dob_overwrites_every_member(self):
        fixture = build_family_plan(
            [_patient("p1", dob="1970-05-01"), _patient("p2", given="Luis", dob="1995-11-20")],
            subscriber_base_id="SYN-SUB-TEST",
            force_shared_dob=True,
        )
        assert {m["birthDate"] for m in fixture.members} == {"1970-05-01"}

    def test_namespace_is_obviously_synthetic(self):
        assert "example.org" in SYNTHETIC_PAYER_NAMESPACE

    def test_rejects_empty_base_patients(self):
        with pytest.raises(ValueError):
            build_family_plan([], subscriber_base_id="SYN-SUB-TEST")


class TestMemberIdTrueMatchPairs:
    def test_pairs_are_identical_copies(self):
        fixture = build_family_plan([_patient("p1")], subscriber_base_id="SYN-SUB-TEST")
        pairs = member_id_true_match_pairs(fixture)
        assert len(pairs) == 1
        assert pairs[0][0] == pairs[0][1]
        assert pairs[0][0] is not pairs[0][1]  # distinct objects, not aliased


class TestSubscriberIdAdministrativeRestrictionPairs:
    def test_pairs_share_subscriber_id_but_differ_on_member_id(self):
        fixture = build_family_plan(
            [_patient("p1"), _patient("p2", given="Luis")],
            subscriber_base_id="SYN-SUB-TEST",
            force_shared_dob=True,
        )
        pairs = subscriber_id_administrative_restriction_pairs(fixture)
        assert len(pairs) == 1
        query, candidate = pairs[0]
        query_member_id = next(i["value"] for i in query["identifier"] if i["type"]["coding"][0]["code"] == MEMBER_ID_TYPE_CODE)
        candidate_member_id = next(i["value"] for i in candidate["identifier"] if i["type"]["coding"][0]["code"] == MEMBER_ID_TYPE_CODE)
        assert query_member_id != candidate_member_id
        assert query["birthDate"] == candidate["birthDate"]


class TestRecycledMemberIdNegativePairs:
    def test_candidate_gets_query_familys_member_id_with_different_demographics(self):
        fixture_a = build_family_plan([_patient("p1", family="Rivera")], subscriber_base_id="SYN-SUB-A")
        fixture_b = build_family_plan([_patient("p2", family="Chen", given="Wei", dob="2001-02-02")], subscriber_base_id="SYN-SUB-B")
        pairs = recycled_member_id_negative_pairs(fixture_a, fixture_b)
        assert len(pairs) == 1
        query, recycled_candidate = pairs[0]
        query_member_id = next(i["value"] for i in query["identifier"] if i["type"]["coding"][0]["code"] == MEMBER_ID_TYPE_CODE)
        candidate_member_id = next(i["value"] for i in recycled_candidate["identifier"] if i["type"]["coding"][0]["code"] == MEMBER_ID_TYPE_CODE)
        assert query_member_id == candidate_member_id
        assert recycled_candidate["name"][0]["family"] == "Chen"  # demographics unchanged
```

Plus an integration test (in `evaluation/test_labeled_pairs.py`, `importorskip("numpy")`) that
runs `build_insurance_identifier_pairs()` against 4 real ONC patients and asserts the expected
`pair_type` strata values appear, and a test in the reference matching engine's
`matching/tests/test_table2_rules.py` for Task 3's regression guard.

## Validation (definition of "resolved")

- [ ] Session_6 confirmed `completed/` before this session's code was written; the type-code
      constants in `synthetic_insurance_patients.py` were verified against its actual
      `field_extractor.py`, not left at this doc's placeholder values.
- [ ] `evaluation/synthetic_insurance_patients.py` exists, imports cleanly, and every test in
      `evaluation/test_synthetic_insurance_patients.py` passes.
- [ ] `build_insurance_identifier_pairs()` runs against real ONC fixture data (4+ patients) and
      produces `insurance_member_id_match`, `administrative_restriction`, and
      `recycled_member_id_negative` labeled pairs.
- [ ] `test_subscriber_id_dob_alone_never_appears` passes against the full (session_6-expanded)
      `APPROVED_RULES`.
- [ ] Running `MatchingEngine.evaluate_pair()` (or `.match()`) against the fabricated
      administrative-restriction pair and the recycled-Member-ID pair both return no-match; the
      Member-ID true-match pair returns match — confirmed as part of this session's own manual
      validation pass (not necessarily a new unit test if `evaluate_pair()` is already exercised
      generically elsewhere — author's call at execution time).
- [ ] `ruff check`/`mypy` clean on new files; `make tests` green (full suite); `make run-pre-commit`
      clean.
- [ ] `evaluation/SYNTHETIC_DATA_COMPARISON.md` updated.
- [ ] Per `conventions.md`'s statistical rigor gate: this session doesn't itself change matching
      rule definitions (it only adds test fixtures + one regression-guard test), so Tier 1 doesn't
      block it — but it cannot move to `completed/` before session_6 (which does change rule
      behavior) is `completed/` first, per the dependency rule above.

## Open questions

- **Not a `NEEDS HUMAN DECISION`, but flagged prominently:** `MEMBER_ID_TYPE_CODE`/
  `SUBSCRIBER_ID_TYPE_CODE`'s values in this doc are best-effort placeholders. The executing agent
  must verify them against session_6's actual, merged `field_extractor.py` before trusting this
  module's output — this is the same class of implementation detail session_6 itself deferred, not
  a new ambiguity this session introduces.
- Whether `build_insurance_identifier_pairs()` should eventually be folded into
  `build_labeled_pairs()`'s single call once both stabilize, or remain a separate, explicitly-called
  function (since it needs curated donor patients rather than the full sample) — left as a
  candidate follow-up refactor, not blocking this session.

## Execution notes

_(empty at authoring time; filled in by whoever executes the session)_
