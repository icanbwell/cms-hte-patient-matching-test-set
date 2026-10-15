# v1 Release: Conformance, Near-Miss Negatives, Realistic Dataset Release (Session 16, one PR)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the realistic dataset in the repo as the v1 release: FHIR-conformant resources, real hard negatives and near-miss decoys in both tiers, a pairwise tier that is 50% negatives, and a gate in CI that a fresh clone passes.

**Architecture:** Fix the loader at the source and add a conformance validator (Tasks 1-7). Add a streaming reverse-blocking finder that, for each sampled query, scans every ONC shard once and keeps real look-alike records (Task 8). Feed those decoys into both tiers under the existing category names (`hard_negative`, `name_collision_negative`, `sibling_negative`) plus a new `near_miss_negative` (Tasks 10-12), rebalance the pairwise tier to 50% negatives by subsampling positives, extend the audit and gate (Tasks 9, 13), then commit the realistic files and run their gate in CI (Task 14).

**Tech Stack:** Python 3.12, pytest, ruff, mypy, uv. No new dependencies.

**Spec:** `docs/sessions/completed/session_16.md` (Workstreams 1, 2 and 4, plus "Release caveats"). Ticket BAI-1156. This one PR covers former PRs 1, 2 and 4 and the decoy part of PR 3. Not in this PR: queries with 0 or 1 expected matches (E3), family structure (E1, PR 5), the age vintage (E2), and `strata.decoy_kinds` on query rows.

**Commit structure:** one commit per task, so the PR reads as separable workstreams: Tasks 1-7 conformance and `marriage_variant` retirement, Tasks 8-13 near-miss negatives and gate, Tasks 14-15 release route, regeneration and docs.

## Global Constraints

- `from __future__ import annotations` at the top of every module; `typing.Dict`/`List`/`Set` rather than builtin generics.
- Run tests with `uv run pytest <path> -v`; lint with `uv run ruff check <files>`; types with `uv run mypy evaluation`. Commit hooks run ruff.
- No new runtime dependency.
- Never emit an empty string, empty array, empty object or null in a `Patient`.
- No fabricated attributes: no `telecom.use` or `period` on base records. `rank` is derivable from column order and is emitted.
- Values copied from ONC are not normalized (case and punctuation preserved).
- MOTHERS_MAIDEN_NAME maps to the extension `http://hl7.org/fhir/StructureDefinition/patient-mothersMaidenName` (decided), never to a `name` entry.
- No fabricated identities: every decoy is a real ONC record that passes `identity_guard.is_possible_same_person` against its query and is not in the sample or donor pool.
- Memory: one shard in memory at a time. The finder streams; it never builds a 1M-record list.
- Tier parity: every category present in the pairwise file is also present in the population file (`audit.tier_parity_gap` stays 0).
- Commit messages start with `BAI-1156 `. No AI-attribution trailer. Branch: `IQ-BAI-1156`.
- Committed files under `evaluation/cases/` are regenerated only in Tasks 14 and 15.

## Review Focus

- **Patient with no name parts, or no phone/address/SSN/email:** keys are omitted and no reader raises. Pinned in Tasks 2, 3 and 7.
- **`PHONE2` with `^` and empty parts (`"^^"`, `"555^"`, `"^555"`):** empties dropped, no caret survives. Pinned in Task 3.
- **Mutators leaving `[]` behind, and placeholder SSNs created from nothing:** pruned at write time and typed. Pinned in Tasks 4 and 5.
- **`marriage_variant` retirement:** superseded. Task 6 was not carried out as written: `marriage_variant` was kept (it reads the mother's maiden name from the extension) and its case ids still exist.
- **A query with no look-alikes anywhere (rare surname, no DOB, no address):** the finder returns nothing for it and the pools and pairs still build. Pinned in Task 8.
- **A common DOB or surname flooding a query:** per-kind cap keeps at most 3 per kind per query, deterministically. Pinned in Task 8.
- **A decoy that is secretly the query (same SSN, or same first name + family + DOB under another id):** never emitted. Pinned in Task 8.
- **Too few negatives to reach 50%:** the rebalancer never drops negatives, never drops a category below its floor, and reports the shortfall instead of failing silently. Pinned in Task 10.
- **Fresh clone with committed realistic files:** the gate and the manifest-sync test pass without running the generator. Pinned in Task 14.

---

## File Structure

| File | Responsibility |
|---|---|
| `evaluation/fhir_conformance.py` (create) | `violations(patient)`, `prune_empty(value)`. No repo imports. |
| `evaluation/near_miss.py` (create) | `find_near_misses(...)`, `NearMiss`, `NearMissResult`. Streaming reverse-blocking finder. |
| `evaluation/negative_balance.py` (create) | `rebalance_negatives(records, ...)`: subsample positives to a target negative share. |
| `evaluation/onc_loader.py` (modify) | Conformant mapping; `ssn_identifier`. |
| `evaluation/placeholders.py` (modify) | Typed SSN on creation. |
| `evaluation/export_test_dataset.py`, `export_population_dataset.py`, `export_full_onc_dataset.py` (modify) | `prune_empty` at serialization; `near_misses` plumbing in `build_test_case_records`. |
| `evaluation/labeled_pairs.py` (modify) | Retire `marriage_variant`; emit near-miss negative pairs. |
| `evaluation/population_cases.py` (modify) | Add near-miss decoys to query pools. |
| `evaluation/scenarios.py`, `drift_profile.py`, `mutations.py` (modify) | Retire `marriage_variant`. |
| `evaluation/audit.py`, `release_thresholds_realistic.json` (modify) | New metrics and thresholds. |
| `evaluation/export_realistic_dataset.py` (modify) | Second streaming pass, rebalance, manifest. |
| `evaluation/test_*.py` (create/modify) | Tests per module; `test_committed_realistic.py` (create). |
| `.gitignore`, `.github/workflows/build_and_test.yml`, `evaluation/cases/*` (modify) | Commit realistic files; gate them in CI. |
| `evaluation/cases/README.md`, `CLAUDE.md`, `docs/sessions/completed/session_16.md` (modify) | Docs and changelog. |

---

### Task 1: Conformance validator

**Files:**
- Create: `evaluation/fhir_conformance.py`
- Test: `evaluation/test_fhir_conformance.py`

**Interfaces:**
- Produces: `violations(patient: Dict[str, Any]) -> List[str]` (empty list means conformant) and `prune_empty(value: Any) -> Any` (returns a copy with `""`, `[]`, `{}` and `None` removed recursively, leaving `0` and `False` alone). Constants `SSN_SYSTEM`, `V2_0203_SYSTEM`.

- [ ] **Step 1: Write the failing tests**

Create `evaluation/test_fhir_conformance.py`:

```python
"""Unit tests for fhir_conformance.py."""

from __future__ import annotations

from fhir_conformance import SSN_SYSTEM, V2_0203_SYSTEM, prune_empty, violations

SSN_TYPE = {"coding": [{"system": V2_0203_SYSTEM, "code": "SS"}]}


def _patient(**overrides):
    base = {
        "resourceType": "Patient",
        "id": "1",
        "name": [{"use": "official", "family": "Smith", "given": ["Jane"]}],
        "gender": "female",
        "telecom": [{"system": "phone", "value": "555-000-1111", "rank": 1}],
        "identifier": [
            {"system": SSN_SYSTEM, "type": SSN_TYPE, "value": "892-39-5115"}
        ],
    }
    base.update(overrides)
    return base


class TestViolations:
    def test_a_conformant_patient_has_no_violations(self) -> None:
        assert violations(_patient()) == []

    def test_empty_string_is_reported_with_its_path(self) -> None:
        patient = _patient(name=[{"use": "official", "family": "Smith", "given": [""]}])
        assert violations(patient) == ["name[0].given[0]: empty string"]

    def test_empty_array_is_reported(self) -> None:
        assert violations(_patient(address=[])) == ["address: empty array"]

    def test_null_is_reported(self) -> None:
        assert violations(_patient(birthDate=None)) == ["birthDate: null"]

    def test_caret_in_telecom_value_is_reported(self) -> None:
        patient = _patient(
            telecom=[{"system": "phone", "value": "555-000-1111^^555-222-3333"}]
        )
        assert violations(patient) == ["telecom[0].value: contains '^'"]

    def test_unknown_telecom_system_is_reported(self) -> None:
        patient = _patient(telecom=[{"system": "carrier-pigeon", "value": "x"}])
        assert violations(patient) == [
            "telecom[0].system: 'carrier-pigeon' not a ContactPointSystem"
        ]

    def test_duplicate_rank_within_a_system_is_reported(self) -> None:
        patient = _patient(
            telecom=[
                {"system": "phone", "value": "1", "rank": 1},
                {"system": "phone", "value": "2", "rank": 1},
            ]
        )
        assert violations(patient) == ["telecom: duplicate rank within system 'phone'"]

    def test_same_rank_in_different_systems_is_fine(self) -> None:
        patient = _patient(
            telecom=[
                {"system": "phone", "value": "1", "rank": 1},
                {"system": "email", "value": "a@b.c", "rank": 1},
            ]
        )
        assert violations(patient) == []

    def test_name_use_outside_the_binding_is_reported(self) -> None:
        patient = _patient(name=[{"use": "alias", "family": "Smith"}])
        assert violations(patient) == ["name[0].use: 'alias' not in NameUse"]

    def test_ssn_identifier_without_type_is_reported(self) -> None:
        patient = _patient(identifier=[{"system": SSN_SYSTEM, "value": "892-39-5115"}])
        assert violations(patient) == [
            "identifier[0]: SSN identifier lacks type coding SS"
        ]


class TestPruneEmpty:
    def test_removes_empty_values_recursively(self) -> None:
        value = {"a": "", "b": [], "c": {}, "d": None, "e": {"f": [""], "g": 1}}
        assert prune_empty(value) == {"e": {"g": 1}}

    def test_keeps_zero_and_false(self) -> None:
        assert prune_empty({"rank": 0, "active": False}) == {"rank": 0, "active": False}

    def test_does_not_mutate_its_input(self) -> None:
        value = {"identifier": []}
        prune_empty(value)
        assert value == {"identifier": []}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest evaluation/test_fhir_conformance.py -v`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'fhir_conformance'`.

- [ ] **Step 3: Write the implementation**

Create `evaluation/fhir_conformance.py`:

```python
"""Structural FHIR R4 conformance checks for emitted Patient resources.

Pure Python, no dependency on the rest of the repo. This is a structural
floor (no empty values, bound code sets, typed SSN identifiers, unique ranks),
not a replacement for the official HL7 validator, which is run manually once
per release (session 16 design doc, Workstream 1).
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List

Patient = Dict[str, Any]

SSN_SYSTEM = "http://hl7.org/fhir/sid/us-ssn"
V2_0203_SYSTEM = "http://terminology.hl7.org/CodeSystem/v2-0203"

NAME_USES = frozenset(
    {"usual", "official", "temp", "nickname", "anonymous", "old", "maiden"}
)
TELECOM_SYSTEMS = frozenset({"phone", "fax", "email", "pager", "url", "sms", "other"})

_EMPTY = ("", [], {}, None)


def prune_empty(value: Any) -> Any:
    """A copy of `value` with "", [], {} and None removed recursively.

    0 and False are kept. FHIR forbids empty strings, arrays and objects, and
    some mutators leave them behind (e.g. ssn_dropped leaves identifier: [])."""
    if isinstance(value, dict):
        pruned = {key: prune_empty(item) for key, item in value.items()}
        return {key: item for key, item in pruned.items() if item not in _EMPTY}
    if isinstance(value, list):
        items = [prune_empty(item) for item in value]
        return [item for item in items if item not in _EMPTY]
    return value


def _empties(value: Any, path: str) -> Iterator[str]:
    if isinstance(value, dict):
        if not value and path:
            yield f"{path}: empty object"
        for key, item in value.items():
            yield from _empties(item, f"{path}.{key}" if path else key)
    elif isinstance(value, list):
        if not value:
            yield f"{path}: empty array"
        for index, item in enumerate(value):
            yield from _empties(item, f"{path}[{index}]")
    elif isinstance(value, str):
        if not value.strip():
            yield f"{path}: empty string"
    elif value is None:
        yield f"{path}: null"


def _has_coding(identifier: Dict[str, Any], code: str) -> bool:
    codings = (identifier.get("type") or {}).get("coding") or []
    return any(
        c.get("system") == V2_0203_SYSTEM and c.get("code") == code for c in codings
    )


def violations(patient: Patient) -> List[str]:
    """Human-readable conformance problems; an empty list means conformant."""
    found = list(_empties(patient, ""))
    for index, entry in enumerate(patient.get("name") or []):
        use = entry.get("use")
        if use is not None and use not in NAME_USES:
            found.append(f"name[{index}].use: {use!r} not in NameUse")
    ranks: Dict[str, List[Any]] = {}
    for index, contact in enumerate(patient.get("telecom") or []):
        system = contact.get("system")
        if system not in TELECOM_SYSTEMS:
            found.append(
                f"telecom[{index}].system: {system!r} not a ContactPointSystem"
            )
        if "^" in str(contact.get("value") or ""):
            found.append(f"telecom[{index}].value: contains '^'")
        if "rank" in contact:
            ranks.setdefault(str(system), []).append(contact["rank"])
    for system, values in ranks.items():
        if len(values) != len(set(values)):
            found.append(f"telecom: duplicate rank within system {system!r}")
    for index, identifier in enumerate(patient.get("identifier") or []):
        if identifier.get("system") == SSN_SYSTEM and not _has_coding(identifier, "SS"):
            found.append(f"identifier[{index}]: SSN identifier lacks type coding SS")
    return found
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest evaluation/test_fhir_conformance.py -v`
Expected: all PASS.

- [ ] **Step 5: Lint, types, commit**

```bash
uv run ruff check evaluation/fhir_conformance.py evaluation/test_fhir_conformance.py
uv run mypy evaluation/fhir_conformance.py
git add evaluation/fhir_conformance.py evaluation/test_fhir_conformance.py
git commit -m "BAI-1156 add FHIR structural conformance validator and prune_empty"
```

---

### Task 2: Loader names, alias and mother's maiden name

**Files:**
- Modify: `evaluation/onc_loader.py:1-29` (docstring), `:59-87` (names and patient skeleton)
- Test: `evaluation/test_onc_loader.py`

**Interfaces:**
- Consumes: `violations` from Task 1.
- Produces: `_row_to_patient(row)` returns `name` as a list holding at most one `use: "official"` entry (keys `family`, `given`, `suffix` only when non-empty) followed by at most one `{"use": "nickname", "text": ALIAS}` entry; `name` is absent when neither exists. `extension` holds the mother's-maiden-name extension when the column is non-empty. Constant `MOTHERS_MAIDEN_NAME_URL`.

- [ ] **Step 1: Write the failing tests**

Append to `evaluation/test_onc_loader.py` (add `from fhir_conformance import violations` and `from onc_loader import MOTHERS_MAIDEN_NAME_URL` to the imports):

```python
class TestNames:
    def test_empty_first_name_emits_no_given(self) -> None:
        patient = _row_to_patient(_row(FIRST=""))
        assert "given" not in patient["name"][0]
        assert violations(patient) == []

    def test_blank_suffix_and_middle_are_omitted(self) -> None:
        patient = _row_to_patient(_row(MIDDLE="", SUFFIX=""))
        assert patient["name"] == [
            {"use": "official", "family": "SMITH", "given": ["JANE"]}
        ]

    def test_middle_is_appended_to_given_and_suffix_kept(self) -> None:
        patient = _row_to_patient(_row(MIDDLE="Q", SUFFIX="JR"))
        assert patient["name"][0]["given"] == ["JANE", "Q"]
        assert patient["name"][0]["suffix"] == ["JR"]

    def test_alias_is_a_separate_nickname_entry_not_a_given_name(self) -> None:
        patient = _row_to_patient(_row(ALIAS="JANIE"))
        assert patient["name"][0]["given"] == ["JANE"]
        assert patient["name"][1] == {"use": "nickname", "text": "JANIE"}

    def test_row_with_no_name_parts_omits_name(self) -> None:
        patient = _row_to_patient(_row(FIRST="", LAST="", MIDDLE="", SUFFIX=""))
        assert "name" not in patient


class TestMothersMaidenName:
    def test_maps_to_the_standard_extension_not_a_name_entry(self) -> None:
        patient = _row_to_patient(_row(MOTHERS_MAIDEN_NAME="JONES"))
        assert len(patient["name"]) == 1
        assert patient["extension"] == [
            {"url": MOTHERS_MAIDEN_NAME_URL, "valueString": "JONES"}
        ]

    def test_absent_when_the_column_is_empty(self) -> None:
        assert "extension" not in _row_to_patient(_row())
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest evaluation/test_onc_loader.py -v`
Expected: ImportError for `MOTHERS_MAIDEN_NAME_URL` (collection error).

- [ ] **Step 3: Implement**

In `evaluation/onc_loader.py`, replace the module docstring paragraph beginning "Column mapping mirrors..." through "...which that transform reads from the CSV but never maps into the output FHIR resource." with:

```
Column mapping started from the legacy production matching engine's own
create_patient_resource() transform and is now FHIR R4 conformant: empty
columns are omitted (never emitted as ""/[]), ALIAS becomes a separate
`use: nickname` name, and MOTHERS_MAIDEN_NAME maps to the standard
patient-mothersMaidenName extension (it is the mother's maiden name, not the
patient's own prior surname).
```

Add near the other constants (below `_GENDER_MAP`):

```python
MOTHERS_MAIDEN_NAME_URL = (
    "http://hl7.org/fhir/StructureDefinition/patient-mothersMaidenName"
)


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _human_names(row: Dict[str, str]) -> List[Dict[str, Any]]:
    official: Dict[str, Any] = {"use": "official"}
    family = _clean(row.get("LAST"))
    if family:
        official["family"] = family
    given = [g for g in (_clean(row.get("FIRST")), _clean(row.get("MIDDLE"))) if g]
    if given:
        official["given"] = given
    suffix = _clean(row.get("SUFFIX"))
    if suffix:
        official["suffix"] = [suffix]
    names: List[Dict[str, Any]] = [official] if len(official) > 1 else []
    alias = _clean(row.get("ALIAS"))
    if alias:
        names.append({"use": "nickname", "text": alias})
    return names
```

Replace the top of `_row_to_patient` (from `given = [row["FIRST"]]` through the closing `}` of the `patient` dict literal) with:

```python
    patient: Dict[str, Any] = {
        "resourceType": "Patient",
        "id": row["EnterpriseID"],
        "gender": _GENDER_MAP.get(row.get("GENDER", "").upper(), "unknown"),
        "telecom": [],
        "address": [],
        "identifier": [],
    }
    names = _human_names(row)
    if names:
        patient["name"] = names
    mothers_maiden_name = _clean(row.get("MOTHERS_MAIDEN_NAME"))
    if mothers_maiden_name:
        patient["extension"] = [
            {"url": MOTHERS_MAIDEN_NAME_URL, "valueString": mothers_maiden_name}
        ]
```

(Task 3 removes the three empty lists.)

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest evaluation/test_onc_loader.py -v`
Expected: the new `TestNames` and `TestMothersMaidenName` tests PASS. `violations(patient) == []` in `test_empty_first_name_emits_no_given` still fails here because of the empty lists; if it fails, that is expected until Task 3. If so, change that one assertion to `assert not [v for v in violations(patient) if v.startswith("name")]` for now and restore it to `== []` in Task 3 Step 3.

- [ ] **Step 5: Commit**

```bash
uv run ruff check evaluation/onc_loader.py evaluation/test_onc_loader.py
git add evaluation/onc_loader.py evaluation/test_onc_loader.py
git commit -m "BAI-1156 loader: omit empty name parts, alias as nickname entry, mother's maiden name as extension"
```

---

### Task 3: Loader telecom, address and identifier

**Files:**
- Modify: `evaluation/onc_loader.py` (the rest of `_row_to_patient`)
- Test: `evaluation/test_onc_loader.py`

**Interfaces:**
- Produces: `ssn_identifier(value: str) -> Dict[str, Any]` (system `SSN_SYSTEM`, `type.coding` of v2-0203 `SS`, `value`); `_row_to_patient` emits `telecom` entries `{"system", "value", "rank"}` with rank 1..n per system in column order, omits `telecom`/`address`/`identifier` when empty, and omits blank `city`/`state`/`postalCode`.

- [ ] **Step 1: Write the failing tests**

Update the existing `test_email_still_loads_after_both_phones` in `test_onc_loader.py` to expect the rank, then append the new tests (add `from fhir_conformance import V2_0203_SYSTEM` and `from onc_loader import ssn_identifier` to the imports):

```python
# replace the body of test_email_still_loads_after_both_phones' assertion with:
        assert patient["telecom"][-1] == {
            "system": "email",
            "value": "jane@example.com",
            "rank": 1,
        }


class TestTelecom:
    def test_caret_joined_phone_is_split_into_one_entry_per_number(self) -> None:
        patient = _row_to_patient(_row(PHONE2="555-000-1111^^555-222-3333"))
        assert [t["value"] for t in patient["telecom"]] == [
            "555-000-1111",
            "555-222-3333",
        ]
        assert violations(patient) == []

    def test_empty_parts_around_carets_are_dropped(self) -> None:
        for raw in ("^^", "555-000-1111^", "^555-000-1111", "^^555-000-1111^^"):
            patient = _row_to_patient(_row(PHONE=raw))
            values = [t["value"] for t in patient.get("telecom", [])]
            assert all("^" not in v and v for v in values), raw

    def test_rank_follows_column_order_per_system(self) -> None:
        patient = _row_to_patient(
            _row(PHONE="1", PHONE2="2", EMAIL="a@b.c")
        )
        assert [(t["system"], t["rank"]) for t in patient["telecom"]] == [
            ("phone", 1),
            ("phone", 2),
            ("email", 1),
        ]

    def test_telecom_carries_no_use_or_period(self) -> None:
        patient = _row_to_patient(_row(PHONE="555-000-1111"))
        assert set(patient["telecom"][0]) == {"system", "value", "rank"}


class TestAddressAndIdentifier:
    def test_blank_city_state_zip_are_omitted(self) -> None:
        patient = _row_to_patient(_row(ADDRESS1="1 MAIN ST"))
        assert patient["address"] == [{"line": ["1 MAIN ST"]}]

    def test_ssn_identifier_is_typed(self) -> None:
        patient = _row_to_patient(_row(SSN="892-39-5115"))
        assert patient["identifier"] == [ssn_identifier("892-39-5115")]
        assert patient["identifier"][0]["type"]["coding"] == [
            {"system": V2_0203_SYSTEM, "code": "SS"}
        ]

    def test_empty_row_has_no_empty_lists(self) -> None:
        patient = _row_to_patient(_row())
        assert violations(patient) == []
        for key in ("telecom", "address", "identifier"):
            assert key not in patient
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest evaluation/test_onc_loader.py -v`
Expected: ImportError for `ssn_identifier` (collection error).

- [ ] **Step 3: Implement**

In `onc_loader.py` add `import re` to the imports, add below `_human_names`:

```python
_SSN_SYSTEM = "http://hl7.org/fhir/sid/us-ssn"
_V2_0203_SYSTEM = "http://terminology.hl7.org/CodeSystem/v2-0203"


def ssn_identifier(value: str) -> Dict[str, Any]:
    """A US SSN identifier with the v2-0203 `SS` type coding."""
    return {
        "system": _SSN_SYSTEM,
        "type": {"coding": [{"system": _V2_0203_SYSTEM, "code": "SS"}]},
        "value": value,
    }


def _phone_numbers(raw: str | None) -> List[str]:
    """ONC phone columns sometimes hold several numbers joined by HL7 '^'."""
    return [part for part in (p.strip() for p in re.split(r"\^+", raw or "")) if part]
```

Delete `"telecom": [], "address": [], "identifier": [],` from the `patient` dict built in Task 2, and replace everything after the `birthDate` block (from `if row.get("PHONE"):` to `return patient`) with:

```python
telecom: List[Dict[str, Any]] = []
phones = _phone_numbers(row.get("PHONE")) + _phone_numbers(row.get("PHONE2"))
for rank, value in enumerate(phones, start=1):
    telecom.append({"system": "phone", "value": value, "rank": rank})
email = _clean(row.get("EMAIL"))
if email:
    telecom.append({"system": "email", "value": email, "rank": 1})
if telecom:
    patient["telecom"] = telecom
line1 = _clean(row.get("ADDRESS1"))
if line1:
    address: Dict[str, Any] = {
        "line": [line1]
        + ([_clean(row["ADDRESS2"])] if _clean(row.get("ADDRESS2")) else [])
    }
    for key, column in (("city", "CITY"), ("state", "STATE"), ("postalCode", "ZIP")):
        part = _clean(row.get(column))
        if part:
            address[key] = part
    patient["address"] = [address]
ssn = _clean(row.get("SSN"))
if ssn:
    patient["identifier"] = [ssn_identifier(ssn)]
return patient
```

Also update the `birthDate` guard comment if needed, but leave the `if row.get("DOB"):` block as is. Restore the full `violations(patient) == []` assertion in `test_empty_first_name_emits_no_given` if Task 2 weakened it.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest evaluation/test_onc_loader.py evaluation/test_fhir_conformance.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check evaluation/onc_loader.py evaluation/test_onc_loader.py
uv run ruff format evaluation/onc_loader.py evaluation/test_onc_loader.py
git add evaluation/onc_loader.py evaluation/test_onc_loader.py
git commit -m "BAI-1156 loader: split caret phones, rank telecom, type SSN identifier, omit empty elements"
```

---

### Task 4: Typed SSN in placeholders, and a loader-wide sweep

**Files:**
- Modify: `evaluation/placeholders.py:72-76`
- Test: `evaluation/test_placeholders.py`, `evaluation/test_fhir_conformance.py`

**Interfaces:**
- Consumes: `ssn_identifier` (Task 3), `violations`, `prune_empty` (Task 1), `iter_shard_batches` is NOT used (too slow).
- Produces: `placeholders._apply_placeholder` (the function whose docstring starts "A copy of `patient` with `field` set to the placeholder `value`") now creates typed SSN identifiers.

- [ ] **Step 1: Write the failing tests**

Add to `evaluation/test_fhir_conformance.py` (add imports `csv`, `from itertools import islice`, `from onc_loader import _row_to_patient`, `from export_inputs import ONC_DIR`):

```python
class TestCorpus:
    def test_every_50th_row_of_every_onc_shard_is_conformant(self) -> None:
        checked = 0
        for path in sorted(ONC_DIR.glob("*.csv")):
            with open(path, newline="", encoding="utf-8") as f:
                for index, row in enumerate(csv.DictReader(f)):
                    if index % 50:
                        continue
                    patient = _row_to_patient(row)
                    assert violations(patient) == [], (path.name, row["EnterpriseID"])
                    checked += 1
        assert checked > 15000
```

Find the function name and the SSN-creating test in `test_placeholders.py` (line ~69 asserts `created["identifier"][0]["value"] == "999-99-9999"`); add directly after that test:

```python
    def test_created_ssn_identifier_carries_the_ssn_type(self) -> None:
        # Same call as the test above that checks created["identifier"][0]["value"];
        # reuse its arguments.
        assert violations(created) == []
```

Open `evaluation/test_placeholders.py` around line 60-70 first and copy the exact call that builds `created` into this test body (it is a one-line call to the placeholder function with `create_missing=True` on a patient that has no SSN), and add `from fhir_conformance import violations` to the imports.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest evaluation/test_placeholders.py evaluation/test_fhir_conformance.py -v`
Expected: the new placeholder test FAILS with `identifier[0]: SSN identifier lacks type coding SS`; the corpus test PASSES (it exercises Task 3's loader).

- [ ] **Step 3: Implement**

In `evaluation/placeholders.py` replace

```python
modified.setdefault("identifier", []).append({"system": SSN_SYSTEM, "value": value})
```

with

```python
                modified.setdefault("identifier", []).append(ssn_identifier(value))
```

and add `from onc_loader import ssn_identifier` to its imports.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest evaluation/test_placeholders.py evaluation/test_fhir_conformance.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check evaluation/placeholders.py evaluation/test_placeholders.py evaluation/test_fhir_conformance.py
git add evaluation/placeholders.py evaluation/test_placeholders.py evaluation/test_fhir_conformance.py
git commit -m "BAI-1156 placeholders: typed SSN identifier; add ONC corpus conformance test"
```

---

### Task 5: Prune empties at every serialization point

**Files:**
- Modify: `evaluation/export_test_dataset.py:184-203` (`write_jsonl`), `evaluation/export_population_dataset.py:49-73`, `evaluation/export_full_onc_dataset.py:87`, `:128`, `:131`
- Test: `evaluation/test_export_test_dataset.py`, `evaluation/test_export_population_dataset.py`, `evaluation/test_fhir_conformance.py`

**Interfaces:**
- Consumes: `prune_empty`, `violations` (Task 1).
- Produces: every `Patient` body written to JSONL has no empty values.

- [ ] **Step 1: Write the failing tests**

Add to `evaluation/test_export_test_dataset.py` (import `LabeledCaseRecord`, `write_jsonl`, `json` already present):

```python
def test_write_jsonl_drops_empty_arrays_and_strings(tmp_path):
    patient = _patient("p1")  # has identifier: [] and telecom: []
    patient["name"][0]["suffix"] = []
    record = LabeledCaseRecord(
        case_id="p1::x",
        source=patient,
        target=patient,
        expected_match=True,
        rationale="r",
    )
    path = tmp_path / "out.jsonl"
    write_jsonl([record], path)
    row = json.loads(path.read_text())
    for side in ("source", "target"):
        assert "identifier" not in row[side]
        assert "telecom" not in row[side]
        assert "suffix" not in row[side]["name"][0]
```

Add to `evaluation/test_export_population_dataset.py`:

```python
def test_population_files_drop_empty_arrays(tmp_path):
    dataset = build_population_dataset(
        [_patient("p1"), _patient("p2", family="Jones", given="Robert")], seed=0
    )
    candidates_path = tmp_path / "c.jsonl"
    queries_path = tmp_path / "q.jsonl"
    write_population_dataset(dataset, candidates_path, queries_path)
    for line in candidates_path.read_text().splitlines():
        assert "identifier" not in json.loads(line)["patient"]
    for line in queries_path.read_text().splitlines():
        assert "identifier" not in json.loads(line)["query"]
```

Add to `evaluation/test_fhir_conformance.py` (add imports `from labeled_pairs import generate_raw_pairs`, `from export_inputs import load_sample_and_donors`):

```python
class TestGeneratedPairs:
    def test_every_generated_pair_is_conformant_after_pruning(self) -> None:
        patients, donors = load_sample_and_donors(300, 300)
        for pair in generate_raw_pairs(patients, donors=donors, seed=0):
            for side in (pair.query_patient, pair.candidate_patient):
                assert violations(prune_empty(side)) == [], pair.pair_id
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest evaluation/test_export_test_dataset.py evaluation/test_export_population_dataset.py evaluation/test_fhir_conformance.py -v`
Expected: the two export tests FAIL (empty `identifier` still present). `TestGeneratedPairs` PASSES already (it prunes itself); it pins that mutator output is conformant once pruned, so a future mutator that emits an invalid shape (not just an empty one) fails here.

- [ ] **Step 3: Implement**

In each of `export_test_dataset.py`, `export_population_dataset.py` and `export_full_onc_dataset.py` add `from fhir_conformance import prune_empty`. Then:
- `write_jsonl`: `"source": prune_empty(record.source), "target": prune_empty(record.target),`
- `write_population_dataset`: `json.dumps({"id": candidate_id, "patient": prune_empty(patient)})` and `"query": prune_empty(case.query_patient),`
- `export_full_onc_dataset.py`: apply `prune_empty(...)` to every `Patient` dict passed into the three `json.dumps` calls at lines 87, 128 and 131. Run `sed -n 80,140p evaluation/export_full_onc_dataset.py` first and wrap exactly the patient-valued expressions (`record.source`, `record.target`, `patient`, `case.query_patient`).

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest evaluation/test_export_test_dataset.py evaluation/test_export_population_dataset.py evaluation/test_export_full_onc_dataset.py evaluation/test_fhir_conformance.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check evaluation/
git add evaluation/export_test_dataset.py evaluation/export_population_dataset.py evaluation/export_full_onc_dataset.py evaluation/test_export_test_dataset.py evaluation/test_export_population_dataset.py evaluation/test_fhir_conformance.py
git commit -m "BAI-1156 prune empty values when serializing patients"
```

---

### Task 6: Retire `marriage_variant` (SUPERSEDED: not carried out; `marriage_variant` was kept)

**Decision for the reviewer (flagged in the design doc):** `marriage_variant` swapped `name[0].family` for the second `name` entry, which was MOTHERS_MAIDEN_NAME. With that column now an extension, the swap never fires, so all ~1,993 `marriage_variant` positives would become address-only changes mislabeled as marriages (session 15 finding F4 criticized exactly this). Surname change is already covered by `surname_change`, and address change by `address_move`. This task removes the scenario. Consumers pinned to `::marriage_variant` case ids lose them; the changelog in Task 15 records the removal.

**Files:**
- Modify: `evaluation/scenarios.py:32,66-72,125`, `evaluation/drift_profile.py:23`, `evaluation/labeled_pairs.py:107,116,133,160,369,399`, `evaluation/mutations.py:327-354` (delete `marriage_variant`)
- Test: `evaluation/test_scenarios.py:75,89,141-150`, `evaluation/test_drift_profile.py:33`, `evaluation/test_labeled_pairs.py` (lines 93, 154, 198, 213, 224, 248, 287, 365, 378), `evaluation/test_mutations.py:23,248-332` (delete `TestMarriageVariant`), `evaluation/test_audit.py:63,86,90,103,106` (string-only, leave)

**Interfaces:**
- Produces: `REGISTRY` no longer contains `marriage_variant`; `generate_raw_pairs` and `_generate_all_raw_pairs` no longer accept `include_marriage_variant`; `DriftProfile` default rates no longer include `marriage_variant`; `DriftProfile.from_json` still accepts a file that names it.

- [ ] **Step 1: Write the failing tests**

Add to `evaluation/test_scenarios.py`:

```python
    def test_marriage_variant_is_retired(self):
        assert "marriage_variant" not in REGISTRY
        assert list(REGISTRY)[:2] == ["ssn_dropped", "phone_variant"]
```

Add to `evaluation/test_drift_profile.py`:

```python
    def test_legacy_marriage_variant_key_in_a_custom_profile_is_ignored(self, tmp_path):
        path = tmp_path / "profile.json"
        path.write_text(json.dumps({"source": "old", "rates": {"marriage_variant": 1.0}}))
        profile = DriftProfile.from_json(path)
        assert profile.rate("phone_churn") == 0.0  # absent rates default to 0
```

Add to `evaluation/test_labeled_pairs.py`:

```python
    def test_no_pair_id_mentions_marriage_variant(self) -> None:
        pairs = list(generate_raw_pairs(drift_population(), donors=drift_donors(), seed=0))
        assert not [p.pair_id for p in pairs if "marriage_variant" in p.pair_id]
```

(`drift_population` and `drift_donors` are already imported in that file; if not, import them from `support_patients`.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest evaluation/test_scenarios.py evaluation/test_drift_profile.py evaluation/test_labeled_pairs.py -v`
Expected: the three new tests FAIL (`marriage_variant` still in `REGISTRY`; pair ids still contain it). Check `DriftProfile.from_json` behavior: the second test may already pass if `from_json` accepts unknown keys; if so, keep it as a regression pin.

- [ ] **Step 3: Implement**

- `scenarios.py`: delete `_marriage_variant` (lines 66-72), the `Scenario("marriage_variant", _marriage_variant),` registry line, and `marriage_variant` from the `from mutations import ...` line (leave `phone_variant, ssn_dropped_variant`). Update the comment above `REGISTRY` from "the three session-14 scenarios" to "the two remaining session-14 scenarios".
- `drift_profile.py`: delete `"marriage_variant": 1.0,` from `LEGACY_RATES`.
- `labeled_pairs.py`: delete the `include_marriage_variant` parameter from `_effective_profile`, `_generate_all_raw_pairs` and `generate_raw_pairs`, delete its tuple in `_effective_profile`'s `off` list, and delete the keyword pass-through in `generate_raw_pairs`' call to `_generate_all_raw_pairs` (lines 107, 116, 133, 160, 369, 399). Update the docstring sentence that lists "SSN-dropped/marriage/phone-number" to "SSN-dropped/phone-number".
- `mutations.py`: delete `marriage_variant` (lines 327-354) and any now-unused import.
- Tests: delete `TestMarriageVariant` and its import in `test_mutations.py`; delete the `include_marriage_variant=False,` kwarg lines in `test_labeled_pairs.py` (93, 213, 287, 365); in `test_labeled_pairs.py:198` remove `"marriage_variant",` from the expected set, at `:248` and `:378` remove `"marriage_variant"` from the set literals, and at `:154` delete the `{"family": "Jones", ...}  # maiden-name proxy` second name entry; in `test_scenarios.py` change line 75 to `assert names[:2] == ["ssn_dropped", "phone_variant"]`, delete the `marriage_variant` suffix assertion at line 89 and the whole `test_marriage_variant_needs_a_next_patient` (141-150); in `test_drift_profile.py` delete line 33 (`assert profile.rate("marriage_variant") == 1.0`).

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest evaluation -v -x -q`
Expected: PASS. Then `grep -rn "marriage" evaluation/*.py`: remaining hits must be only `test_audit.py` string fixtures and `prevalence_estimates.py` prose; if any other hit remains, remove it.

- [ ] **Step 5: Commit**

```bash
uv run ruff check evaluation/ && uv run mypy evaluation
git add -A evaluation/*.py
git commit -m "BAI-1156 retire marriage_variant: its surname swap depended on mother's maiden name as a name entry"
```

---

### Task 7: Realistic manifest: drop stale caveat, add dataset_version

**Files:**
- Modify: `evaluation/export_realistic_dataset.py:65-71` (`CAVEATS`), `:118` (`kind`), `:117-133` (manifest dict)
- Test: `evaluation/test_realistic_dataset.py:107-113`

**Interfaces:**
- Produces: `DATASET_VERSION: str = "2"` in `export_realistic_dataset.py`; manifest key `"dataset_version"`.

- [ ] **Step 1: Write the failing test**

In `evaluation/test_realistic_dataset.py` change `test_manifest_states_its_caveats_and_target_sources` so it no longer expects rule 29 and add a version check (keep the other assertions in that test):

```python
def test_manifest_states_its_caveats_and_target_sources(realistic):
    manifest = realistic.manifest
    caveats = " ".join(manifest["caveats"])
    assert manifest["caveats"]
    assert "rule 29" not in caveats
    assert "reference algorithm" in caveats
    assert manifest["dataset_version"] == "2"
    assert "rule 29" not in manifest["kind"]
```

(Open the test first and keep any assertions below line 113; only the `"rule 29" in caveats` line flips.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest evaluation/test_realistic_dataset.py -v`
Expected: FAIL (`KeyError: 'dataset_version'` or the rule-29 assertion).

- [ ] **Step 3: Implement**

In `export_realistic_dataset.py`: delete the `"not filtered for CMS Table 2 rule 29 (BAI-1061)",` entry; change `"kind"` to `"realistic dataset: RELEASE CANDIDATE"`; add `DATASET_VERSION = "2"` below `CASES_DIR` with the comment `# Bumped when emitted resource content changes (session 16: FHIR-conformant loader).`; add `"dataset_version": DATASET_VERSION,` as the first manifest key after `"kind"`. Also update the module docstring sentence "so these are a release CANDIDATE" if it mentions rule 29 (it does not; leave).

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest evaluation/test_realistic_dataset.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check evaluation/export_realistic_dataset.py evaluation/test_realistic_dataset.py
git add evaluation/export_realistic_dataset.py evaluation/test_realistic_dataset.py
git commit -m "BAI-1156 realistic manifest: drop stale rule-29 caveat, add dataset_version"
```

---

### Task 8: Near-miss finder

**Files:**
- Create: `evaluation/near_miss.py`
- Test: `evaluation/test_near_miss.py`

**Interfaces:**
- Consumes: `identity_guard.is_possible_same_person`, `normalize_phone`, `normalize_token`; `hard_negatives._levenshtein_distance(a, b, max_distance)`.
- Produces:
  - `KINDS: Tuple[str, ...]` = `("dob_zip", "name", "sibling", "address", "phone", "email", "dob_only", "surname_zip")` (priority order).
  - `PAIR_TYPE_BY_KIND: Dict[str, str]`: `dob_zip` -> `hard_negative`, `name` -> `name_collision_negative`, `sibling` -> `sibling_negative`, every other kind -> `near_miss_negative`.
  - `@dataclass(frozen=True) NearMiss(query: Patient, decoy: Patient, kind: str, shared_fields: Mapping[str, str])` with properties `query_id: str` and `pair_type: str`.
  - `@dataclass(frozen=True) NearMissResult(near_misses: List[NearMiss], yield_by_kind: Dict[str, Dict[str, int]])`; each `yield_by_kind[kind]` has keys `queries` (queries with at least one kept decoy), `kept`, `seen`.
  - `find_near_misses(queries: Sequence[Patient], batches: Iterable[Sequence[Patient]], *, exclude_ids: Collection[str] = (), per_kind_cap: int = 3, seed: int = 0) -> NearMissResult`. `batches` is consumed once. Output is ordered by query id, then round-robin across kinds in `KINDS` order (so truncating a pool keeps a mix of kinds).

- [ ] **Step 1: Write the failing tests**

Create `evaluation/test_near_miss.py`:

```python
"""Unit tests for near_miss.py."""

from __future__ import annotations

from identity_guard import SSN_SYSTEM
from near_miss import KINDS, PAIR_TYPE_BY_KIND, find_near_misses


def _p(id_, first, family, dob, zip_="10001", street="1 MAIN ST", phone=None, ssn=None):
    patient = {
        "resourceType": "Patient",
        "id": id_,
        "name": [{"use": "official", "family": family, "given": [first]}],
        "birthDate": dob,
        "address": [
            {"line": [street], "city": "NY", "state": "NY", "postalCode": zip_}
        ],
    }
    if phone:
        patient["telecom"] = [{"system": "phone", "value": phone, "rank": 1}]
    if ssn:
        patient["identifier"] = [{"system": SSN_SYSTEM, "value": ssn}]
    return patient


QUERY = _p("q", "JANE", "SMITH", "1980-01-01")


def _find(records, queries=(QUERY,), **kwargs):
    return find_near_misses(list(queries), [records], **kwargs)


def _kinds(result):
    return {(m.decoy["id"], m.kind) for m in result.near_misses}


class TestKinds:
    def test_same_dob_and_zip_with_a_different_surname_is_a_hard_negative(self):
        result = _find([_p("d", "ROBERT", "JONES", "1980-01-01", street="9 ELM ST")])
        assert _kinds(result) == {("d", "dob_zip")}
        miss = result.near_misses[0]
        assert miss.pair_type == "hard_negative"
        assert dict(miss.shared_fields) == {
            "postalCode": "10001",
            "birthDate": "1980-01-01",
        }

    def test_name_within_one_edit_with_different_dob_and_zip(self):
        result = _find([_p("d", "JANE", "SMYTH", "1990-05-05", zip_="20002")])
        assert _kinds(result) == {("d", "name")}
        assert dict(result.near_misses[0].shared_fields) == {"name_distance": "1"}

    def test_identical_name_with_different_dob_and_zip_has_distance_zero(self):
        result = _find([_p("d", "JANE", "SMITH", "1990-05-05", zip_="20002")])
        assert dict(result.near_misses[0].shared_fields) == {"name_distance": "0"}

    def test_name_two_edits_away_is_not_a_near_miss(self):
        assert (
            _find([_p("d", "JANE", "SMOOTH", "1990-05-05", zip_="20002")]).near_misses
            == []
        )

    def test_same_surname_and_zip_with_close_birth_years_is_a_sibling(self):
        result = _find([_p("d", "JOHN", "SMITH", "1982-05-05")])
        assert _kinds(result) == {("d", "sibling")}
        assert result.near_misses[0].pair_type == "sibling_negative"
        assert dict(result.near_misses[0].shared_fields)["age_gap_years"] == "2"

    def test_same_surname_and_zip_with_a_wide_birth_gap_is_surname_zip(self):
        result = _find([_p("d", "JOHN", "SMITH", "1950-05-05")])
        assert _kinds(result) == {("d", "surname_zip")}
        assert result.near_misses[0].pair_type == "near_miss_negative"

    def test_shared_street_and_zip_with_a_different_surname_is_an_address_miss(self):
        result = _find([_p("d", "ROBERT", "JONES", "1950-05-05")])
        assert _kinds(result) == {("d", "address")}

    def test_shared_phone_with_a_different_surname_is_a_phone_miss(self):
        query = _p("q", "JANE", "SMITH", "1980-01-01", phone="347-984-6839")
        result = _find(
            [
                _p(
                    "d",
                    "ROBERT",
                    "JONES",
                    "1950-05-05",
                    zip_="20002",
                    street="9 ELM ST",
                    phone="(347) 984-6839",
                )
            ],
            queries=(query,),
        )
        assert _kinds(result) == {("d", "phone")}

    def test_shared_dob_only_is_a_dob_only_miss(self):
        result = _find(
            [_p("d", "ROBERT", "JONES", "1980-01-01", zip_="20002", street="9 ELM ST")]
        )
        assert _kinds(result) == {("d", "dob_only")}

    def test_a_record_qualifying_for_several_kinds_is_filed_under_the_first(self):
        result = _find(
            [_p("d", "ROBERT", "JONES", "1980-01-01")]
        )  # dob_zip, address, dob_only
        assert _kinds(result) == {("d", "dob_zip")}

    def test_every_kind_maps_to_a_pair_type(self):
        assert set(PAIR_TYPE_BY_KIND) == set(KINDS)


class TestGuards:
    def test_the_query_itself_and_excluded_ids_are_never_returned(self):
        records = [
            QUERY,
            _p("skip", "ROBERT", "JONES", "1980-01-01"),
            _p("keep", "ALICE", "BROWN", "1980-01-01"),
        ]
        result = _find(records, exclude_ids={"skip"})
        assert {m.decoy["id"] for m in result.near_misses} == {"keep"}

    def test_a_record_sharing_the_queries_ssn_is_never_returned(self):
        query = _p("q", "JANE", "SMITH", "1980-01-01", ssn="892-39-5115")
        twin = _p("t", "ROBERT", "JONES", "1980-01-01", ssn="892-39-5115")
        assert _find([twin], queries=(query,)).near_misses == []

    def test_a_query_with_no_look_alikes_yields_nothing(self):
        lonely = {"resourceType": "Patient", "id": "lonely"}
        result = _find(
            [_p("d", "ROBERT", "JONES", "1950-05-05", zip_="20002")], queries=(lonely,)
        )
        assert result.near_misses == []


class TestCapsAndDeterminism:
    def _flood(self):
        return [
            _p(f"d{i}", "ROBERT", f"JONES{i}", "1980-01-01", zip_=f"2{i:04d}")
            for i in range(10)
        ]

    def test_per_kind_cap_limits_kept_decoys_and_reports_seen(self):
        result = _find(self._flood(), per_kind_cap=3)
        assert len(result.near_misses) == 3
        assert result.yield_by_kind["dob_only"] == {"queries": 1, "kept": 3, "seen": 10}
        assert result.yield_by_kind["dob_zip"] == {"queries": 0, "kept": 0, "seen": 0}

    def test_same_seed_gives_the_same_decoys(self):
        first = _find(self._flood(), seed=7)
        second = _find(self._flood(), seed=7)
        assert [m.decoy["id"] for m in first.near_misses] == [
            m.decoy["id"] for m in second.near_misses
        ]

    def test_batches_are_consumed_once_from_a_generator(self):
        batches = (batch for batch in [self._flood()[:5], self._flood()[5:]])
        result = find_near_misses([QUERY], batches, per_kind_cap=10)
        assert len(result.near_misses) == 10

    def test_output_interleaves_kinds_per_query(self):
        records = [
            _p("a", "ROBERT", "JONES", "1980-01-01", zip_="20002"),
            _p("b", "ALICE", "BROWN", "1980-01-01", zip_="20003"),
            _p("c", "JOHN", "SMITH", "1982-05-05"),
        ]
        kinds = [m.kind for m in _find(records).near_misses]
        assert kinds == ["sibling", "dob_only", "dob_only"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest evaluation/test_near_miss.py -v`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'near_miss'`.

- [ ] **Step 3: Write the implementation**

Create `evaluation/near_miss.py`:

```python
"""Reverse-blocking near-miss finder (session 16, Workstream 2).

Given the sampled query patients, stream every ONC shard once and keep real
records that resemble a query without being the same person: shared DOB+ZIP,
a near-identical name, siblings, a shared address, phone, email, or just a
birth date. This replaces mining pairs inside the 2,000-record sample, where
two colliding records almost never both appear.

Per record the finder looks its keys up in a small index built from the
queries (O(1) each), so there is no pairwise comparison and no 1M-record list.
Edit distance <= 1 on names uses a deletion neighborhood: a query registers its
name and every single-character deletion, a record looks up the same set, and
a hit is verified with a real edit-distance check.

Decoys are real ONC records, never fabricated, and are never the query, never
in `exclude_ids` (the sample and donor ids), and never
`is_possible_same_person` as the query. Per (query, kind) at most
`per_kind_cap` decoys are kept, by seeded reservoir sampling, so a common DOB
or surname cannot flood a query.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Collection, Dict, Iterable, List, Mapping, Sequence, Set, Tuple

from hard_negatives import _levenshtein_distance
from identity_guard import is_possible_same_person, normalize_phone, normalize_token

Patient = Dict[str, Any]

SIBLING_MAX_AGE_GAP_YEARS = 3
DEFAULT_PER_KIND_CAP = 3

# Priority order: a record qualifying under several kinds is filed under the first.
KINDS: Tuple[str, ...] = (
    "dob_zip",
    "name",
    "sibling",
    "address",
    "phone",
    "email",
    "dob_only",
    "surname_zip",
)

PAIR_TYPE_BY_KIND: Dict[str, str] = {
    "dob_zip": "hard_negative",
    "name": "name_collision_negative",
    "sibling": "sibling_negative",
    "address": "near_miss_negative",
    "phone": "near_miss_negative",
    "email": "near_miss_negative",
    "dob_only": "near_miss_negative",
    "surname_zip": "near_miss_negative",
}


@dataclass(frozen=True)
class NearMiss:
    query: Patient
    decoy: Patient
    kind: str
    shared_fields: Mapping[str, str]

    @property
    def query_id(self) -> str:
        return str(self.query["id"])

    @property
    def pair_type(self) -> str:
        return PAIR_TYPE_BY_KIND[self.kind]


@dataclass(frozen=True)
class NearMissResult:
    near_misses: List[NearMiss]
    yield_by_kind: Dict[str, Dict[str, int]]


def _primary(patient: Patient) -> Dict[str, Any]:
    names = patient.get("name") or []
    return names[0] if names else {}


def _raw_family(patient: Patient) -> str:
    return str(_primary(patient).get("family") or "")


def _family(patient: Patient) -> str:
    return normalize_token(_raw_family(patient))


def _first(patient: Patient) -> str:
    given = _primary(patient).get("given") or []
    return normalize_token(given[0]) if given else ""


def _full_name(patient: Patient) -> str:
    first, family = _first(patient), _family(patient)
    return f"{first} {family}" if first and family else ""


def _dob(patient: Patient) -> str:
    return str(patient.get("birthDate") or "")


def _birth_year_gap(a: Patient, b: Patient) -> int | None:
    try:
        return abs(int(_dob(a)[:4]) - int(_dob(b)[:4]))
    except ValueError:
        return None


def _address(patient: Patient) -> Dict[str, Any]:
    addresses = patient.get("address") or []
    return addresses[0] if addresses else {}


def _raw_zip(patient: Patient) -> str:
    return str(_address(patient).get("postalCode") or "")


def _zip(patient: Patient) -> str:
    return normalize_token(_raw_zip(patient))


def _street(patient: Patient) -> str:
    lines = _address(patient).get("line") or []
    return normalize_token(lines[0]) if lines else ""


def _phones(patient: Patient) -> Set[str]:
    found = {
        normalize_phone(t.get("value"))
        for t in patient.get("telecom") or []
        if t.get("system") == "phone"
    }
    return {p for p in found if len(p) == 10}


def _emails(patient: Patient) -> Set[str]:
    return {
        str(t["value"]).strip().casefold()
        for t in patient.get("telecom") or []
        if t.get("system") == "email" and t.get("value")
    }


def _deletions(text: str) -> Set[str]:
    return {text[:i] + text[i + 1 :] for i in range(len(text))}


class _QueryIndex:
    def __init__(self, queries: Sequence[Patient]) -> None:
        self.queries: Dict[str, Patient] = {str(q["id"]): q for q in queries}
        self._dob_zip: Dict[Tuple[str, str], List[str]] = defaultdict(list)
        self._name: Dict[str, List[str]] = defaultdict(list)
        self._surname_zip: Dict[Tuple[str, str], List[str]] = defaultdict(list)
        self._address: Dict[Tuple[str, str], List[str]] = defaultdict(list)
        self._phone: Dict[str, List[str]] = defaultdict(list)
        self._email: Dict[str, List[str]] = defaultdict(list)
        self._dob: Dict[str, List[str]] = defaultdict(list)
        for query_id, query in self.queries.items():
            dob, zip_, family, street = (
                _dob(query),
                _zip(query),
                _family(query),
                _street(query),
            )
            if dob and zip_:
                self._dob_zip[(dob, zip_)].append(query_id)
            name = _full_name(query)
            if name:
                for key in {name} | _deletions(name):
                    self._name[key].append(query_id)
            if family and zip_:
                self._surname_zip[(family, zip_)].append(query_id)
            if street and zip_:
                self._address[(street, zip_)].append(query_id)
            for phone in _phones(query):
                self._phone[phone].append(query_id)
            for email in _emails(query):
                self._email[email].append(query_id)
            if dob:
                self._dob[dob].append(query_id)

    def keys_hit(self, record: Patient) -> Dict[str, Set[str]]:
        """query id -> the key families the record shares with that query."""
        hit: Dict[str, Set[str]] = defaultdict(set)
        dob, zip_, family, street = (
            _dob(record),
            _zip(record),
            _family(record),
            _street(record),
        )
        if dob and zip_:
            for query_id in self._dob_zip.get((dob, zip_), ()):
                hit[query_id].add("dob_zip")
        name = _full_name(record)
        if name:
            for key in {name} | _deletions(name):
                for query_id in self._name.get(key, ()):
                    hit[query_id].add("name")
        if family and zip_:
            for query_id in self._surname_zip.get((family, zip_), ()):
                hit[query_id].add("surname_zip")
        if street and zip_:
            for query_id in self._address.get((street, zip_), ()):
                hit[query_id].add("address")
        for phone in _phones(record):
            for query_id in self._phone.get(phone, ()):
                hit[query_id].add("phone")
        for email in _emails(record):
            for query_id in self._email.get(email, ()):
                hit[query_id].add("email")
        if dob:
            for query_id in self._dob.get(dob, ()):
                hit[query_id].add("dob")
        return hit


def _classify(
    query: Patient, record: Patient, keys: Set[str]
) -> Tuple[str, Dict[str, str]] | None:
    same_family = _family(query) == _family(record)
    same_first = _first(query) == _first(record)
    if "dob_zip" in keys and not same_family:
        return "dob_zip", {"postalCode": _raw_zip(record), "birthDate": _dob(record)}
    if "name" in keys and _dob(query) != _dob(record) and _zip(query) != _zip(record):
        distance = _levenshtein_distance(_full_name(query), _full_name(record), 1)
        if distance <= 1:
            return "name", {"name_distance": str(distance)}
    if "surname_zip" in keys and not same_first:
        gap = _birth_year_gap(query, record)
        if gap is not None and gap <= SIBLING_MAX_AGE_GAP_YEARS:
            return "sibling", {
                "age_gap_years": str(gap),
                "family_name": _raw_family(record),
                "postalCode": _raw_zip(record),
            }
    if "address" in keys and not same_family:
        return "address", {"shared": "address"}
    if "phone" in keys and not same_family:
        return "phone", {"shared": "phone"}
    if "email" in keys and not same_family:
        return "email", {"shared": "email"}
    if "dob" in keys and not same_family and not same_first:
        return "dob_only", {"shared": "birthDate"}
    if "surname_zip" in keys and not same_first:
        return "surname_zip", {"shared": "surname+postalCode"}
    return None


def _interleave(per_kind: Mapping[str, List[NearMiss]]) -> List[NearMiss]:
    ordered = {
        kind: sorted(per_kind.get(kind, []), key=lambda m: str(m.decoy["id"]))
        for kind in KINDS
    }
    longest = max((len(v) for v in ordered.values()), default=0)
    return [
        ordered[kind][position]
        for position in range(longest)
        for kind in KINDS
        if position < len(ordered[kind])
    ]


def find_near_misses(
    queries: Sequence[Patient],
    batches: Iterable[Sequence[Patient]],
    *,
    exclude_ids: Collection[str] = (),
    per_kind_cap: int = DEFAULT_PER_KIND_CAP,
    seed: int = 0,
) -> NearMissResult:
    """Stream `batches` once and return up to `per_kind_cap` real look-alikes
    per (query, kind). See the module docstring."""
    index = _QueryIndex(queries)
    excluded = set(exclude_ids)
    rngs = {qid: random.Random(f"{seed}:near_miss:{qid}") for qid in index.queries}
    kept: Dict[Tuple[str, str], List[NearMiss]] = defaultdict(list)
    seen: Counter[Tuple[str, str]] = Counter()
    for batch in batches:
        for record in batch:
            record_id = str(record.get("id"))
            if record_id in excluded:
                continue
            for query_id, keys in index.keys_hit(record).items():
                query = index.queries[query_id]
                if record_id == query_id or is_possible_same_person(query, record):
                    continue
                found = _classify(query, record, keys)
                if found is None:
                    continue
                kind, shared = found
                slot = (query_id, kind)
                seen[slot] += 1
                miss = NearMiss(
                    query=query, decoy=record, kind=kind, shared_fields=shared
                )
                pool = kept[slot]
                if len(pool) < per_kind_cap:
                    pool.append(miss)
                else:
                    position = rngs[query_id].randrange(seen[slot])
                    if position < per_kind_cap:
                        pool[position] = miss
    near_misses: List[NearMiss] = []
    for query_id in sorted(index.queries):
        near_misses.extend(
            _interleave({kind: kept.get((query_id, kind), []) for kind in KINDS})
        )
    yield_by_kind = {
        kind: {
            "queries": sum(1 for (_, k), pool in kept.items() if k == kind and pool),
            "kept": sum(len(pool) for (_, k), pool in kept.items() if k == kind),
            "seen": sum(count for (_, k), count in seen.items() if k == kind),
        }
        for kind in KINDS
    }
    return NearMissResult(near_misses=near_misses, yield_by_kind=yield_by_kind)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest evaluation/test_near_miss.py -v`
Expected: PASS. If `test_output_interleaves_kinds_per_query` fails on the order of the two `dob_only` decoys, the cause is the sorted-by-decoy-id tie-break: `a` before `b`; that matches the assertion, so a failure there means the classification of record `c` or the zip choices are wrong; fix the data, not the assertion.

- [ ] **Step 5: Lint, types, commit**

```bash
uv run ruff check evaluation/near_miss.py evaluation/test_near_miss.py
uv run ruff format evaluation/near_miss.py evaluation/test_near_miss.py
uv run mypy evaluation/near_miss.py
git add evaluation/near_miss.py evaluation/test_near_miss.py
git commit -m "BAI-1156 add streaming reverse-blocking near-miss finder"
```

---

### Task 9: Audit metrics for negative balance and decoy difficulty

**Files:**
- Modify: `evaluation/audit.py` (new functions near `same_person_negatives`, new keys in `build_report`)
- Test: `evaluation/test_audit.py`

**Interfaces:**
- Consumes: `population_pairs`, `pair_features` (existing), `category_of`.
- Produces: `negative_share(pair_rows) -> float`, `all_yes_f1(pair_rows) -> float` (`2p/(1+p)`, p = positive share; 0.0 on no rows), `missing_hard_negative_categories(pair_rows) -> List[str]` (checked against `REQUIRED_HARD_NEGATIVE_CATEGORIES = ("hard_negative", "name_collision_negative", "sibling_negative", "near_miss_negative")`, negatives only), `decoy_no_overlap_rate(query_rows, candidates) -> float` (share of non-matching pool candidates agreeing with their query on none of ssn, dob, family, given, address, phone, email). `build_report` gains keys `negative_share`, `all_yes_f1`, `missing_hard_negative_categories`, `decoy_no_overlap_rate`.

- [ ] **Step 1: Write the failing tests**

Append to `evaluation/test_audit.py` (reuse its `_row(case_id, source, target, expected, rationale)` and `_patient` helpers; add the new functions to the `from audit import ...` line):

```python
class TestNegativeBalance:
    def _rows(self, positives, negatives):
        rows = [
            _row(f"p{i}", _patient("a"), _patient("b"), True, "fuzzy_variant")
            for i in range(positives)
        ]
        rows += [
            _row(f"n{i}", _patient("a"), _patient("b"), False, "hard_negative")
            for i in range(negatives)
        ]
        return rows

    def test_negative_share_is_the_fraction_of_non_matches(self):
        assert negative_share(self._rows(1, 1)) == 0.5
        assert negative_share([]) == 0.0

    def test_all_yes_f1_is_two_p_over_one_plus_p(self):
        assert all_yes_f1(self._rows(1, 1)) == pytest.approx(2 * 0.5 / 1.5)
        assert all_yes_f1(self._rows(959, 41)) == pytest.approx(0.9791, abs=1e-3)
        assert all_yes_f1([]) == 0.0

    def test_missing_hard_negative_categories_lists_absent_required_ones(self):
        rows = self._rows(1, 1)  # only hard_negative present
        assert missing_hard_negative_categories(rows) == [
            "name_collision_negative",
            "sibling_negative",
            "near_miss_negative",
        ]


class TestDecoyOverlap:
    def _p(self, id_, first, family, dob):
        return {
            "resourceType": "Patient",
            "id": id_,
            "name": [{"family": family, "given": [first]}],
            "birthDate": dob,
        }

    def test_share_of_decoys_with_no_field_in_common(self):
        query = self._p("q", "Jane", "Smith", "1980-01-01")
        candidates = {
            "m": self._p("m", "Jane", "Smith", "1980-01-01"),
            "near": self._p("near", "Robert", "Smith", "1970-02-02"),
            "far": self._p("far", "Robert", "Jones", "1970-02-02"),
        }
        rows = [
            {
                "query_id": "q",
                "query": query,
                "candidate_ids": ["m", "near", "far"],
                "expected_match_ids": ["m"],
                "rationale": "population",
            }
        ]
        assert decoy_no_overlap_rate(rows, candidates) == 0.5
```

(`pytest` import: add `import pytest` to the test module imports if it is not already there.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest evaluation/test_audit.py -v`
Expected: ImportError for the new names.

- [ ] **Step 3: Implement**

In `audit.py`, after `same_person_negatives`:

```python
REQUIRED_HARD_NEGATIVE_CATEGORIES = (
    "hard_negative",
    "name_collision_negative",
    "sibling_negative",
    "near_miss_negative",
)

_OVERLAP_FEATURES = ("ssn", "dob", "family", "given", "address", "phone", "email")


def negative_share(pair_rows: Sequence[Row]) -> float:
    """Fraction of pairwise cases labeled non-match."""
    if not pair_rows:
        return 0.0
    return sum(1 for r in pair_rows if not r["expected_match"]) / len(pair_rows)


def all_yes_f1(pair_rows: Sequence[Row]) -> float:
    """F1 of a matcher that answers "match" to every pairwise case: 2p/(1+p),
    p = positive share. The reviewer's check that "always yes" must not score well."""
    if not pair_rows:
        return 0.0
    positive = 1.0 - negative_share(pair_rows)
    return 2 * positive / (1 + positive)


def missing_hard_negative_categories(pair_rows: Sequence[Row]) -> List[str]:
    """Required hard-negative categories with no non-match row."""
    present = {
        category_of(r["rationale"]) for r in pair_rows if not r["expected_match"]
    }
    return [c for c in REQUIRED_HARD_NEGATIVE_CATEGORIES if c not in present]


def decoy_no_overlap_rate(
    query_rows: Sequence[Row], candidates: Dict[str, Patient]
) -> float:
    """Share of non-matching pool candidates that agree with their query on none
    of ssn, dob, family, given, address, phone or email (the easy-to-reject decoys)."""
    total = 0
    disjoint = 0
    for pair in population_pairs(query_rows, candidates):
        if pair.is_true_match:
            continue
        total += 1
        if not any(pair.features[name] for name in _OVERLAP_FEATURES):
            disjoint += 1
    return disjoint / total if total else 0.0
```

(`population_pairs` is defined later in the module; Python resolves it at call time, so the order is fine.) Add to the dict returned by `build_report`, after `"tier_parity_gap"`:

```python
        "negative_share": negative_share(pair_rows),
        "all_yes_f1": all_yes_f1(pair_rows),
        "missing_hard_negative_categories": missing_hard_negative_categories(pair_rows),
        "decoy_no_overlap_rate": decoy_no_overlap_rate(query_rows, candidates),
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest evaluation/test_audit.py evaluation/test_release_gate.py -v`
Expected: PASS. (`release_thresholds.json` does not name the new metrics, so the committed gate is unchanged.)

- [ ] **Step 5: Commit**

```bash
uv run ruff check evaluation/audit.py evaluation/test_audit.py && uv run ruff format evaluation/audit.py evaluation/test_audit.py
git add evaluation/audit.py evaluation/test_audit.py
git commit -m "BAI-1156 audit: negative share, always-match F1, required hard-negative categories, decoy overlap"
```

---

### Task 10: Near-miss negatives in the pairwise tier, and negative rebalancing

**Files:**
- Modify: `evaluation/labeled_pairs.py` (`_generate_all_raw_pairs`, `generate_raw_pairs`), `evaluation/export_test_dataset.py` (`build_test_case_records`)
- Create: `evaluation/negative_balance.py`
- Test: `evaluation/test_labeled_pairs.py`, `evaluation/test_negative_balance.py`

**Interfaces:**
- Consumes: `NearMiss` (Task 8); `audit.category_of`; `LabeledCaseRecord` (fields `case_id, source, target, expected_match, rationale, frequency=1.0`).
- Produces: `generate_raw_pairs(..., near_misses: Sequence[NearMiss] = ())` emitting one negative `RawPair` per near miss with `pair_id = f"{query_id}::{decoy_id}::near_miss::{kind}"` and `strata = {"pair_type": miss.pair_type, "found_by": "near_miss", **miss.shared_fields}`; `build_test_case_records(..., near_misses=...)` passes them through; `rebalance_negatives(records: List[LabeledCaseRecord], *, target_share: float, seed: int, min_per_category: int = 25) -> List[LabeledCaseRecord]`.

- [ ] **Step 1: Write the failing tests**

Add to `evaluation/test_labeled_pairs.py` (import `from near_miss import NearMiss`; `_patient(id, family=..., given=...)` already exists in that file):

```python
    def test_near_misses_are_emitted_as_negative_pairs_in_their_own_category(self) -> None:
        query = _patient("p1")
        decoy = _patient("d1", family="Jones", given="Robert")
        miss = NearMiss(
            query=query, decoy=decoy, kind="dob_only", shared_fields={"shared": "birthDate"}
        )
        pairs = [
            p
            for p in generate_raw_pairs([query], near_misses=[miss], seed=0)
            if "::near_miss::" in p.pair_id
        ]
        assert len(pairs) == 1
        assert pairs[0].pair_id == "p1::d1::near_miss::dob_only"
        assert pairs[0].is_true_match is False
        assert pairs[0].candidate_patient is decoy
        assert dict(pairs[0].strata) == {
            "pair_type": "near_miss_negative",
            "found_by": "near_miss",
            "shared": "birthDate",
        }
```

Create `evaluation/test_negative_balance.py`:

```python
"""Unit tests for negative_balance.py."""

from __future__ import annotations

from collections import Counter

import pytest
from audit import category_of
from export_test_dataset import LabeledCaseRecord
from negative_balance import rebalance_negatives


def _rec(case_id: str, expected: bool, rationale: str) -> LabeledCaseRecord:
    return LabeledCaseRecord(
        case_id=case_id,
        source={},
        target={},
        expected_match=expected,
        rationale=rationale,
    )


def _records(positives: dict, negatives: int):
    records = [
        _rec(f"{cat}{i}", True, f"{cat}/x")
        for cat, n in positives.items()
        for i in range(n)
    ]
    records += [_rec(f"neg{i}", False, "hard_negative") for i in range(negatives)]
    return records


def _share(records):
    return sum(1 for r in records if not r.expected_match) / len(records)


def test_subsamples_positives_to_reach_the_target_share():
    out = rebalance_negatives(
        _records({"a": 100, "b": 100}, 100), target_share=0.5, seed=0
    )
    assert _share(out) == pytest.approx(0.5)
    kept = Counter(category_of(r.rationale) for r in out if r.expected_match)
    assert kept["a"] == kept["b"] == 50


def test_never_drops_a_negative():
    records = _records({"a": 300}, 100)
    out = rebalance_negatives(records, target_share=0.5, seed=0)
    assert {r.case_id for r in out if not r.expected_match} == {
        r.case_id for r in records if not r.expected_match
    }


def test_small_categories_keep_their_floor():
    out = rebalance_negatives(
        _records({"rare": 10, "big": 500}, 100), target_share=0.5, seed=0
    )
    kept = Counter(category_of(r.rationale) for r in out if r.expected_match)
    assert kept["rare"] == 10
    assert kept["big"] == 90


def test_no_op_when_already_balanced_enough():
    records = _records({"a": 50}, 100)
    assert rebalance_negatives(records, target_share=0.5, seed=0) == records


def test_reports_a_shortfall_by_leaving_the_share_below_target_rather_than_failing():
    # 10 negatives cannot support 500 positives at 50% once floors apply.
    out = rebalance_negatives(
        _records({"a": 500, "b": 500}, 10), target_share=0.5, seed=0
    )
    assert _share(out) < 0.5
    assert sum(1 for r in out if r.expected_match) == 50  # two floors of 25


def test_is_deterministic_and_keeps_original_order():
    records = _records({"a": 200}, 50)
    first = rebalance_negatives(records, target_share=0.5, seed=3)
    second = rebalance_negatives(records, target_share=0.5, seed=3)
    assert [r.case_id for r in first] == [r.case_id for r in second]
    order = {r.case_id: i for i, r in enumerate(records)}
    assert [order[r.case_id] for r in first] == sorted(order[r.case_id] for r in first)


@pytest.mark.parametrize("bad", [0.0, 1.0, -0.1, 1.5])
def test_rejects_a_target_outside_the_open_unit_interval(bad):
    with pytest.raises(ValueError, match="target_share"):
        rebalance_negatives([], target_share=bad, seed=0)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest evaluation/test_labeled_pairs.py evaluation/test_negative_balance.py -v`
Expected: `test_negative_balance.py` collection ERROR (no module); the labeled_pairs test FAILS with `TypeError: ... unexpected keyword argument 'near_misses'`.

- [ ] **Step 3: Implement**

`labeled_pairs.py`: add `from near_miss import NearMiss` to the imports; add `near_misses: Sequence[NearMiss] = (),` to the parameter lists of `_generate_all_raw_pairs` and `generate_raw_pairs` (before `exclusions` / `seed`), pass `near_misses=near_misses,` through in `generate_raw_pairs`' call to `_generate_all_raw_pairs`; and in `_generate_all_raw_pairs`, directly before the line `if not include_special_populations:`, add:

```python
    for miss in near_misses:
        yield RawPair(
            pair_id=f"{miss.query_id}::{miss.decoy['id']}::near_miss::{miss.kind}",
            query_patient=miss.query,
            candidate_patient=miss.decoy,
            is_true_match=False,
            strata={
                "pair_type": miss.pair_type,
                "found_by": "near_miss",
                **miss.shared_fields,
            },
        )
```

`export_test_dataset.py`: add `from near_miss import NearMiss` to imports, add `near_misses: Sequence[NearMiss] = (),` to `build_test_case_records` (before `exclusions`) and `near_misses=near_misses,` to its `generate_raw_pairs(...)` call.

Create `evaluation/negative_balance.py`:

```python
"""Rebalance the pairwise tier toward a target negative share (session 16).

An "always match" answer scores F1 = 2p/(1+p) on a tier that is p positive, so
a 96%-positive tier cannot separate algorithms. Positives are cheap to
regenerate and negatives are scarce, so this drops *positives* (never
negatives), proportionally by category, keeping at least `min_per_category`
of each category (or all of a smaller one). If negatives are too few to reach
the target once those floors apply, the share is left below target: the
audit's `negative_share` gate reports it rather than this function raising.
"""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Dict, List

from audit import category_of
from export_test_dataset import LabeledCaseRecord


def rebalance_negatives(
    records: List[LabeledCaseRecord],
    *,
    target_share: float,
    seed: int,
    min_per_category: int = 25,
) -> List[LabeledCaseRecord]:
    if not 0.0 < target_share < 1.0:
        raise ValueError(f"target_share must be in (0, 1), got {target_share}")
    n_negatives = sum(1 for r in records if not r.expected_match)
    positives = [i for i, r in enumerate(records) if r.expected_match]
    budget = int(n_negatives * (1 - target_share) / target_share)
    if len(positives) <= budget:
        return list(records)
    by_category: Dict[str, List[int]] = defaultdict(list)
    for index in positives:
        by_category[category_of(records[index].rationale)].append(index)
    floors = {c: min(len(g), min_per_category) for c, g in by_category.items()}
    keep = {
        c: min(len(g), max(floors[c], round(len(g) * budget / len(positives))))
        for c, g in by_category.items()
    }
    excess = sum(keep.values()) - budget
    while excess > 0:
        reducible = [c for c in keep if keep[c] > floors[c]]
        if not reducible:
            break
        biggest = max(reducible, key=lambda c: (keep[c], c))
        keep[biggest] -= 1
        excess -= 1
    dropped = set()
    for category, group in by_category.items():
        rng = random.Random(f"{seed}:rebalance:{category}")
        kept = set(rng.sample(group, keep[category]))
        dropped.update(i for i in group if i not in kept)
    return [r for i, r in enumerate(records) if i not in dropped]
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest evaluation/test_labeled_pairs.py evaluation/test_negative_balance.py evaluation/test_export_test_dataset.py -v`
Expected: PASS. Note `test_small_categories_keep_their_floor`: budget 100, proportional `rare` 2 and `big` 98, floors 10 and 25, so keep = 10 and 98, excess 8, `big` reduced to 90.

- [ ] **Step 5: Lint, types, commit**

```bash
uv run ruff check evaluation/ && uv run ruff format evaluation/negative_balance.py evaluation/test_negative_balance.py evaluation/labeled_pairs.py evaluation/export_test_dataset.py && uv run mypy evaluation
git add evaluation/negative_balance.py evaluation/test_negative_balance.py evaluation/labeled_pairs.py evaluation/export_test_dataset.py evaluation/test_labeled_pairs.py
git commit -m "BAI-1156 pairwise tier: near-miss negatives and negative rebalancing"
```

---

### Task 11: Near-miss decoys in the population tier

**Files:**
- Modify: `evaluation/population_cases.py` (`build_population_dataset`)
- Test: `evaluation/test_population_cases.py`

**Interfaces:**
- Consumes: `NearMiss` (Task 8).
- Produces: `build_population_dataset(..., near_misses: Sequence[NearMiss] = ())`. Each near miss becomes a non-match candidate of its query under candidate id `str(decoy["id"])`, credited to category `miss.pair_type`. Near-misses are added after every existing decoy category, so existing categories keep their pool slots when a pool is trimmed to `pool_size`.

- [ ] **Step 1: Write the failing test**

Add to `evaluation/test_population_cases.py` (add `from near_miss import NearMiss`):

```python
def _near_patient(id_: str, family: str, given: str, dob: str = "1980-06-15"):
    return {
        "resourceType": "Patient",
        "id": id_,
        "name": [{"family": family, "given": [given]}],
        "birthDate": dob,
        "address": [
            {"line": ["1 Main St"], "city": "NY", "state": "NY", "postalCode": "10001"}
        ],
    }


def test_near_misses_join_the_query_pool_as_non_matches():
    patients = [
        _near_patient("p1", "Smith", "Katherine"),
        _near_patient("p2", "Jones", "Robert", "1970-01-01"),
    ]
    decoy = _near_patient("d1", "Brown", "Alice")
    miss = NearMiss(
        query=patients[0],
        decoy=decoy,
        kind="dob_zip",
        shared_fields={"postalCode": "10001", "birthDate": "1980-06-15"},
    )
    dataset = build_population_dataset(patients, near_misses=[miss], seed=0)
    case = next(c for c in dataset.cases if c.query_id == "p1")
    assert "d1" in case.candidate_ids
    assert "d1" not in case.expected_match_ids
    assert dataset.candidates["d1"] is decoy
    assert "hard_negative" in case.rationale


def test_near_misses_never_displace_true_matches_when_the_pool_is_trimmed():
    patients = [_near_patient("p1", "Smith", "Katherine")]
    misses = [
        NearMiss(
            query=patients[0],
            decoy=_near_patient(f"d{i}", f"Brown{i}", "Alice"),
            kind="dob_only",
            shared_fields={"shared": "birthDate"},
        )
        for i in range(60)
    ]
    dataset = build_population_dataset(
        patients, near_misses=misses, pool_size=40, seed=0
    )
    case = dataset.cases[0]
    assert len(case.candidate_ids) == 40
    assert set(case.expected_match_ids) <= set(case.candidate_ids)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest evaluation/test_population_cases.py -v`
Expected: FAIL with `TypeError: build_population_dataset() got an unexpected keyword argument 'near_misses'`.

- [ ] **Step 3: Implement**

In `population_cases.py` add `from near_miss import NearMiss` to the imports and `near_misses: Sequence[NearMiss] = (),` to `build_population_dataset`'s parameters (before `exclusions`). Immediately before the line `all_ids = list(by_id)`, add:

```python
    # Real look-alike decoys found by near_miss.py. Added last so every existing
    # decoy category keeps its slot when a pool is trimmed to `pool_size`; the
    # decoy is not in `patients`, so its plain id cannot collide with a sample id.
    for miss in near_misses:
        if miss.query_id in by_id:
            add_candidate(
                miss.query_id, str(miss.decoy["id"]), miss.decoy, False, miss.pair_type
            )
```

Update the module docstring's "decoy pool" paragraph with one sentence: "Near-miss decoys (near_miss.py) are real records found across all ONC shards that share a name, DOB, address or contact with the query."

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest evaluation/test_population_cases.py evaluation/test_export_population_dataset.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check evaluation/population_cases.py evaluation/test_population_cases.py && uv run ruff format evaluation/population_cases.py evaluation/test_population_cases.py && uv run mypy evaluation
git add evaluation/population_cases.py evaluation/test_population_cases.py
git commit -m "BAI-1156 population tier: add near-miss decoys to query pools"
```

---

### Task 12: Realistic export: second streaming pass, rebalance, manifest

**Files:**
- Modify: `evaluation/export_realistic_dataset.py` (`CAVEATS`, `generate_realistic`, `__main__`, manifest)
- Test: `evaluation/test_realistic_dataset.py`

**Interfaces:**
- Consumes: `find_near_misses`, `rebalance_negatives`, `iter_shard_batches`.
- Produces: `generate_realistic(..., decoy_batches: Callable[[], Iterable[Sequence[Patient]]] | None = None, target_negative_share: float | None = None, per_kind_cap: int = DEFAULT_PER_KIND_CAP)`. With `decoy_batches=None` the output is unchanged (existing tests keep working). Manifest gains `near_miss` (`per_kind_cap`, `yield_by_kind`), `negative_share`, `n_positives_dropped`. The stale caveat "mined sibling, name-collision and hard-negative categories are scarce" is removed from `CAVEATS`. `__main__` passes `decoy_batches=iter_shard_batches`, `target_negative_share=0.5`, and `per_kind_cap` from env `NEAR_MISS_CAP` (default 3).

- [ ] **Step 1: Write the failing tests**

In `evaluation/test_realistic_dataset.py` change the `realistic` fixture to enable the new behavior (imports: `from audit import negative_share`):

```python
@pytest.fixture(scope="module")
def realistic(tmp_path_factory):
    dataset = generate_realistic(
        iter_shard_batches(limit=1),
        sample_size=SAMPLE,
        donor_size=SAMPLE,
        seed=0,
        profile=DriftProfile(),
        decoy_batches=lambda: iter_shard_batches(limit=1),
        target_negative_share=0.5,
    )
    out = tmp_path_factory.mktemp("realistic")
    write_realistic_dataset(dataset, out)
    return dataset, out
```

Add tests:

```python
def test_pairwise_tier_is_about_half_negative(realistic):
    _, out = realistic
    rows = read_jsonl(out / "realistic_labeled_pairs.jsonl")
    assert negative_share(rows) >= 0.45


def test_near_miss_negatives_appear_in_both_tiers(realistic):
    _, out = realistic
    pairs = read_jsonl(out / "realistic_labeled_pairs.jsonl")
    near = [r for r in pairs if "found_by=near_miss" in r["rationale"]]
    assert near and all(r["expected_match"] is False for r in near)
    queries = read_jsonl(out / "realistic_population_queries.jsonl")
    assert any(
        "near_miss_negative" in q["rationale"] or "hard_negative" in q["rationale"]
        for q in queries
    )


def test_manifest_reports_near_miss_yield_and_negative_share(realistic):
    dataset, _ = realistic
    manifest = dataset.manifest
    assert set(manifest["near_miss"]["yield_by_kind"]) >= {
        "dob_zip",
        "name",
        "dob_only",
    }
    assert manifest["near_miss"]["per_kind_cap"] == 3
    assert manifest["negative_share"] >= 0.45
    assert manifest["n_positives_dropped"] >= 0
```

Replace the `test_the_realistic_thresholds_pass_on_the_generated_files` body's threshold loading so scale-dependent metrics are skipped at 300 patients on one shard (full-scale values are gated by the committed-file test in Task 14):

```python
SCALE_DEPENDENT = {"missing_hard_negative_categories"}
...
    thresholds = {
        name: rule
        for name, rule in load_thresholds(REALISTIC_THRESHOLDS_PATH).items()
        if name not in SCALE_DEPENDENT
    }
    results = check(report, thresholds)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest evaluation/test_realistic_dataset.py -v`
Expected: collection or fixture ERROR, `TypeError: generate_realistic() got an unexpected keyword argument 'decoy_batches'`.

- [ ] **Step 3: Implement**

In `export_realistic_dataset.py`: add imports `from near_miss import DEFAULT_PER_KIND_CAP, find_near_misses`, `from negative_balance import rebalance_negatives`, `from typing import Callable` (extend the existing typing import). Delete the caveat line `"mined sibling, name-collision and hard-negative categories are scarce",`. Extend the signature and body of `generate_realistic`:

```python
def generate_realistic(
    batches: Iterable[Sequence[Patient]],
    *,
    sample_size: int,
    donor_size: int,
    seed: int,
    profile: DriftProfile,
    decoy_batches: Callable[[], Iterable[Sequence[Patient]]] | None = None,
    target_negative_share: float | None = None,
    per_kind_cap: int = DEFAULT_PER_KIND_CAP,
) -> RealisticDataset:
    sample = stratified_sample(batches, sample_size, donor_n=donor_size, seed=seed)
    housed = assign_households(sample.patients, profile=profile, seed=seed)
    near_result = None
    if decoy_batches is not None:
        near_result = find_near_misses(
            housed.patients,
            decoy_batches(),
            exclude_ids={p["id"] for p in sample.patients}
            | {d["id"] for d in sample.donors},
            per_kind_cap=per_kind_cap,
            seed=seed,
        )
    near_misses = near_result.near_misses if near_result else []
    records = build_test_case_records(
        housed.patients,
        donors=sample.donors,
        profile=profile,
        households=housed.households,
        near_misses=near_misses,
        seed=seed,
        frequency_lookup=researched_frequency,
    )
    n_before = len(records)
    if target_negative_share is not None:
        records = rebalance_negatives(
            records, target_share=target_negative_share, seed=seed
        )
    population = build_population_dataset(
        housed.patients,
        donors=sample.donors,
        profile=profile,
        households=housed.households,
        near_misses=near_misses,
        seed=seed,
    )
    n_negatives = sum(1 for r in records if not r.expected_match)
```

and add to the manifest dict (after `"profile_rates"`):

```python
        "near_miss": {
            "per_kind_cap": per_kind_cap,
            "yield_by_kind": near_result.yield_by_kind if near_result else {},
        },
        "negative_share": n_negatives / len(records) if records else 0.0,
        "n_positives_dropped": n_before - len(records),
```

(Keep `"n_labeled_cases": len(records)`, which is already computed after this point.) In `__main__`, replace the `generate_realistic(...)` call arguments by adding:

```python
decoy_batches = (iter_shard_batches,)
target_negative_share = (0.5,)
per_kind_cap = (int(os.environ.get("NEAR_MISS_CAP", DEFAULT_PER_KIND_CAP)),)
```

and add `NEAR_MISS_CAP (3)` to the docstring's Environment line.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest evaluation/test_realistic_dataset.py -v`
Expected: PASS except possibly `test_the_realistic_thresholds_pass_on_the_generated_files`, which depends on Task 13's thresholds (before Task 13 it still runs the old thresholds and should pass). If `test_pairwise_tier_is_about_half_negative` fails because negatives are too few at 300 patients on one shard, print `dataset.manifest["near_miss"]` and `negative_share`, and raise `SAMPLE` in the fixture to 600 rather than weakening the 0.45 floor.

- [ ] **Step 5: Commit**

```bash
uv run ruff check evaluation/ && uv run ruff format evaluation/export_realistic_dataset.py evaluation/test_realistic_dataset.py && uv run mypy evaluation
git add evaluation/export_realistic_dataset.py evaluation/test_realistic_dataset.py
git commit -m "BAI-1156 realistic export: near-miss pass, negative rebalance, manifest yield report"
```

---

### Task 13: Realistic gate thresholds

**Files:**
- Modify: `evaluation/release_thresholds_realistic.json`
- Test: `evaluation/test_release_gate.py`

**Interfaces:**
- Consumes: the metrics from Task 9.
- Produces: enforced `negative_share` (min 0.45), enforced `all_yes_f1` (max 0.70), enforced `missing_hard_negative_categories` (max 0, list-valued so the gate uses its length), tracked `decoy_no_overlap_rate` (max 0.5).

- [ ] **Step 1: Write the failing test**

Add to `evaluation/test_release_gate.py`:

```python
def test_realistic_thresholds_name_the_negative_balance_metrics():
    rules = load_thresholds(REALISTIC_THRESHOLDS_PATH)
    assert rules["negative_share"] == {"min": 0.45, "status": "enforced"}
    assert rules["all_yes_f1"] == {"max": 0.70, "status": "enforced"}
    assert rules["missing_hard_negative_categories"] == {"max": 0, "status": "enforced"}
    assert rules["decoy_no_overlap_rate"] == {"max": 0.5, "status": "tracked"}
```

(Add `REALISTIC_THRESHOLDS_PATH` and `load_thresholds` to that file's imports from `release_gate` if absent.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest evaluation/test_release_gate.py -v`
Expected: FAIL with `KeyError: 'negative_share'`.

- [ ] **Step 3: Implement**

Add these four entries to `evaluation/release_thresholds_realistic.json` (keep the existing seven):

```json
  "negative_share": {"min": 0.45, "status": "enforced"},
  "all_yes_f1": {"max": 0.70, "status": "enforced"},
  "missing_hard_negative_categories": {"max": 0, "status": "enforced"},
  "decoy_no_overlap_rate": {"max": 0.5, "status": "tracked"}
```

(`negative_share` at 0.45 and `all_yes_f1` at 0.70 are nearly the same bound; the rebalancer targets 0.50, where `all_yes_f1` is 0.667.)

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest evaluation/test_release_gate.py evaluation/test_realistic_dataset.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add evaluation/release_thresholds_realistic.json evaluation/test_release_gate.py
git commit -m "BAI-1156 realistic gate: enforce negative share, always-match F1, hard-negative categories"
```

---

### Task 14: Commit the realistic set and gate it in CI

**Files:**
- Create: `evaluation/test_committed_realistic.py`
- Modify: `.gitignore`, `.github/workflows/build_and_test.yml`, `evaluation/release_thresholds_realistic.json` (only if the measured `best_single_field_f1` allows), `evaluation/cases/realistic_*` (generated)

**Interfaces:**
- Consumes: `release_gate.run`, `failures`; `export_realistic_dataset.DATASET_VERSION`; `audit.CASES_DIR`.
- Produces: committed `evaluation/cases/realistic_labeled_pairs.jsonl`, `realistic_population_candidates.jsonl`, `realistic_population_queries.jsonl`, `realistic_manifest.json`; CI runs `make audit-realistic`.

- [ ] **Step 1: Write the failing test**

Create `evaluation/test_committed_realistic.py`:

```python
"""The committed realistic release files pass their gate and match the code."""

from __future__ import annotations

import json

from audit import CASES_DIR
from drift_profile import DriftProfile
from export_inputs import DEFAULT_DONOR_SIZE
from export_realistic_dataset import DATASET_VERSION
from labeled_pairs import DEFAULT_SAMPLE_SIZE
from release_gate import failures, run


def test_committed_realistic_files_pass_the_realistic_gate():
    results = run("realistic")
    assert failures(results) == [], [(r.name, r.value) for r in failures(results)]


def test_committed_realistic_manifest_matches_the_code():
    manifest = json.loads((CASES_DIR / "realistic_manifest.json").read_text())
    assert manifest["dataset_version"] == DATASET_VERSION
    assert manifest["seed"] == 0
    assert manifest["sample_size"] == DEFAULT_SAMPLE_SIZE
    assert manifest["donor_size"] == DEFAULT_DONOR_SIZE
    assert manifest["profile_source"] == DriftProfile().source
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest evaluation/test_committed_realistic.py -v`
Expected: FAIL with `FileNotFoundError: 'realistic' dataset files not found`.

- [ ] **Step 3: Generate, measure, and set thresholds from the measured values**

```bash
make generate-realistic-dataset | tail -60
make audit-realistic
ls -l evaluation/cases/realistic_*
```
Expected: generation finishes (several minutes: the shards are read twice); every enforced line in `audit-realistic` prints `ok`. Check these against the plan before continuing:
- `negative_share` >= 0.45 and `all_yes_f1` <= 0.70. If `negative_share` is below target, read `manifest["near_miss"]["yield_by_kind"]` and `n_positives_dropped`; raise `NEAR_MISS_CAP` (for example `NEAR_MISS_CAP=6 make generate-realistic-dataset`) and re-run. Do not lower the thresholds.
- `missing_hard_negative_categories` is empty.
- `best_single_field_f1`: if it is now <= 0.90, change its status to `"enforced"` in `release_thresholds_realistic.json`; if not, leave it `"tracked"` and record the value in the README (Task 15).
- Each realistic file is under 50 MB (`ls -l`). If one is not, lower `NEAR_MISS_CAP` or stop and report: the release route (commit vs. release artifact) must then be revisited with the maintainer.

- [ ] **Step 4: Release route**

Delete these lines from `.gitignore`:

```
# Generated by export_realistic_dataset.py (a release candidate: commit deliberately with `git add -f`)
evaluation/cases/realistic_*.jsonl
evaluation/cases/realistic_manifest.json
```

In `.github/workflows/build_and_test.yml`, add after `- run: make audit` in the `test` job:

```yaml
      - run: make audit-realistic
```

Run: `uv run pytest evaluation/test_committed_realistic.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add .gitignore .github/workflows/build_and_test.yml evaluation/test_committed_realistic.py evaluation/release_thresholds_realistic.json evaluation/cases/realistic_labeled_pairs.jsonl evaluation/cases/realistic_population_candidates.jsonl evaluation/cases/realistic_population_queries.jsonl evaluation/cases/realistic_manifest.json
git commit -m "BAI-1156 commit the realistic dataset and gate it in CI"
```

---

### Task 15: Regenerate the committed set, document, verify

**Files:**
- Modify: `evaluation/cases/sample_labeled_pairs.jsonl`, `population_candidates.jsonl`, `population_queries.jsonl`, `evaluation/cases/README.md`, `CLAUDE.md`, `docs/sessions/completed/session_16.md`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Regenerate the committed (curated) files**

```bash
PYTHONPATH=. uv run python evaluation/export_test_dataset.py
PYTHONPATH=. uv run python evaluation/export_population_dataset.py
```
Expected: both rewrite the three committed files without error (this also discards any stray local edit to `sample_labeled_pairs.jsonl`).

- [ ] **Step 2: Verify conformance of every committed file and the gates**

```bash
PYTHONPATH=evaluation uv run python - <<'E'
import json
from pathlib import Path
from fhir_conformance import violations
cases = Path("evaluation/cases")
bad = 0
for name, keys in (
    ("sample_labeled_pairs.jsonl", ("source", "target")),
    ("population_candidates.jsonl", ("patient",)),
    ("population_queries.jsonl", ("query",)),
    ("realistic_labeled_pairs.jsonl", ("source", "target")),
    ("realistic_population_candidates.jsonl", ("patient",)),
    ("realistic_population_queries.jsonl", ("query",)),
):
    for line in (cases / name).read_text().splitlines():
        row = json.loads(line)
        for key in keys:
            bad += bool(violations(row[key]))
print("non-conformant patients:", bad)
E
make audit
make audit-realistic
grep -c "marriage_variant" evaluation/cases/sample_labeled_pairs.jsonl evaluation/cases/realistic_labeled_pairs.jsonl
```
Expected: `non-conformant patients: 0`; `make audit` shows `same_person_negatives = 0` and `tier_parity_gap = 0` (the committed set's realism floors fail by design and are reported, not enforced here); `make audit-realistic` all `ok`; both `grep -c` print `0`.

- [ ] **Step 3: Update docs**

`evaluation/cases/README.md`:
- Replace the realistic section's "git-ignored, commit deliberately with `git add -f`" with "committed as the v1 release (`make audit-realistic` runs in CI)". Replace the "The mined negative categories collapse" bullet with the measured per-category row counts from the new realistic file (run `python3 -c` over `realistic_labeled_pairs.jsonl` counting `rationale` heads) and one sentence: hard negatives now come from `near_miss.py` (reverse blocking over all shards). Replace the "Mining them per shard ... is a follow-up" sentence. Remove the "marriage_variant" bullet (about lines 95-97) and fix lines mentioning it (~155, ~167, ~342, ~604).
- Add a "Changelog" entry:

```
### Dataset version 2 (BAI-1156)
- Patient resources are FHIR-conformant: no empty strings/arrays, caret-joined phones split into one `telecom` entry each with `rank`, SSN identifiers carry type `SS`, ONC ALIAS is a separate `use: nickname` name (not in `given`), MOTHERS_MAIDEN_NAME is the `patient-mothersMaidenName` extension (not a second name).
- Removed: the `marriage_variant` case ids (its surname swap relied on mother's maiden name as a name entry). Surname changes are covered by `surname_change`, address changes by `address_move`.
- Realistic set committed (`realistic_*`): real look-alike decoys from all shards in both tiers (`hard_negative`, `name_collision_negative`, `sibling_negative`, `near_miss_negative`; strata `found_by=near_miss`), pairwise tier rebalanced to ~50% negatives by subsampling positives (`manifest.n_positives_dropped`), enforced gates for `negative_share`, `all_yes_f1` and required hard-negative categories.
- Open caveats at release (also in `realistic_manifest.json`): drift positives not verified against the CMS reference algorithm; drift and household sharing rates are placeholders; households are mostly unrelated records at one address.
```

`CLAUDE.md`: in the Architecture list add a bullet "**`near_miss.py`** — streaming reverse-blocking finder: real look-alike decoys for sampled queries across all shards; feeds both tiers (`hard_negative`, `name_collision_negative`, `sibling_negative`, `near_miss_negative`). **`negative_balance.py`** rebalances the pairwise tier toward 50% negatives." and replace the sentence that says realistic files are git-ignored (in the `export_realistic_dataset.py` bullet: "the committed files are never overwritten" stays; add "the realistic files are committed as the v1 release").

`docs/sessions/completed/session_16.md`: under Rollout add "**Decision (2026-10-14):** shipped as one PR (former PRs 1, 2, 4 and the decoy part of PR 3), one commit per workstream. Still deferred: queries with 0 or 1 expected matches, `strata.decoy_kinds`, family structure (PR 5), age vintage." and under "Release caveats" mark caveats 1 and 5 closed.

- [ ] **Step 4: Full verification**

```bash
make tests && make lint && make typecheck && make audit && make audit-realistic
git status --short
```
Expected: all green; `git status` shows only the files edited in this task.

- [ ] **Step 5: Commit**

```bash
git add evaluation/cases CLAUDE.md docs/sessions/completed/session_16.md
git commit -m "BAI-1156 regenerate committed datasets with conformant resources; document dataset version 2"
```

---

## Self-Review

- **Spec coverage (reviewer blockers and caveats):**
  - R1 release route: Task 14 (un-ignore, commit, CI gate, manifest-sync test).
  - R2 lost hard negatives: Tasks 8, 10, 11, 12 (finder emits `hard_negative`, `name_collision_negative`, `sibling_negative` in both tiers), gated by `missing_hard_negative_categories` (Tasks 9, 13).
  - R3 always-yes F1: Tasks 10, 12 (rebalance to 50%), gated by `negative_share` and `all_yes_f1` (Tasks 9, 13). The design doc's separate `always_match` baseline is replaced by the `all_yes_f1` audit metric, because the baselines score the population tier and the reviewer's check is on the pairwise tier.
  - R4 loader conformance: Tasks 1-5, enforced by the validator and corpus tests.
  - Caveats: 1 (stale rule 29) Task 7; 5 (scarce hard negatives) Task 12; 2, 3, 4 stay disclosed (Task 15 changelog and manifest).
  - Partly covered enhancement: harder decoys (Task 11 puts real look-alikes in pools; `decoy_no_overlap_rate` is tracked, not enforced).
  - Not covered by design: E1 family structure, E2 age vintage, E3 queries with 0/1 matches.
- **Placeholder scan:** the three steps that said "open the file first" (Tasks 4, 5 and 7) were resolved during implementation; the shipped code and tests in the PR are the source of truth, not those step bodies. Task 14 Step 3 and Task 12 Step 4 give explicit decision rules for measured values (cap, floor, enforce-or-track) instead of guessed numbers.
- **Type consistency:** `NearMiss(query, decoy, kind, shared_fields)` and its properties `query_id`/`pair_type` are defined in Task 8 and used unchanged in Tasks 10-12; `find_near_misses(...) -> NearMissResult(near_misses, yield_by_kind)` is used in Task 12; `rebalance_negatives(records, *, target_share, seed, min_per_category)` is defined and used in Tasks 10 and 12; `negative_share`, `all_yes_f1`, `missing_hard_negative_categories`, `decoy_no_overlap_rate` are defined in Task 9 and named identically in the Task 13 thresholds.
- **Known risks:**
  - Near-miss yield per kind is data-dependent; Task 12's manifest reports it and Task 14 Step 3 stops on a shortfall instead of weakening a gate.
  - Realistic file sizes grow with decoy bodies; Task 14 Step 3 checks each file is under 50 MB.
  - Direct-index sites (`household_assignment.py:251`, `special_populations.py:409,415`, `drift_mutations.py:92-96`) are guarded today; the full test run in Tasks 6 and 15 is the check that omitting empty `address`/`telecom` broke nothing.
  - The small-scale realistic test skips `missing_hard_negative_categories` (scale-dependent); the full-scale value is gated by `test_committed_realistic.py`.
