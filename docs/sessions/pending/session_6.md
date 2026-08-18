# Session 6 — Expand Table 2 to v3.3's 37 Rules

**Status:** pending
**Thread:** Line B: CMS v3.3 migration
**Estimated size:** M/L — three new canonical fields end-to-end (extractor + comparator +
rules), a new DOB fuzzy mode, 11 new rule definitions, and a default-off flag for a
reviewer-flagged risky cluster.

> This session doc originated in the patient-matching repo. Read [conventions.md](https://github.com/icanbwell/patient-matching/blob/main/docs/sessions/conventions.md) there first (this repo does not carry its own copy).

**On hold (Imran, 2026-08-16):** do not start this session yet, even once the live-spec-fetch
blocker (below) clears — separate from that blocker, Imran asked to hold off adding the v3.3
37-rule expansion for now. Confirm with him before beginning. Session 11
(`docs/sessions/pending/session_11.md`) has a hard dependency on this session and is therefore
on hold too.

## Outcome purpose

This repo currently implements CMS Proposal **v3.2.2** (26 rules, no ZIP or insurance-ID
based combinations, no DOB tolerance) — but the actual mid-August target, per the DS handoff
(`docs/handoff/README.md`), is **v3.3**: 37 rules, gender dropped entirely, DOB exact-or-
+/-1-day, and several insurance-namespace and ZIP-anchored combinations the current field
model can't even express yet. This session closes that version gap.

## Upstream sessions (must be completed first)

Session 5 — every new rule's `p_collision_exact`/`_fuzzy` is computed via session 5's
evaluator; this session cannot correctly score the 11 new combinations without it.

## Downstream sessions (unblocked by this one)

None currently authored. The (not-yet-authored) per-value P(collision) refinement, if Imran
signs off on it, would apply to this session's full 37-rule set once it exists.

## Upstream data/system dependencies

The CMS v3.3 spec's Table 2 (Google Doc, file ID `1ABHR6e4N-K9lEj1vc7DuzoAy8CuaAqwqAZSpJH9T4Yg`
— see `conventions.md`). **Fetch it fresh at session-start.** The 37-rule table below is
transcribed directly from that spec as read 2026-07-28 — re-verify rule numbering, field
combinations, and collision-probability figures against the live doc before implementing,
since it's a draft under active public comment.

## Downstream data/system dependencies

None new.

## Scope

### In scope

**1. Three new canonical fields, end-to-end** (needed by the 11 new rules below):
   - `zip_code` (rules 33, 34, 35) — 5-digit ZIP, exact only.
   - `insurance_member_id` (rules 27-30) — individual-level, payer-namespace-scoped, exact
     only. Per the spec: "the bare subscriber base value without dependent suffix SHALL NOT
     be treated as a Member ID."
   - `insurance_subscriber_id` (rules 31, 32) — policyholder-level, payer-namespace-scoped,
     exact only.

**2. A new DOB comparison mode**: several v3.3 rules mark DOB as fuzzy-eligible (shown with
   `*` in the spec), but v3.3's DOB tolerance is **+/-1 day**, not Damerau-Levenshtein edit
   distance (DOB is a date, not a name/street string) — this needs new comparator logic, not
   reuse of the existing string-fuzzy path.

**3. The 11 new Table 2 rules** (27-37), per the spec as read 2026-07-28 (re-verify at
   session-start):

   | # | Combination | p(exact) | p(fuzzy) | Notes |
   |---|---|---|---|---|
   | 27 | First Name + DOB + Member ID (payer namespace) | 2e-12 | — | |
   | 28 | Last Name* + DOB* + Member ID (payer namespace) | 5e-13 | 1e-12 | DOB* = +/-1 day |
   | 29 | Phone Number + Member ID (payer namespace) | 1e-12 | — | |
   | 30 | Email Address + Member ID (payer namespace) | 1e-12 | — | |
   | 31 | First Name* + Last Name + DOB + Subscriber ID (payer namespace) | 1e-12 | 1.5e-12 | |
   | 32 | First Name + Last Name* + DOB + Subscriber ID (payer namespace) | 1e-12 | 2e-12 | |
   | 33 | First Name* + Last Name* + Phone Number + ZIP | 3e-14 | 9e-14 | household-risk cluster, see below |
   | 34 | Last Name + Phone Number + ZIP | 1.5e-12 | — | household-risk cluster |
   | 35 | Last Name + Email Address + ZIP | 1.5e-12 | — | household-risk cluster |
   | 36 | Last Name* + DOB + Phone Number | 5e-13 | 1e-12 | household-risk cluster |
   | 37 | Last Name* + Street Line + Phone Number | 1.5e-13 | 3e-13 | household-risk cluster |

   For each rule, the `p_collision_exact`/`_fuzzy` column values above are what session 5's
   `evaluate_combination()` should reproduce once the rule's `fields` tuple is correctly
   built — don't hardcode the spec's numbers as literals (same principle as session 5's
   Task 3); use them here only to verify the computed value against the spec's own stated
   figure as a sanity check while authoring the rule.

   **Note:** row 31's p(fuzzy) is 1.5e-12, not a 2e-12 figure that would assume a 2x first_name fuzzy multiplier — consistent with session 5's Table 3 (first_name fuzzy u=0.03, a 1.5x multiplier), and with the same correction already applied to session 5's rules 04/06. Row 32 is unaffected (its fuzzy field is last_name, whose 2x multiplier — 0.01 vs exact 0.005 — is correct as stated).

**4. Two explicit exclusions/flags, carried over from the spec's own text and its still-open
   review comments** (see `../superpowers/specs/2026-07-28-session-planning-playbook-design.md`
   for the full history of how these were found):
   - **First Name + Last Name + DOB + ZIP must NOT be added.** The spec computes this to 3e-12
     under its own Table 3 (above the 2e-12 threshold) and explicitly says combinations
     depending on an undefined geographic-dependency discount SHALL NOT be added until that
     methodology is specified through governance — regardless of the 3e-13 figure some prior,
     non-spec analyses cite. Session 5's `test_first_last_dob_zip_is_not_approvable` already
     locks this in at the evaluator level; this session must not construct a `MatchingRule`
     for it.
   - **Rules 33-37 (the phone+ZIP/name-anchored cluster) ship behind a new, default-off
     flag**, `enable_household_risk_rules` — the spec's own reviewers raised unresolved
     concern that this cluster may violate the field-independence assumption for co-resident
     family/household members sharing a landline and surname, with a documented real-world
     false-positive scenario (sensitive records released to the wrong family member). Passing
     the numeric threshold is explicitly "necessary but not sufficient" per the spec itself.
     **`NEEDS HUMAN DECISION — Sean/Imran`**: whether to enable this cluster by default before
     the spec's comment period resolves. Recommended default: off, matching the spec's own
     framing — implement the rules, gate them behind the flag, don't flip it on without
     explicit sign-off.

### Out of scope
- The per-value (name-frequency-conditioned) collision-probability refinement — separate,
  not-yet-authored candidate session needing Imran's sign-off.
- Gender as a matching field — v3.3 drops it entirely; this repo's Table 2 rules never
  referenced gender in the first place (confirm by grep before assuming there's cleanup work
  here — `grep -rn gender patient_matching/matching/` and check whether any hits are
  matching-relevant or just FHIR resource shape).
- Wiring the household-risk cluster's adversarial family-sharing test case into Thread B's
  harness — that's the trigger condition for eventually flipping `enable_household_risk_rules`
  on, tracked as follow-up work once session 3/4 exist, not part of this session's Definition
  of Done.

## Tasks

1. **Add the three new canonical fields to the field model.**
   File: `patient_matching/matching/table2_rules.py` — add constants alongside the existing
   ones:
   ```python
   ZIP_CODE = "zip_code"
   INSURANCE_MEMBER_ID = "insurance_member_id"
   INSURANCE_SUBSCRIBER_ID = "insurance_subscriber_id"
   ```
   File: `patient_matching/matching/field_extractor.py` — add three new `Set[str]` fields to
   `PatientFields` (`zip_codes`, `insurance_member_ids`, `insurance_subscriber_ids`), add them
   to `get_values()`'s mapping dict, and add extraction logic in `FieldExtractor`:
   - `zip_codes`: extend `_extract_addresses` to also pull `addr.get("postalCode")` per
     address entry.
   - `insurance_member_ids`/`insurance_subscriber_ids`: extend `_extract_identifiers` — these
     come from FHIR `Coverage` resources in a real system, but this repo's `FieldExtractor`
     only ever sees a `Patient` dict (per its docstring: "Extract canonical field values from
     a normalized FHIR Patient resource"). Per the spec, an insurance identifier requires a
     co-submitted Payer ID and SHALL be namespace-scoped — represent this the same way
     `legal_ids`/`namespace_ids` already do (`f"{assigner}|{value}"` — see
     `_extract_identifiers`'s existing `legal_ids` branch for the pattern), reading from
     `patient.get("identifier", [])` entries whose `type.coding` includes a member-ID or
     subscriber-ID type code. **Decide the exact FHIR identifier type codes to key off of at
     implementation time** (this wasn't resolved during authoring since it depends on how
     Coverage-sourced identifiers actually get attached to the Patient dict this engine
     receives — check `patient_matching/fhir_client/` and `patient_matching/ial2_extraction/`
     for how identifiers arrive in practice before inventing new codes).

2. **Add DOB fuzzy (+/-1 day) comparison.**
   File: `patient_matching/matching/field_comparator.py` — add a new method:
   ```python
   from datetime import date, timedelta

   DOB_FUZZY_TOLERANCE_DAYS = 1

   @staticmethod
   def dob_fuzzy_match(query_values: Set[str], candidate_values: Set[str]) -> bool:
       """CMS v3.3 DOB tolerance: +/-1 day, exact date comparison (not edit distance).

       Both value sets are ISO 8601 date strings (YYYY-MM-DD). A query DOB matches
       a candidate DOB if they're the same day or adjacent by exactly one day.
       """
       try:
           q_dates = {date.fromisoformat(v) for v in query_values}
           c_dates = {date.fromisoformat(v) for v in candidate_values}
       except ValueError:
           return False  # partial/malformed dates never fuzzy-match, per SS V.A.5
       for q in q_dates:
           for c in c_dates:
               if abs((q - c).days) <= DOB_FUZZY_TOLERANCE_DAYS:
                   return True
       return False
   ```
   File: `patient_matching/matching/matching_engine.py`, method `_evaluate_rule` — the fuzzy
   branch currently always calls `self._comparator.fuzzy_match(q_values, c_values)`
   regardless of field name. The full method today (as of 2026-07-28) reads:
   ```python
   def _evaluate_rule(
       self,
       rule: MatchingRule,
       query_fields: PatientFields,
       cand_fields: PatientFields,
   ) -> RuleEvaluation:
       evaluation = RuleEvaluation(rule_id=rule.rule_id)
       fuzzy_count = 0
       all_matched = True

       for rf in rule.fields:
           q_values = query_fields.get_values(rf.name)
           c_values = cand_fields.get_values(rf.name)

           if not q_values or not c_values:
               evaluation.field_outcomes[rf.name] = "missing"
               all_matched = False
               continue

           # Try exact match first
           if self._comparator.exact_match(q_values, c_values):
               evaluation.field_outcomes[rf.name] = "exact"
               continue

           # Try fuzzy if eligible
           if (
               rf.role == FieldRole.FUZZY_ELIGIBLE
               and rule.max_fuzzy_fields > 0
               and self._comparator.fuzzy_match(q_values, c_values)
           ):
               fuzzy_count += 1
               if fuzzy_count <= rule.max_fuzzy_fields:
                   evaluation.field_outcomes[rf.name] = "fuzzy"
                   evaluation.fuzzy_fields.append(rf.name)
                   continue
               else:
                   # Exceeded max fuzzy fields
                   evaluation.field_outcomes[rf.name] = "fuzzy_exceeded"
                   all_matched = False
                   continue

           # No match
           evaluation.field_outcomes[rf.name] = "no_match"
           all_matched = False

       evaluation.matched = all_matched
       if evaluation.matched:
           evaluation.match_type = "fuzzy" if evaluation.fuzzy_fields else "exact"

       return evaluation
   ```
   Change only the fuzzy-branch condition (the `if (rf.role == FieldRole.FUZZY_ELIGIBLE and
   rule.max_fuzzy_fields > 0 and self._comparator.fuzzy_match(q_values, c_values)):` block) to
   dispatch on field name, leaving every other line of the method unchanged (this snippet is
   a fragment — the replacement for just that condition and its existing body, shown against
   the full method above for context — not a standalone statement):
   ```python-fragment
           if (
               rf.role == FieldRole.FUZZY_ELIGIBLE
               and rule.max_fuzzy_fields > 0
               and (
                   self._comparator.dob_fuzzy_match(q_values, c_values)
                   if rf.name == DOB
                   else self._comparator.fuzzy_match(q_values, c_values)
               )
           ):
               fuzzy_count += 1
               if fuzzy_count <= rule.max_fuzzy_fields:
                   evaluation.field_outcomes[rf.name] = "fuzzy"
                   evaluation.fuzzy_fields.append(rf.name)
                   continue
               else:
                   evaluation.field_outcomes[rf.name] = "fuzzy_exceeded"
                   all_matched = False
                   continue
   ```
   (Import `DOB` from `.table2_rules` in `matching_engine.py` if not already imported —
   check current imports first, since `table2_rules` is already imported for other names.)

3. **Add the `enable_household_risk_rules` flag and the 11 new rules.**
   File: `patient_matching/matching/table2_rules.py`. Add a module-level flag:
   ```python
   # NEEDS HUMAN DECISION - Sean/Imran: whether to enable the household-risk rule
   # cluster (33-37) by default. Off by default per the CMS v3.3 spec's own open,
   # unresolved reviewer concern about family/household false-positive risk on
   # phone+ZIP/name-anchored combinations - see docs/sessions/pending/session_6.md.
   ENABLE_HOUSEHOLD_RISK_RULES = False
   ```
   Add the 11 new `MatchingRule` entries (27-37) to `APPROVED_RULES`, each with `fields` built
   from the new/existing constants, `p_collision_exact`/`_fuzzy` computed via
   `collision.p_collision(...)` (import from `.collision`, added in session 5), and — for
   rules 33-37 only — excluded from `APPROVED_RULES` unless `ENABLE_HOUSEHOLD_RISK_RULES` is
   `True`. First, rename the existing 26-rule tuple literal in `table2_rules.py` from
   `APPROVED_RULES` to `_V322_RULES` (it keeps its exact current contents — no rule inside it
   changes). Then add the new rules. Two fully worked examples below — rule 27 (always-on,
   needs the new `INSURANCE_MEMBER_ID` constant) and rule 33 (household-risk cluster, needs
   `ZIP_CODE`) — build rules 28-32 and 34-37 the same way, reading each one's exact field
   combination and fuzzy-eligible fields (marked `*` in the Task 3 table's "Combination"
   column) from that table:
   ```python
   _V33_ALWAYS_ON_RULES: tuple[MatchingRule, ...] = (
       MatchingRule(
           rule_id="27",
           description="First Name + DOB + Member ID (w/ Payer namespace)",
           fields=(
               _rf(FIRST_NAME),
               _rf(DOB),
               _rf(INSURANCE_MEMBER_ID),
           ),
           max_fuzzy_fields=0,
           p_collision_exact=p_collision((_rf(FIRST_NAME), _rf(DOB), _rf(INSURANCE_MEMBER_ID))),
       ),
       # ... rules 28-32 go here, same pattern, using the Task 3 table's field lists ...
   )

   _HOUSEHOLD_RISK_RULES: tuple[MatchingRule, ...] = (
       MatchingRule(
           rule_id="33",
           description="First Name* + Last Name* + Phone Number + ZIP",
           fields=(
               _rf(FIRST_NAME, _F),
               _rf(LAST_NAME, _F),
               _rf(PHONE),
               _rf(ZIP_CODE),
           ),
           max_fuzzy_fields=2,
           p_collision_exact=p_collision((_rf(FIRST_NAME, _F), _rf(LAST_NAME, _F), _rf(PHONE), _rf(ZIP_CODE))),
           p_collision_fuzzy=p_collision(
               (_rf(FIRST_NAME, _F), _rf(LAST_NAME, _F), _rf(PHONE), _rf(ZIP_CODE)),
               fuzzy_fields=frozenset({FIRST_NAME, LAST_NAME}),
           ),
       ),
       # ... rules 34-37 go here, same pattern, using the Task 3 table's field lists ...
   )

   APPROVED_RULES: tuple[MatchingRule, ...] = (
       *_V322_RULES,
       *_V33_ALWAYS_ON_RULES,
       *(_HOUSEHOLD_RISK_RULES if ENABLE_HOUSEHOLD_RISK_RULES else ()),
   )
   ```
   The two `# ... rules N-M go here ...` comments are the only intentionally-incomplete part
   of this snippet — they stand for four and five more `MatchingRule(...)` calls, respectively,
   each fully specified (rule ID, field combination, fuzzy eligibility, collision values) in
   the Task 3 table above; write all nine remaining calls out in full using the two examples
   above as the pattern, the same way rule 27's and rule 33's are written out in full here —
   don't leave a real `...` or a bare comment in the actual file.

   **Bug-prevention note:** This exact bug class — a `max_fuzzy_fields` value inconsistent with how many fields the stated `p_collision_fuzzy` figure requires to be simultaneously fuzzy — has now been found and fixed twice in this plan (session 5's rule 01, session 6's rule 33). When writing each remaining rule, don't just copy the table's `*`-marked fields into `fuzzy_fields` — verify with `p_collision(...)` that your chosen `fuzzy_fields` set and `max_fuzzy_fields` value together actually reproduce the table's stated figure, the same way rule 27 and rule 33's examples do.
   Update the module docstring and `MatchingRule`'s docstring reference to "26" -> reflect the
   new total, and update `MatchingEngine`'s module docstring (currently "All 26 approved field
   combinations") similarly.

## Unit tests required

File: `patient_matching/matching/tests/test_table2_rules.py` (existing — update
`test_total_count`, which currently asserts `len(APPROVED_RULES) == 26`) and
`patient_matching/matching/tests/test_field_comparator.py` (existing — add DOB fuzzy cases).

```python
import pytest
from patient_matching.matching.table2_rules import APPROVED_RULES, ENABLE_HOUSEHOLD_RISK_RULES

class TestV33RuleCount:
    def test_total_count_with_household_risk_rules_off(self):
        assert ENABLE_HOUSEHOLD_RISK_RULES is False  # documents the current default
        assert len(APPROVED_RULES) == 32  # 26 original + 27-32, with 33-37 excluded

    def test_first_last_dob_zip_never_appears(self):
        """The spec's own admitted exclusion - must never be constructible as a rule."""
        for rule in APPROVED_RULES:
            field_names = {rf.name for rf in rule.fields}
            assert field_names != {"first_name", "last_name", "dob", "zip_code"}
```

```python
# in test_field_comparator.py
import pytest
from patient_matching.matching.field_comparator import FieldComparator

class TestDobFuzzyMatch:
    @pytest.mark.parametrize(
        "query_dob,candidate_dob,expected",
        [
            ("1990-01-15", "1990-01-15", True),   # exact
            ("1990-01-15", "1990-01-14", True),    # -1 day
            ("1990-01-15", "1990-01-16", True),    # +1 day
            ("1990-01-15", "1990-01-13", False),   # -2 days, out of tolerance
            ("1990-01-15", "1990-01-17", False),   # +2 days, out of tolerance
            ("1990-01-01", "1989-12-31", True),    # year boundary, -1 day
        ],
    )
    def test_dob_fuzzy_boundary(self, query_dob, candidate_dob, expected):
        assert FieldComparator.dob_fuzzy_match({query_dob}, {candidate_dob}) == expected

    def test_malformed_date_never_matches(self):
        assert FieldComparator.dob_fuzzy_match({"not-a-date"}, {"1990-01-15"}) is False
```

## Validation (definition of "resolved")

- [ ] `zip_code`, `insurance_member_id`, `insurance_subscriber_id` are extractable via
      `FieldExtractor`/`PatientFields`, with tests covering at least one populated and one
      empty case each.
- [ ] `FieldComparator.dob_fuzzy_match` exists, is used by `MatchingEngine` specifically for
      the `dob` field (not the generic string `fuzzy_match`), and all six boundary cases pass.
- [ ] `APPROVED_RULES` has 32 entries with `ENABLE_HOUSEHOLD_RISK_RULES = False` (the default),
      and 37 entries if that flag is manually flipped to `True` in a test.
- [ ] First Name + Last Name + DOB + ZIP is not constructible as any rule in `APPROVED_RULES`,
      under either flag setting.
- [ ] Every new rule's `p_collision_exact`/`_fuzzy` (computed via session 5's evaluator)
      matches the spec's own stated figure in the Task 3 table above, within rounding.
- [ ] `make tests` is green (full suite — this touches shared field-extraction and comparator
      code, so run the *entire* suite, not just the new tests, to catch regressions in
      existing rules 01-26).
- [ ] `make run-pre-commit` is clean.
- [ ] Per `conventions.md`'s statistical rigor gate: this session does not move to
      `completed/` until session 3's Tier-1 `ComparisonReport` exists.

## Open questions

- **`NEEDS HUMAN DECISION — Sean/Imran`** (stated in Scope above): whether to enable
  `ENABLE_HOUSEHOLD_RISK_RULES` by default before the CMS v3.3 comment period resolves.
  Recommended default: leave it `False` until Sean/Imran explicitly say otherwise.
- The exact FHIR identifier type codes for `insurance_member_id`/`insurance_subscriber_id`
  extraction (Task 1) were deliberately left for implementation time rather than guessed —
  this is a legitimate implementation detail the executing agent resolves by reading
  `patient_matching/fhir_client/`/`patient_matching/ial2_extraction/`'s actual identifier
  shapes, not a `NEEDS HUMAN DECISION` (no external authority is needed, just more context
  than was convenient to gather during this planning pass).

## Execution notes

_(empty at authoring time; filled in by whoever executes the session)_
