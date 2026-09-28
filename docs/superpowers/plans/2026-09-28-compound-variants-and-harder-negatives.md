# Compound True-Match Variants & Harder Hard-Negatives Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add compound (multi-field) true-match variants, three new scenario-specific true-match
mutators (SSN-dropped, marriage/address change, phone variant), and two new hard-negative miners
(sibling/twin proxy, name-collision-without-overlap) to this repo's test-data generation pipeline,
addressing items 1-2 of the 2026-09-22 CMS Patient Matching workgroup's feedback.

**Architecture:** Four small, additive generator functions land in `evaluation/mutations.py`
(true-match side) and two in `evaluation/hard_negatives.py`/`evaluation/special_populations.py`
(non-match side), following each module's existing "one self-contained function, one clear
scenario" style. One supporting change unlocks the phone-variant scenario: `onc_loader.py`
currently drops ONC's `PHONE2` column entirely; loading it as a second `telecom` entry is a
prerequisite, not optional plumbing. Everything wires into `labeled_pairs.py`'s
`generate_raw_pairs()` last, as new opt-out (`include_*`) parameters alongside the existing ones,
each producing `RawPair`s tagged with a new `strata["pair_type"]` value so downstream consumers can
slice by category exactly like every existing category already works.

**Tech Stack:** Python 3.12, stdlib only (no new dependencies — a pure-Python Levenshtein-distance
helper replaces the need for `rapidfuzz`, which session 13 confirmed is not an actual dependency of
this repo), pytest.

**Spec:** `docs/sessions/pending/session_14.md`

## Global Constraints

- `from __future__ import annotations` at the top of every new/modified module (existing
  repo-wide convention).
- Use `typing.Dict`/`List`/`Tuple` over builtin generics, matching every existing file in
  `evaluation/` (ruff's `UP006`/`UP035`/`FURB192` are deliberately ignored in `pyproject.toml`).
- No new third-party dependencies. `pyproject.toml`'s `dependencies` list stays unchanged.
- Field values are never normalized (session 13's removed-normalization convention) — no new
  mutator may lowercase, strip, or reformat a field as a side effect of doing something else.
- Every new generator function gets a docstring naming which 2026-09-22 workgroup gap it
  addresses, following the pattern every existing module in `evaluation/` already uses (see
  `mutations.py`'s and `special_populations.py`'s module docstrings).
- Default to no code comments beyond a docstring; only add an inline comment where a non-obvious
  invariant needs explaining (e.g. why a blocking key is used).
- `make lint` / `make typecheck` / `make run-pre-commit` must stay clean after every task.

## Review Focus

- **No-op mutators producing query==candidate pairs.** `ssn_dropped_variant` (no SSN present),
  `phone_variant` (fewer than two phone numbers), and `marriage_variant` (no
  `MOTHERS_MAIDEN_NAME`) can all legitimately no-op on a given ONC record. An unreviewed
  implementation could silently yield a "true match" pair where both sides are byte-identical,
  which is a degenerate but not obviously wrong-looking test case — each task below has an explicit
  test for the no-op path, not just the happy path.
- **`generate_compound_variant(n_mutations=1)` or `n_mutations=0`.** Must raise, not silently
  produce a single-edit variant that duplicates `generate_fuzzy_variant()`'s job under a different
  name — tested directly in Task 5.
- **Off-by-one at the sibling/household age-gap boundary.** `mine_sibling_negatives`'s
  `max_age_gap_years` and the existing `mine_shared_surname_household_negatives`'s
  `min_age_gap_years` must not silently overlap (e.g. both claiming a 3-year gap) or leave a gap
  where neither miner claims a case — Task 6 tests the exact boundary values (3 and 15 years) from
  both functions' perspectives.
- **`mine_name_collision_negatives`'s first-letter blocking silently dropping legitimate pairs.**
  A pair differing by an inserted/deleted first character (e.g. "Smith" vs. "ASmith") lands in
  different blocking buckets and is never compared. Task 7 tests both that same-bucket collisions
  are found and that the blocking key is documented as a known, accepted tradeoff (matching this
  module's existing ZIP+DOB blocking precedent) rather than silently treated as exhaustive.
- **`PHONE2` telecom-list-order assumption.** Task 1 must confirm (by grep, not assumption) that
  no downstream code indexes `patient["telecom"][0]` expecting it to always be a specific type
  before appending a second phone entry — verified in Task 1's own step, not deferred.

---

## Task 1: Load ONC's `PHONE2` column as a second `telecom` entry

Resolves session_14.md's open question about whether ONC carries any phone-type-equivalent field.
Finding (confirmed by inspecting `evaluation/fixtures/onc/*.csv` headers directly): ONC has no
`use` (home/mobile) semantic, but it does carry a second raw phone-number column, `PHONE2`, that
`onc_loader.py` currently reads from the CSV header but never maps into the output `Patient` dict.
Loading it is the prerequisite for Task 4's `phone_variant`.

**Files:**
- Modify: `evaluation/onc_loader.py:94-97`
- Create: `evaluation/test_onc_loader.py` (no test file exists for this module today)

**Interfaces:**
- Produces: `load_onc_patients()`'s output `Patient["telecom"]` list may now contain **two**
  `{"system": "phone", ...}` entries (order: `PHONE` first, `PHONE2` second, both before any
  `EMAIL` entry) instead of at most one.

- [ ] **Step 1: Confirm no downstream code assumes a fixed/short `telecom` list shape**

Run: `grep -rn "telecom\[" /Users/imranqureshi/git/cms-hte-patient-matching-test-set/evaluation/*.py`

Expected: no matches (confirmed already during planning — this step re-verifies before editing,
since the grep result gates whether this task is safe to do at all).

- [ ] **Step 2: Write the failing tests**

```python
# evaluation/test_onc_loader.py
"""Unit tests for onc_loader.py."""

from __future__ import annotations

from onc_loader import load_onc_patients, _row_to_patient


def _row(**overrides):
    base = {
        "EnterpriseID": "1",
        "LAST": "SMITH",
        "FIRST": "JANE",
        "MIDDLE": "",
        "SUFFIX": "",
        "DOB": "8476",
        "GENDER": "FEMALE",
        "SSN": "",
        "ADDRESS1": "",
        "ADDRESS2": "",
        "ZIP": "",
        "MOTHERS_MAIDEN_NAME": "",
        "MRN": "",
        "CITY": "",
        "STATE": "",
        "PHONE": "",
        "PHONE2": "",
        "EMAIL": "",
        "ALIAS": "",
    }
    base.update(overrides)
    return base


class TestPhone2Loading:
    def test_both_phone_columns_load_as_separate_phone_telecom_entries(self) -> None:
        patient = _row_to_patient(_row(PHONE="555-000-1111", PHONE2="555-222-3333"))
        phone_values = [t["value"] for t in patient["telecom"] if t["system"] == "phone"]
        assert phone_values == ["555-000-1111", "555-222-3333"]

    def test_email_still_loads_after_both_phones(self) -> None:
        patient = _row_to_patient(
            _row(PHONE="555-000-1111", PHONE2="555-222-3333", EMAIL="jane@example.com")
        )
        assert patient["telecom"][-1] == {"system": "email", "value": "jane@example.com"}

    def test_missing_phone2_yields_a_single_phone_entry(self) -> None:
        patient = _row_to_patient(_row(PHONE="555-000-1111"))
        phone_entries = [t for t in patient["telecom"] if t["system"] == "phone"]
        assert len(phone_entries) == 1

    def test_missing_both_phones_yields_no_phone_entries(self) -> None:
        patient = _row_to_patient(_row())
        assert not any(t["system"] == "phone" for t in patient["telecom"])
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /Users/imranqureshi/git/cms-hte-patient-matching-test-set && PYTHONPATH=evaluation uv run pytest evaluation/test_onc_loader.py -v`
Expected: `test_both_phone_columns_load_as_separate_phone_telecom_entries` FAILS (only one phone
value present); the other three pass already against current code.

- [ ] **Step 4: Implement**

In `evaluation/onc_loader.py`, replace lines 94-97:

```python
    if row.get("PHONE"):
        patient["telecom"].append({"system": "phone", "value": row["PHONE"]})
    if row.get("EMAIL"):
        patient["telecom"].append({"system": "email", "value": row["EMAIL"]})
```

with:

```python
    if row.get("PHONE"):
        patient["telecom"].append({"system": "phone", "value": row["PHONE"]})
    if row.get("PHONE2"):
        patient["telecom"].append({"system": "phone", "value": row["PHONE2"]})
    if row.get("EMAIL"):
        patient["telecom"].append({"system": "email", "value": row["EMAIL"]})
```

Also update the module docstring's second paragraph (currently: "extended to also populate
MOTHERS_MAIDEN_NAME and ALIAS, which that transform reads from the CSV but never maps into the
output FHIR resource") to add `PHONE2` to that list.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/imranqureshi/git/cms-hte-patient-matching-test-set && PYTHONPATH=evaluation uv run pytest evaluation/test_onc_loader.py -v`
Expected: all 4 PASS.

- [ ] **Step 6: Commit**

```bash
git add evaluation/onc_loader.py evaluation/test_onc_loader.py
git commit -m "Load ONC's PHONE2 column as a second telecom entry"
```

---

## Task 2: `ssn_dropped_variant` — SSN present on one side of a true-match pair, absent on the other

**Files:**
- Modify: `evaluation/mutations.py` (add near the end of the "Name mutations" section, before
  "Composition")
- Test: `evaluation/test_mutations.py`

**Interfaces:**
- Consumes: `Patient` type alias, `_copy_patient()` — both already defined at the top of
  `mutations.py`.
- Produces: `SSN_SYSTEM: str` (module-level constant), `ssn_dropped_variant(patient: Patient) ->
  Patient`.

- [ ] **Step 1: Write the failing tests**

```python
# add to evaluation/test_mutations.py
from mutations import SSN_SYSTEM, ssn_dropped_variant


class TestSsnDroppedVariant:
    def test_removes_the_ssn_identifier(self) -> None:
        patient = _patient(
            identifier=[{"system": SSN_SYSTEM, "value": "123-45-6789"}]
        )
        result = ssn_dropped_variant(patient)
        assert result["identifier"] == []

    def test_leaves_non_ssn_identifiers_untouched(self) -> None:
        other = {"system": "http://example.org/mrn", "value": "M1"}
        patient = _patient(identifier=[{"system": SSN_SYSTEM, "value": "1"}, other])
        result = ssn_dropped_variant(patient)
        assert result["identifier"] == [other]

    def test_missing_ssn_is_a_noop(self) -> None:
        patient = _patient(identifier=[])
        result = ssn_dropped_variant(patient)
        assert result["identifier"] == []

    def test_does_not_mutate_input_patient(self) -> None:
        patient = _patient(identifier=[{"system": SSN_SYSTEM, "value": "1"}])
        ssn_dropped_variant(patient)
        assert patient["identifier"] == [{"system": SSN_SYSTEM, "value": "1"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/imranqureshi/git/cms-hte-patient-matching-test-set && uv run pytest evaluation/test_mutations.py::TestSsnDroppedVariant -v`
Expected: FAIL with `ImportError: cannot import name 'SSN_SYSTEM'`.

- [ ] **Step 3: Implement**

Add to `evaluation/mutations.py`, after `substitute_nickname()` (before the "Composition" section
comment):

```python
# --------------------------------------------------------------------------------------
# Identifier mutations
# --------------------------------------------------------------------------------------

# Matches onc_loader.py's own SSN identifier.system value exactly.
SSN_SYSTEM = "http://hl7.org/fhir/sid/us-ssn"


def ssn_dropped_variant(patient: Patient) -> Patient:
    """Return a copy of `patient` with its SSN identifier removed - models the
    realistic case Luke Breyer (Epic) raised in the 2026-09-22 workgroup
    meeting, where one of a person's two on-file records carries a Social
    Security Number and the other doesn't. Matches the Epic reference doc's
    "Missing/placeholder SSN" data-quality category. No-op if `patient` has no
    SSN identifier to begin with."""
    patient = _copy_patient(patient)
    identifiers = patient.get("identifier") or []
    patient["identifier"] = [i for i in identifiers if i.get("system") != SSN_SYSTEM]
    return patient
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/imranqureshi/git/cms-hte-patient-matching-test-set && uv run pytest evaluation/test_mutations.py::TestSsnDroppedVariant -v`
Expected: all 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add evaluation/mutations.py evaluation/test_mutations.py
git commit -m "Add ssn_dropped_variant true-match mutator"
```

---

## Task 3: `marriage_variant` — maiden-name + address change true-match pair

**Files:**
- Modify: `evaluation/mutations.py` (same "Identifier mutations" area — rename section to
  "Identifier and household mutations", or add a new small section immediately after; either is
  fine, keep it adjacent to Task 2's addition)
- Test: `evaluation/test_mutations.py`

**Interfaces:**
- Consumes: `Patient`, `_copy_patient()`.
- Produces: `marriage_variant(patient: Patient, donor: Patient) -> Patient`.

- [ ] **Step 1: Write the failing tests**

```python
# add to evaluation/test_mutations.py
from mutations import marriage_variant


class TestMarriageVariant:
    def test_replaces_family_name_with_mothers_maiden_name(self) -> None:
        patient = _patient(
            name=[
                {"family": "Smith", "given": ["Katherine"]},
                {"family": "Jones", "given": ["Katherine"]},  # maiden-name proxy entry
            ]
        )
        donor = _patient(id="donor", address=[{"line": ["9 Elm St"], "city": "X", "state": "Y", "postalCode": "99999"}])
        result = marriage_variant(patient, donor)
        assert result["name"][0]["family"] == "Jones"

    def test_replaces_address_with_donors_address(self) -> None:
        patient = _patient(address=[{"line": ["1 Main St"], "city": "A", "state": "B", "postalCode": "11111"}])
        donor = _patient(id="donor", address=[{"line": ["9 Elm St"], "city": "X", "state": "Y", "postalCode": "99999"}])
        result = marriage_variant(patient, donor)
        assert result["address"] == donor["address"]

    def test_no_maiden_name_entry_leaves_family_name_unchanged(self) -> None:
        patient = _patient(name=[{"family": "Smith", "given": ["Katherine"]}])
        donor = _patient(id="donor", address=[])
        result = marriage_variant(patient, donor)
        assert result["name"][0]["family"] == "Smith"

    def test_does_not_mutate_input_patient_or_donor(self) -> None:
        patient = _patient(
            name=[{"family": "Smith", "given": ["K"]}, {"family": "Jones", "given": ["K"]}],
            address=[{"line": ["1 Main St"], "city": "A", "state": "B", "postalCode": "11111"}],
        )
        donor = _patient(id="donor", address=[{"line": ["9 Elm St"], "city": "X", "state": "Y", "postalCode": "99999"}])
        original_patient_address = [dict(a) for a in patient["address"]]
        marriage_variant(patient, donor)
        assert patient["address"] == original_patient_address
        assert patient["name"][0]["family"] == "Smith"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/imranqureshi/git/cms-hte-patient-matching-test-set && uv run pytest evaluation/test_mutations.py::TestMarriageVariant -v`
Expected: FAIL with `ImportError: cannot import name 'marriage_variant'`.

- [ ] **Step 3: Implement**

Add to `evaluation/mutations.py`, right after Task 2's `ssn_dropped_variant()`:

```python
def marriage_variant(patient: Patient, donor: Patient) -> Patient:
    """Return a copy of `patient` with its family name replaced by its second
    `name` entry (onc_loader.py loads MOTHERS_MAIDEN_NAME as a second `name`
    entry for household-linkage purposes; repurposed here as a pre-marriage
    surname proxy, since ONC has no dedicated maiden-name column) and its
    address replaced by `donor`'s address (modeling a marriage-driven move -
    ONC carries no address history for one person to draw a second address
    from, so an unrelated real ONC record's address stands in for it).
    Represents the "surname + address changed together" scenario Luke Breyer
    (Epic) raised in the 2026-09-22 workgroup meeting. No-op on the name
    change if `patient` has fewer than two `name` entries."""
    patient = _copy_patient(patient)
    names = patient.get("name") or []
    if len(names) > 1:
        names[0]["family"] = names[1]["family"]
    patient["address"] = copy.deepcopy(donor.get("address") or [])
    return patient
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/imranqureshi/git/cms-hte-patient-matching-test-set && uv run pytest evaluation/test_mutations.py::TestMarriageVariant -v`
Expected: all 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add evaluation/mutations.py evaluation/test_mutations.py
git commit -m "Add marriage_variant true-match mutator"
```

---

## Task 4: `phone_variant` — two distinct real phone numbers for one person

Depends on Task 1 (`PHONE2` loading) to have any real data to exercise, though the function itself
only depends on the `telecom` list shape and can be tested with hand-built fixtures independent of
Task 1's completion.

**Files:**
- Modify: `evaluation/mutations.py` (same area as Tasks 2-3)
- Test: `evaluation/test_mutations.py`

**Interfaces:**
- Consumes: `Patient`, `_copy_patient()`.
- Produces: `phone_variant(patient: Patient) -> Patient`.

- [ ] **Step 1: Write the failing tests**

```python
# add to evaluation/test_mutations.py
from mutations import phone_variant


class TestPhoneVariant:
    def test_swaps_to_second_phone_number(self) -> None:
        patient = _patient(
            telecom=[
                {"system": "phone", "value": "555-000-1111"},
                {"system": "phone", "value": "555-222-3333"},
            ]
        )
        result = phone_variant(patient)
        phone_values = [t["value"] for t in result["telecom"] if t["system"] == "phone"]
        assert phone_values == ["555-222-3333"]

    def test_preserves_non_phone_telecom_entries(self) -> None:
        patient = _patient(
            telecom=[
                {"system": "phone", "value": "555-000-1111"},
                {"system": "phone", "value": "555-222-3333"},
                {"system": "email", "value": "jane@example.com"},
            ]
        )
        result = phone_variant(patient)
        assert {"system": "email", "value": "jane@example.com"} in result["telecom"]

    def test_single_phone_number_is_a_noop(self) -> None:
        patient = _patient(telecom=[{"system": "phone", "value": "555-000-1111"}])
        result = phone_variant(patient)
        assert result["telecom"] == patient["telecom"]

    def test_no_phone_number_is_a_noop(self) -> None:
        patient = _patient(telecom=[])
        result = phone_variant(patient)
        assert result["telecom"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/imranqureshi/git/cms-hte-patient-matching-test-set && uv run pytest evaluation/test_mutations.py::TestPhoneVariant -v`
Expected: FAIL with `ImportError: cannot import name 'phone_variant'`.

- [ ] **Step 3: Implement**

Add to `evaluation/mutations.py`, right after `marriage_variant()`:

```python
def phone_variant(patient: Patient) -> Patient:
    """Return a copy of `patient` using its second phone number in place of
    its first - models the same person having two different on-file phone
    numbers (e.g. an old home line vs. a newer cell number), the scenario
    Luke Breyer (Epic) named in the 2026-09-22 workgroup meeting. ONC has no
    phone `use` code (home/mobile) to draw on, so this deliberately does not
    fabricate a FHIR ContactPoint.use value - it only demonstrates two
    genuinely different real phone strings for one person. No-op if
    `patient` has fewer than two phone-system telecom entries."""
    patient = _copy_patient(patient)
    telecom = patient.get("telecom") or []
    phones = [t for t in telecom if t.get("system") == "phone"]
    if len(phones) < 2:
        return patient
    non_phone = [t for t in telecom if t.get("system") != "phone"]
    patient["telecom"] = [phones[1]] + non_phone
    return patient
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/imranqureshi/git/cms-hte-patient-matching-test-set && uv run pytest evaluation/test_mutations.py::TestPhoneVariant -v`
Expected: all 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add evaluation/mutations.py evaluation/test_mutations.py
git commit -m "Add phone_variant true-match mutator"
```

---

## Task 5: `generate_compound_variant` — multi-field true-match variant

**Files:**
- Modify: `evaluation/mutations.py:39` (add `List` to the `typing` import) and the "Composition"
  section (after `generate_fuzzy_variant()`)
- Test: `evaluation/test_mutations.py`

**Interfaces:**
- Consumes: `MUTATIONS: Dict[str, Callable[[Patient, random.Random], Patient]]`, `_rng()` — both
  already defined in `mutations.py`.
- Produces: `generate_compound_variant(patient: Patient, *, n_mutations: int = 2, rng:
  random.Random | None = None) -> Tuple[Patient, List[str]]`.

- [ ] **Step 1: Write the failing tests**

```python
# add to evaluation/test_mutations.py
from mutations import generate_compound_variant


class TestGenerateCompoundVariant:
    def test_returns_n_mutations_applied(self) -> None:
        patient = _patient()
        rng = random.Random(0)
        _, mutation_types = generate_compound_variant(patient, n_mutations=3, rng=rng)
        assert len(mutation_types) == 3
        assert all(m in MUTATIONS for m in mutation_types)

    def test_default_n_mutations_is_two(self) -> None:
        patient = _patient()
        _, mutation_types = generate_compound_variant(patient, rng=random.Random(0))
        assert len(mutation_types) == 2

    def test_n_mutations_below_two_raises(self) -> None:
        with pytest.raises(ValueError):
            generate_compound_variant(_patient(), n_mutations=1, rng=random.Random(0))

    def test_does_not_mutate_input_patient(self) -> None:
        patient = _patient()
        original_family = patient["name"][0]["family"]
        generate_compound_variant(patient, n_mutations=3, rng=random.Random(0))
        assert patient["name"][0]["family"] == original_family

    def test_variant_differs_from_original(self) -> None:
        # dob_day/dob_year/dob_typo/dob_month are never no-ops for a present
        # birthDate (see mutate_dob's DOB_ERROR_TYPES docstring) - forcing a
        # DOB-only mutation type twice guarantees an observable change without
        # depending on random name-mutation luck.
        patient = _patient()
        rng = random.Random(0)
        variant, _ = generate_compound_variant(
            patient, n_mutations=2, rng=rng
        )
        # At least one field must differ somewhere in the record.
        assert variant != patient
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/imranqureshi/git/cms-hte-patient-matching-test-set && uv run pytest evaluation/test_mutations.py::TestGenerateCompoundVariant -v`
Expected: FAIL with `ImportError: cannot import name 'generate_compound_variant'`.

- [ ] **Step 3: Implement**

In `evaluation/mutations.py:39`, change:

```python
from typing import Any, Callable, Dict, Tuple
```

to:

```python
from typing import Any, Callable, Dict, List, Tuple
```

Add to the "Composition" section, right after `generate_fuzzy_variant()`:

```python
def generate_compound_variant(
    patient: Patient,
    *,
    n_mutations: int = 2,
    rng: random.Random | None = None,
) -> Tuple[Patient, List[str]]:
    """Apply `n_mutations` randomly-chosen mutators from MUTATIONS to
    `patient` in sequence, each acting on the previous mutator's output -
    models the realistic multi-field true-match pair Luke Breyer (Epic)
    raised in the 2026-09-22 workgroup meeting ("every correct match pair was
    an exact copy with only one field changed"). generate_fuzzy_variant()
    itself is unchanged and still applies exactly one mutation - several CMS
    provisions specifically need that single-field-diff shape to test one
    rule in isolation, so this is an additional true-match category, not a
    replacement.

    Returns (mutated_patient, mutation_types_applied); the list always has
    exactly `n_mutations` entries (repeats allowed - e.g. two independent
    family-name mutators both firing is itself a realistic compound case).
    Raises ValueError if n_mutations < 2 (a single mutation is
    generate_fuzzy_variant()'s job, not this function's)."""
    if n_mutations < 2:
        raise ValueError("generate_compound_variant requires n_mutations >= 2")
    rng = _rng(rng)
    mutation_types = [rng.choice(list(MUTATIONS)) for _ in range(n_mutations)]
    variant = patient
    for mutation_type in mutation_types:
        variant = MUTATIONS[mutation_type](variant, rng)
    return variant, mutation_types
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/imranqureshi/git/cms-hte-patient-matching-test-set && uv run pytest evaluation/test_mutations.py::TestGenerateCompoundVariant -v`
Expected: all 5 PASS. (If `test_variant_differs_from_original` is flaky against a different seed
because both randomly-chosen mutators happened to no-op, re-run with the fixed `random.Random(0)`
seed shown above, which is deterministic — do not loosen the assertion instead.)

- [ ] **Step 5: Commit**

```bash
git add evaluation/mutations.py evaluation/test_mutations.py
git commit -m "Add generate_compound_variant multi-field true-match generator"
```

---

## Task 6: `mine_sibling_negatives` — close-in-age same-household hard negative

Placed in `special_populations.py`, immediately after `mine_shared_surname_household_negatives()`
(same bucketing structure, same file's existing `date` import — not `hard_negatives.py`, which has
no `datetime` import and whose only existing miner is the disjoint ZIP+DOB-collision one).

**Files:**
- Modify: `evaluation/special_populations.py` (add after `mine_shared_surname_household_negatives()`)
- Test: `evaluation/test_special_populations.py`

**Interfaces:**
- Consumes: `HardNegativeCandidate` (already imported from `hard_negatives` at the top of
  `special_populations.py`), `_postal_code()`, `_primary_family_name()` — both already defined in
  this file.
- Produces: `mine_sibling_negatives(patients: Iterable[Patient], *, max_age_gap_years: int = 3) ->
  List[HardNegativeCandidate]`.

- [ ] **Step 1: Write the failing tests**

```python
# add to evaluation/test_special_populations.py
from special_populations import mine_sibling_negatives


def _sibling_patient(id_: str, family: str, zip_code: str, dob: str):
    return {
        "resourceType": "Patient",
        "id": id_,
        "name": [{"family": family, "given": ["Pat"]}],
        "birthDate": dob,
        "telecom": [],
        "address": [
            {"line": ["1 Main St"], "city": "NY", "state": "NY", "postalCode": zip_code}
        ],
        "identifier": [],
    }


class TestMineSiblingNegatives:
    def test_finds_same_family_same_zip_close_in_age(self) -> None:
        patients = [
            _sibling_patient("p1", "Rivera", "10001", "2010-01-01"),
            _sibling_patient("p2", "Rivera", "10001", "2011-06-01"),
        ]
        candidates = mine_sibling_negatives(patients)
        assert len(candidates) == 1
        assert candidates[0].shared_fields["age_gap_years"] == "1"

    def test_excludes_pairs_beyond_max_age_gap_years(self) -> None:
        patients = [
            _sibling_patient("p1", "Rivera", "10001", "1970-01-01"),
            _sibling_patient("p2", "Rivera", "10001", "2010-01-01"),
        ]
        assert mine_sibling_negatives(patients, max_age_gap_years=3) == []

    def test_boundary_gap_equal_to_max_is_included(self) -> None:
        patients = [
            _sibling_patient("p1", "Rivera", "10001", "2010-01-01"),
            _sibling_patient("p2", "Rivera", "10001", "2013-01-01"),
        ]
        candidates = mine_sibling_negatives(patients, max_age_gap_years=3)
        assert len(candidates) == 1

    def test_excludes_different_family_names(self) -> None:
        patients = [
            _sibling_patient("p1", "Rivera", "10001", "2010-01-01"),
            _sibling_patient("p2", "Chen", "10001", "2010-06-01"),
        ]
        assert mine_sibling_negatives(patients) == []

    def test_excludes_different_zip_codes(self) -> None:
        patients = [
            _sibling_patient("p1", "Rivera", "10001", "2010-01-01"),
            _sibling_patient("p2", "Rivera", "20002", "2010-06-01"),
        ]
        assert mine_sibling_negatives(patients) == []

    def test_never_pairs_a_record_with_itself(self) -> None:
        patient = _sibling_patient("p1", "Rivera", "10001", "2010-01-01")
        assert mine_sibling_negatives([patient, patient]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/imranqureshi/git/cms-hte-patient-matching-test-set && uv run pytest evaluation/test_special_populations.py::TestMineSiblingNegatives -v`
Expected: FAIL with `ImportError: cannot import name 'mine_sibling_negatives'`.

- [ ] **Step 3: Implement**

Add to `evaluation/special_populations.py`, immediately after
`mine_shared_surname_household_negatives()`:

```python
def mine_sibling_negatives(
    patients: Iterable[Patient], *, max_age_gap_years: int = 3
) -> List[HardNegativeCandidate]:
    """Mine real ONC pairs sharing a postal code AND family name, with birth
    years close enough together to represent siblings (or twins, which
    ONC's per-row structure cannot distinguish from close-in-age siblings
    without a family-relationship column) - the complementary near-DOB case
    mine_shared_surname_household_negatives()'s min_age_gap_years=15 default
    deliberately excludes. Addresses the gap Luke Breyer (Epic) raised in
    the 2026-09-22 workgroup meeting: negative cases need "close relatives,
    twins, and family members" to be hard enough to outperform cheap
    heuristics, not just coincidental ZIP+DOB collisions between unrelated
    people."""
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
                dob_a, dob_b = a.get("birthDate"), b.get("birthDate")
                if a.get("id") == b.get("id") or not dob_a or not dob_b:
                    continue
                try:
                    gap_years = abs(
                        date.fromisoformat(dob_a).year - date.fromisoformat(dob_b).year
                    )
                except ValueError:
                    continue
                if gap_years > max_age_gap_years:
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

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/imranqureshi/git/cms-hte-patient-matching-test-set && uv run pytest evaluation/test_special_populations.py::TestMineSiblingNegatives -v`
Expected: all 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add evaluation/special_populations.py evaluation/test_special_populations.py
git commit -m "Add mine_sibling_negatives hard-negative miner"
```

---

## Task 7: `mine_name_collision_negatives` — near-identical name without ZIP/DOB overlap

**Files:**
- Modify: `evaluation/hard_negatives.py` (add `_levenshtein_distance`, `_full_name`, and
  `mine_name_collision_negatives` after `mine_shared_address_hard_negatives()`)
- Test: `evaluation/test_hard_negatives.py`

**Interfaces:**
- Consumes: `HardNegativeCandidate`, `_postal_code()` — both already defined in this file.
- Produces: `mine_name_collision_negatives(patients: Iterable[Patient], *, max_name_distance: int =
  1) -> List[HardNegativeCandidate]`.

- [ ] **Step 1: Write the failing tests**

```python
# add to evaluation/test_hard_negatives.py
from hard_negatives import mine_name_collision_negatives


def _named_patient(id_: str, given: str, family: str, zip_code: str, dob: str):
    return {
        "resourceType": "Patient",
        "id": id_,
        "name": [{"family": family, "given": [given]}],
        "birthDate": dob,
        "telecom": [],
        "address": [
            {"line": ["1 Main St"], "city": "NY", "state": "NY", "postalCode": zip_code}
        ],
        "identifier": [],
    }


class TestMineNameCollisionNegatives:
    def test_finds_near_identical_names_with_no_zip_or_dob_overlap(self) -> None:
        patients = [
            _named_patient("p1", "Pat", "Smith", "10001", "1980-01-01"),
            _named_patient("p2", "Pat", "Smyth", "20002", "1990-05-05"),
        ]
        candidates = mine_name_collision_negatives(patients)
        assert len(candidates) == 1
        assert candidates[0].shared_fields["name_distance"] == "1"

    def test_excludes_pairs_sharing_a_zip_code(self) -> None:
        patients = [
            _named_patient("p1", "Pat", "Smith", "10001", "1980-01-01"),
            _named_patient("p2", "Pat", "Smyth", "10001", "1990-05-05"),
        ]
        assert mine_name_collision_negatives(patients) == []

    def test_excludes_pairs_sharing_a_dob(self) -> None:
        patients = [
            _named_patient("p1", "Pat", "Smith", "10001", "1980-01-01"),
            _named_patient("p2", "Pat", "Smyth", "20002", "1980-01-01"),
        ]
        assert mine_name_collision_negatives(patients) == []

    def test_excludes_names_beyond_max_distance(self) -> None:
        patients = [
            _named_patient("p1", "Pat", "Smith", "10001", "1980-01-01"),
            _named_patient("p2", "Pat", "Johnson", "20002", "1990-05-05"),
        ]
        assert mine_name_collision_negatives(patients, max_name_distance=1) == []

    def test_excludes_identical_names(self) -> None:
        patients = [
            _named_patient("p1", "Pat", "Smith", "10001", "1980-01-01"),
            _named_patient("p2", "Pat", "Smith", "20002", "1990-05-05"),
        ]
        assert mine_name_collision_negatives(patients) == []

    def test_never_pairs_a_record_with_itself(self) -> None:
        patient = _named_patient("p1", "Pat", "Smith", "10001", "1980-01-01")
        assert mine_name_collision_negatives([patient, patient]) == []

    def test_different_first_letter_is_not_found_due_to_blocking(self) -> None:
        # Documents the accepted blocking-key tradeoff (see this module's
        # docstring): an edit at the very first letter crosses buckets and is
        # missed, same tradeoff mine_shared_address_hard_negatives() already
        # accepts for its own ZIP+DOB blocking key.
        patients = [
            _named_patient("p1", "Pat", "Smith", "10001", "1980-01-01"),
            _named_patient("p2", "Pat", "Amith", "20002", "1990-05-05"),
        ]
        assert mine_name_collision_negatives(patients) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/imranqureshi/git/cms-hte-patient-matching-test-set && uv run pytest evaluation/test_hard_negatives.py::TestMineNameCollisionNegatives -v`
Expected: FAIL with `ImportError: cannot import name 'mine_name_collision_negatives'`.

- [ ] **Step 3: Implement**

Add to `evaluation/hard_negatives.py`, immediately after `mine_shared_address_hard_negatives()`:

```python
def _full_name(patient: Patient) -> str:
    names = patient.get("name") or []
    if not names:
        return ""
    entry = names[0]
    given = entry.get("given") or []
    first = str(given[0]) if given else ""
    family = str(entry.get("family") or "")
    return f"{first} {family}".strip().upper()


def _levenshtein_distance(a: str, b: str) -> int:
    """Standard edit distance, stdlib-only - session 13 confirmed rapidfuzz
    is not an actual dependency of this repo (cited only in a docstring,
    never imported), so this avoids adding one just for this."""
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            current[j] = min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + cost,
            )
        previous = current
    return previous[-1]


def mine_name_collision_negatives(
    patients: Iterable[Patient], *, max_name_distance: int = 1
) -> List[HardNegativeCandidate]:
    """Pairs of distinct-ID patients whose full name (first given name +
    family name, uppercased) is within `max_name_distance` edit distance of
    each other, but who share NEITHER postal code NOR date of birth - the
    inverse signal from mine_shared_address_hard_negatives() (name differs,
    ZIP+DOB match). Targets the failure mode Luke Breyer (Epic) flagged in
    the 2026-09-22 workgroup meeting: a matcher that over-weights name
    similarity alone, with no corroborating field, should still reject this
    pair.

    Blocked by the full name's first letter (an O(n) bucketing pass before
    an O(k^2) within-bucket comparison, k = bucket size) rather than a full
    O(n^2) scan - mirrors mine_shared_address_hard_negatives()'s blocking
    rationale. A one-character edit at the very first letter of a name would
    cross buckets and be missed; accepted as the same kind of blocking-key
    tradeoff every exact-key miner in this module already makes."""
    buckets: Dict[str, List[Patient]] = defaultdict(list)
    for patient in patients:
        name = _full_name(patient)
        if not name or not _postal_code(patient) or not patient.get("birthDate"):
            continue
        buckets[name[0]].append(patient)

    candidates: List[HardNegativeCandidate] = []
    for group in buckets.values():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                if a.get("id") == b.get("id"):
                    continue
                if _postal_code(a) == _postal_code(b) or a.get("birthDate") == b.get(
                    "birthDate"
                ):
                    continue
                name_a, name_b = _full_name(a), _full_name(b)
                if name_a == name_b:
                    continue
                distance = _levenshtein_distance(name_a, name_b)
                if distance > max_name_distance:
                    continue
                candidates.append(
                    HardNegativeCandidate(
                        query=a,
                        candidate=b,
                        shared_fields={"name_distance": str(distance)},
                    )
                )
    return candidates
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/imranqureshi/git/cms-hte-patient-matching-test-set && uv run pytest evaluation/test_hard_negatives.py::TestMineNameCollisionNegatives -v`
Expected: all 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add evaluation/hard_negatives.py evaluation/test_hard_negatives.py
git commit -m "Add mine_name_collision_negatives hard-negative miner"
```

---

## Task 8: Wire all six new generators into `labeled_pairs.py`

**Files:**
- Modify: `evaluation/labeled_pairs.py`
- Test: `evaluation/test_labeled_pairs.py`

**Interfaces:**
- Consumes (all from prior tasks): `generate_compound_variant`, `ssn_dropped_variant`,
  `marriage_variant`, `phone_variant` (from `mutations`); `mine_name_collision_negatives` (from
  `hard_negatives`); `mine_sibling_negatives` (from `special_populations`).
- Produces: `generate_raw_pairs()` gains eight new keyword-only parameters (all default `True`/
  sensible numeric defaults, so existing callers are unaffected) and yields `RawPair`s with six new
  `strata["pair_type"]` values: `"compound_variant"`, `"ssn_dropped"`, `"marriage_variant"`,
  `"phone_variant"`, `"sibling_negative"`, `"name_collision_negative"`.

**Also fixes a real regression this task would otherwise introduce:** the existing
`test_can_disable_session_10_categories` (`evaluation/test_labeled_pairs.py:107-118`) asserts
`pair_types <= {"fuzzy_variant", "hard_negative"}` after disabling
`include_normalization_edge_cases`/`include_special_populations`. Since this task's six new
categories default to `True` and aren't covered by either of those two existing flags, that test
would start failing the moment `generate_raw_pairs()` changes — Step 3 below updates it in the
same commit, not as an afterthought.

- [ ] **Step 1: Write the failing tests**

```python
# add to evaluation/test_labeled_pairs.py
from mutations import SSN_SYSTEM


def test_generate_raw_pairs_includes_all_new_pair_types() -> None:
    patients = [
        {
            "resourceType": "Patient",
            "id": "p1",
            "name": [
                {"family": "Smith", "given": ["Katherine"]},
                {"family": "Jones", "given": ["Katherine"]},  # maiden-name proxy
            ],
            "birthDate": "1980-06-15",
            "telecom": [
                {"system": "phone", "value": "555-000-1111"},
                {"system": "phone", "value": "555-222-3333"},
            ],
            "address": [
                {"line": ["1 Main St"], "city": "NY", "state": "NY", "postalCode": "10001"}
            ],
            "identifier": [{"system": SSN_SYSTEM, "value": "123-45-6789"}],
        },
        _patient("p2", family="Rivera", given="Ana"),  # default zip 10001, dob 1980-06-15
        {
            **_patient("p3", family="Rivera", given="Luis"),
            "birthDate": "1981-01-01",  # 1-year gap from p2 -> sibling_negative, not household
        },
        {
            **_patient("p4", family="Smyth", given="Katherine"),
            "birthDate": "2001-02-02",
            "address": [
                {"line": ["9 Elm St"], "city": "LA", "state": "CA", "postalCode": "70007"}
            ],
            # "Katherine Smith" (p1) vs "Katherine Smyth" (p4): edit distance 1,
            # no shared ZIP or DOB -> name_collision_negative.
        },
    ]
    pairs = list(generate_raw_pairs(patients, seed=0))
    pair_types = {p.strata["pair_type"] for p in pairs}
    assert {
        "compound_variant",
        "ssn_dropped",
        "marriage_variant",
        "phone_variant",
        "sibling_negative",
        "name_collision_negative",
    }.issubset(pair_types)


def test_can_disable_all_new_pair_types() -> None:
    # Replaces the pre-existing assertion in test_can_disable_session_10_categories,
    # which only disabled include_normalization_edge_cases/include_special_populations
    # and would otherwise now fail: this task's six new categories default to True
    # and aren't covered by either of those two flags.
    patients = [_patient("p1"), _patient("p2", family="Jones", given="Robert")]
    pairs = list(
        generate_raw_pairs(
            patients,
            include_normalization_edge_cases=False,
            include_special_populations=False,
            include_compound_variants=False,
            include_ssn_dropped=False,
            include_marriage_variant=False,
            include_phone_variant=False,
            include_sibling_negatives=False,
            include_name_collision_negatives=False,
            seed=0,
        )
    )
    pair_types = {p.strata.get("pair_type") for p in pairs}
    assert pair_types <= {"fuzzy_variant", "hard_negative"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/imranqureshi/git/cms-hte-patient-matching-test-set && uv run pytest evaluation/test_labeled_pairs.py -k "includes_all_new_pair_types or can_disable_all_new_pair_types" -v`
Expected: `test_generate_raw_pairs_includes_all_new_pair_types` FAILS (missing pair types, since
`generate_raw_pairs()` doesn't produce them yet); `test_can_disable_all_new_pair_types` FAILS with
a `TypeError` (unexpected keyword arguments), since those parameters don't exist yet either.

- [ ] **Step 3: Implement**

In `evaluation/labeled_pairs.py`, update the imports (lines 51-59):

```python
from hard_negatives import mine_name_collision_negatives, mine_shared_address_hard_negatives
from mutations import (
    generate_compound_variant,
    generate_fuzzy_variant,
    marriage_variant,
    phone_variant,
    ssn_dropped_variant,
)
from normalization_edge_cases import diacritic_variant, punctuation_variant
from onc_loader import load_onc_patients
from special_populations import (
    INSTITUTION_TYPES,
    construct_institutional_negatives,
    mine_shared_surname_household_negatives,
    mine_sibling_negatives,
)
```

Update `generate_raw_pairs()`'s signature (lines 87-95):

```python
def generate_raw_pairs(
    patients: List[Patient],
    *,
    n_fuzzy_variants_per_patient: int = 1,
    include_normalization_edge_cases: bool = True,
    include_special_populations: bool = True,
    include_compound_variants: bool = True,
    n_compound_mutations: int = 2,
    include_ssn_dropped: bool = True,
    include_marriage_variant: bool = True,
    include_phone_variant: bool = True,
    include_sibling_negatives: bool = True,
    include_name_collision_negatives: bool = True,
    sibling_max_age_gap_years: int = 3,
    name_collision_max_distance: int = 1,
    institutional_group_size: int = 3,
    seed: int = 0,
) -> Iterator[RawPair]:
```

Update the docstring's first paragraph to add a sentence: "Session 14 further extends this with
compound (multi-field) true-match variants, SSN-dropped/marriage/phone-number true-match
scenarios, and sibling/name-collision hard negatives - all additive, default-on, appended alongside
every prior category."

Inside the `for p in patients:` loop, change to `for idx, p in enumerate(patients):` and add, right
after the existing `if include_normalization_edge_cases:` block (before the loop's end):

```python
        if include_compound_variants:
            compound, mutation_types = generate_compound_variant(
                p, n_mutations=n_compound_mutations, rng=rng
            )
            yield RawPair(
                pair_id=f"{p['id']}::compound::{'-'.join(mutation_types)}",
                query_patient=p,
                candidate_patient=compound,
                is_true_match=True,
                strata={
                    "pair_type": "compound_variant",
                    "mutations": ",".join(mutation_types),
                },
            )
        if include_ssn_dropped:
            dropped = ssn_dropped_variant(p)
            yield RawPair(
                pair_id=f"{p['id']}::ssn_dropped",
                query_patient=p,
                candidate_patient=dropped,
                is_true_match=True,
                strata={"pair_type": "ssn_dropped"},
            )
        if include_marriage_variant:
            donor = patients[(idx + 1) % len(patients)]
            married = marriage_variant(p, donor)
            yield RawPair(
                pair_id=f"{p['id']}::marriage_variant",
                query_patient=p,
                candidate_patient=married,
                is_true_match=True,
                strata={"pair_type": "marriage_variant"},
            )
        if include_phone_variant:
            phoned = phone_variant(p)
            yield RawPair(
                pair_id=f"{p['id']}::phone_variant",
                query_patient=p,
                candidate_patient=phoned,
                is_true_match=True,
                strata={"pair_type": "phone_variant"},
            )
```

Immediately after the existing `for candidate in mine_shared_address_hard_negatives(patients):`
block, before the `if not include_special_populations: return` line, add:

```python
    if include_name_collision_negatives:
        for name_candidate in mine_name_collision_negatives(
            patients, max_name_distance=name_collision_max_distance
        ):
            yield RawPair(
                pair_id=(
                    f"{name_candidate.query['id']}::"
                    f"{name_candidate.candidate['id']}::name_collision"
                ),
                query_patient=name_candidate.query,
                candidate_patient=name_candidate.candidate,
                is_true_match=False,
                strata={
                    "pair_type": "name_collision_negative",
                    **name_candidate.shared_fields,
                },
            )
```

Immediately after the existing `for household_candidate in
mine_shared_surname_household_negatives(patients):` block (still inside the
`if not include_special_populations: return`-gated section), add:

```python
    if include_sibling_negatives:
        for sibling_candidate in mine_sibling_negatives(
            patients, max_age_gap_years=sibling_max_age_gap_years
        ):
            yield RawPair(
                pair_id=(
                    f"{sibling_candidate.query['id']}::"
                    f"{sibling_candidate.candidate['id']}::sibling"
                ),
                query_patient=sibling_candidate.query,
                candidate_patient=sibling_candidate.candidate,
                is_true_match=False,
                strata={
                    "pair_type": "sibling_negative",
                    **sibling_candidate.shared_fields,
                },
            )
```

Remove the now-superseded `test_can_disable_session_10_categories` test
(`evaluation/test_labeled_pairs.py:107-118`) — Step 1's `test_can_disable_all_new_pair_types`
covers the same disable-and-check-subset behavior plus the six new flags, so keeping both would
just leave a redundant, narrower duplicate.

Finally, update the `__main__` block's count-key fallback chain (around line 189-191) to also
surface the compound-variant breakdown:

```python
    counts = Counter(
        (
            p.strata.get("pair_type"),
            p.strata.get("mutation")
            or p.strata.get("case")
            or p.strata.get("category")
            or p.strata.get("mutations"),
        )
        for p in pairs
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/imranqureshi/git/cms-hte-patient-matching-test-set && uv run pytest evaluation/test_labeled_pairs.py -v`
Expected: all tests in this file PASS, including the new one.

- [ ] **Step 5: Run the full suite and the manual smoke script**

Run: `cd /Users/imranqureshi/git/cms-hte-patient-matching-test-set && make tests`
Expected: all green.

Run: `cd /Users/imranqureshi/git/cms-hte-patient-matching-test-set && PYTHONPATH=. uv run python evaluation/labeled_pairs.py`
Expected: printed summary includes nonzero counts for `compound_variant`, `ssn_dropped`,
`marriage_variant`, `phone_variant`, `sibling_negative`, and (if the sampled shard happens to
contain a qualifying pair — not guaranteed at every `SAMPLE_SIZE`) `name_collision_negative`.

- [ ] **Step 6: Commit**

```bash
git add evaluation/labeled_pairs.py evaluation/test_labeled_pairs.py
git commit -m "Wire compound variants and new hard negatives into generate_raw_pairs"
```

---

## Task 9: Documentation updates

**Files:**
- Modify: `evaluation/cases/README.md` (mutation/hard-negative category list/table)
- Modify: `evaluation/SYNTHETIC_DATA_SETUP.md` (if it enumerates categories — check first) or
  `evaluation/DESIGN.md`, whichever file the executing engineer confirms (via grep for the string
  "fuzzy_variant" or "hard_negative") actually documents the category list today
- Modify: `docs/sessions/pending/session_14.md` (resolve the phone-type open question, record the
  `PHONE2` finding)

- [ ] **Step 1: Locate the category-list documentation**

Run: `cd /Users/imranqureshi/git/cms-hte-patient-matching-test-set && grep -rln "fuzzy_variant\|hard_negative" evaluation/*.md evaluation/cases/*.md`

- [ ] **Step 2: Update the category list**

In whichever file(s) Step 1 finds, add six rows/bullets documenting: `compound_variant`,
`ssn_dropped`, `marriage_variant`, `phone_variant`, `sibling_negative`,
`name_collision_negative` — one sentence each, matching the existing entries' style (see how
`normalization_edge_case`/`special_population` categories are already described there).

- [ ] **Step 3: Resolve session_14.md's open question**

In `docs/sessions/pending/session_14.md`'s "Open questions" section, replace the "Phone-type field
availability" bullet's speculative wording with the confirmed finding: ONC has no phone-`use`
semantic, but does carry a second raw phone column (`PHONE2`) that `onc_loader.py` did not
previously load; Task 1 of this plan loads it, and `phone_variant()` uses it to model two distinct
on-file phone numbers per person without fabricating a `use` code.

- [ ] **Step 4: Run the full verification suite one more time**

Run: `cd /Users/imranqureshi/git/cms-hte-patient-matching-test-set && make tests && make lint && make typecheck && make run-pre-commit`
Expected: all clean.

- [ ] **Step 5: Commit**

```bash
git add evaluation/cases/README.md evaluation/SYNTHETIC_DATA_SETUP.md evaluation/DESIGN.md docs/sessions/pending/session_14.md
git commit -m "Document new compound-variant and hard-negative categories"
```

(Adjust the file list in the `git add` to whatever Step 1 actually found and edited.)

---

## Final verification checklist

- [ ] `make tests` — full suite green, including every new test file/class above.
- [ ] `make lint` / `make typecheck` / `make run-pre-commit` — all clean.
- [ ] `PYTHONPATH=. uv run python evaluation/labeled_pairs.py` — prints nonzero counts for all six
      new `pair_type` categories against at least one real-ONC-fixture run (re-run with a larger
      `SAMPLE_SIZE` if `name_collision_negative`/`sibling_negative` show zero at the default 2000).
- [ ] Every no-op path (missing SSN, single phone, no maiden-name entry, `n_mutations < 2`) has an
      explicit passing test, not just the happy path — per this plan's Review Focus.
- [ ] `docs/sessions/pending/session_14.md`'s phone-type open question is resolved with the actual
      finding, not left speculative.
