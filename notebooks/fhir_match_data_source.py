# ruff: noqa: F821
# mypy: ignore-errors
"""Real-World FHIR Match Data Source -- Tier 2 Statistical Rigor.

Author: Data Science. Context: `docs/sessions/pending/session_4.md` -- Line B: CMS
v3.3 migration, Evaluation & Statistical Rigor Framework.

Session 3's ONC baseline proves the engine's self-match integrity on public,
synthetic data. This notebook builds the real-population complement: a reproducible
query over `bronze.fhir_lake.patient_4_0_0` (FHIR Patient resources) joined to
`silver.fhir_lite.person_patient` (the current algorithm's existing Person-Patient
links), producing (a) `rule_eval.LabeledPair`s tagged
`strata={"source": "current_algorithm_link"}` and (b) observed per-field collision
rates compared against Table 3's conservative u-probabilities
(`patient_matching/matching/collision.py`, session 5).

Never a precision/recall/FPR claim -- the current algorithm's links are not ground
truth (they're produced by the very algorithm this repo aims to replace/compare
against). This notebook reports agreement rate with those links (descriptive) and
collision rate (a well-posed statistical quantity), per session_4.md's "Out of
scope" note. No row-level data or query output is committed to this repo -- only
this parameterized notebook.
"""

import random
from collections import Counter
from math import comb
from typing import Any, Dict, List, Sequence, Set, Tuple

from patient_matching.matching.collision import FIELD_U_PROBS
from patient_matching.matching.field_extractor import FieldExtractor, PatientFields
from patient_matching.matching.in_memory_backend import InMemoryBackend
from patient_matching.matching.matching_engine import MatchingEngine
from patient_matching.normalization.manager import NormalizationManager

try:
    from evaluation.rule_eval import LabeledPair
except (
    ImportError
):  # pragma: no cover - only hit when Databricks doesn't have evaluation/ on sys.path
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "evaluation"))
    from rule_eval import LabeledPair  # type: ignore[no-redef]

try:
    from notebooks._sql_safety import _validate_sql_identifier
except (
    ImportError
):  # pragma: no cover - only hit when Databricks doesn't have notebooks/ on sys.path
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _sql_safety import _validate_sql_identifier  # type: ignore[no-redef]

# Strata tag applied to every LabeledPair built from the current algorithm's existing
# Person-Patient links - see build_person_patient_pairs's docstring for why this is
# descriptive only, never ground truth.
_CURRENT_ALGORITHM_LINK_SOURCE = "current_algorithm_link"

# Negative-sampling retry budget: random (i, j) draws can collide with an already-seen
# pair or with themselves, so allow enough attempts to fill n_negative_samples without
# spinning forever on a small person_id pool.
_NEGATIVE_SAMPLE_RETRY_MULTIPLIER = 50
_NEGATIVE_SAMPLE_RETRY_BASE = 100

# Cap on negative samples drawn per run, independent of sample size, to keep local
# processing tractable.
_MAX_NEGATIVE_SAMPLES = 2000


# --- Widgets (Databricks). Falls back to defaults when run outside Databricks. ------------
# Table names confirmed at session-start (2026-08-06): both sides are Databricks tables
# reachable via spark.sql - no separate Mongo connection pattern is needed (resolves
# session_4.md's NEEDS HUMAN DECISION; see docs/sessions/in_review/session_4.md's Execution
# notes for the full resolution).
try:
    dbutils.widgets.text("fhir_catalog", "bronze", "FHIR Patient catalog")
    dbutils.widgets.text("fhir_schema", "fhir_lake", "FHIR Patient schema")
    dbutils.widgets.text("fhir_patient_table", "patient_4_0_0", "FHIR Patient table")
    dbutils.widgets.text(
        "match_links_table",
        "silver.fhir_lite.person_patient",
        "Person-Patient match links table",
    )
    dbutils.widgets.text(
        "sample_size", "5000", "Row sample size (keep local processing tractable)"
    )

    FHIR_CATALOG = _validate_sql_identifier(dbutils.widgets.get("fhir_catalog"))
    FHIR_SCHEMA = _validate_sql_identifier(dbutils.widgets.get("fhir_schema"))
    FHIR_PATIENT_TABLE_NAME = _validate_sql_identifier(
        dbutils.widgets.get("fhir_patient_table")
    )
    FHIR_TABLE = _validate_sql_identifier(
        f"{FHIR_CATALOG}.{FHIR_SCHEMA}.{FHIR_PATIENT_TABLE_NAME}"
    )
    MATCH_TABLE = _validate_sql_identifier(dbutils.widgets.get("match_links_table"))
    SAMPLE_SIZE = int(dbutils.widgets.get("sample_size"))
    if SAMPLE_SIZE <= 0:
        raise ValueError(f"sample_size must be positive, got {SAMPLE_SIZE}")
    IN_DATABRICKS = True
except NameError:
    FHIR_TABLE = "bronze.fhir_lake.patient_4_0_0"
    MATCH_TABLE = "silver.fhir_lite.person_patient"
    SAMPLE_SIZE = 5000
    IN_DATABRICKS = False

print(f"IN_DATABRICKS={IN_DATABRICKS}")
print(f"FHIR_TABLE={FHIR_TABLE}  MATCH_TABLE={MATCH_TABLE}  SAMPLE_SIZE={SAMPLE_SIZE}")

# 1. Query: sample FHIR Patients joined to their existing Person-Patient link.
# Joins on `patient._uuid = person_patient.patient_uuid` -- `_uuid` is the platform's
# internal cross-reference identifier (the same field every `reference`-typed struct
# elsewhere in this schema uses to point at a Patient, e.g.
# `generalPractitioner[]._uuid`), not the FHIR-spec `id` field. Assumption to verify
# empirically the first time this runs: check the printed match-rate below (matched
# rows / SAMPLE_SIZE) -- a near-zero rate would mean this join key guess is wrong for
# this workspace.

_PATIENT_COLUMNS = (
    "_uuid",
    "name",
    "birthDate",
    "telecom",
    "address",
    "identifier",
    "gender",
)


def build_join_query(fhir_table: str, match_table: str, sample_size: int) -> str:
    _validate_sql_identifier(fhir_table)
    _validate_sql_identifier(match_table)
    cols = ", ".join(f"p.{c}" for c in _PATIENT_COLUMNS)
    return (
        f"SELECT {cols}, m.person_uuid AS person_uuid "
        f"FROM {fhir_table} p "
        f"JOIN {match_table} m ON p._uuid = m.patient_uuid "
        f"LIMIT {int(sample_size)}"
    )


if IN_DATABRICKS:
    query = build_join_query(FHIR_TABLE, MATCH_TABLE, SAMPLE_SIZE)
    print(query)
    joined_rows = [r.asDict(recursive=True) for r in spark.sql(query).collect()]
    print(
        f"Joined rows: {len(joined_rows)} of requested sample_size={SAMPLE_SIZE} "
        f"(a low ratio may mean the _uuid<->patient_uuid join key assumption above is wrong for this workspace)"
    )
else:
    print(
        "Not running in Databricks — nothing to query locally. Run this in a Databricks "
        "notebook/cluster with real workspace access to pull real data."
    )
    joined_rows = []

# 2. Transform: join-row -> FHIR Patient dict -> LabeledPairs.
# Mirrors `evaluation/onc_baseline.py::build_onc_pairs`'s shape (normalize, then
# `FieldExtractor.extract`, `features={"query": ..., "candidate": ...}`) so this
# session's `LabeledPair`s slot into the same `rule_eval.py` machinery session 3
# already validated - just sourced from a live join instead of a CSV.

_PATIENT_LIST_FIELDS = ("name", "telecom", "address", "identifier")


def row_to_fhir_patient(row: Dict[str, Any]) -> Dict[str, Any]:
    """Strip join-only columns (patient_uuid/person_uuid) and normalize absent/None
    values to the empty-list/empty-string shape FieldExtractor and NormalizationManager
    expect from a FHIR Patient dict."""
    patient: Dict[str, Any] = {}
    for field_name in _PATIENT_LIST_FIELDS:
        patient[field_name] = row.get(field_name) or []
    patient["birthDate"] = row.get("birthDate") or ""
    patient["gender"] = row.get("gender") or ""
    return patient


def build_person_patient_pairs(
    rows: Sequence[Tuple[str, str, PatientFields]],
    *,
    n_negative_samples: int,
    seed: int = 0,
) -> List[LabeledPair]:
    """Build LabeledPairs from (patient_uuid, person_uuid, PatientFields) rows.

    True-match pairs: patient_uuids sharing a person_uuid, per the CURRENT algorithm's
    existing link - descriptive only, never ground truth (session_4.md's "Out of scope").
    Non-match pairs: a random sample of cross-person_uuid pairs, mirroring
    onc_baseline.build_onc_pairs's negative-sampling approach.
    """
    pairs: List[LabeledPair] = []
    by_person: Dict[str, List[Tuple[str, PatientFields]]] = {}
    for patient_uuid, person_uuid, fields in rows:
        by_person.setdefault(person_uuid, []).append((patient_uuid, fields))

    for person_uuid, members in by_person.items():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                pid_a, fields_a = members[i]
                pid_b, fields_b = members[j]
                pairs.append(
                    LabeledPair(
                        features={"query": fields_a, "candidate": fields_b},
                        is_true_match=True,
                        strata={"source": _CURRENT_ALGORITHM_LINK_SOURCE},
                        pair_id=f"{pid_a}::{pid_b}",
                    )
                )

    person_ids = list(by_person.keys())
    if len(person_ids) < 2 or n_negative_samples <= 0:
        return pairs

    rng = random.Random(seed)
    seen: Set[Tuple[int, int]] = set()
    attempts = 0
    max_attempts = (
        n_negative_samples * _NEGATIVE_SAMPLE_RETRY_MULTIPLIER
        + _NEGATIVE_SAMPLE_RETRY_BASE
    )
    while len(seen) < n_negative_samples and attempts < max_attempts:
        attempts += 1
        i, j = rng.randrange(len(person_ids)), rng.randrange(len(person_ids))
        if i == j or (i, j) in seen or (j, i) in seen:
            continue
        seen.add((i, j))
        pid_a, fields_a = rng.choice(by_person[person_ids[i]])
        pid_b, fields_b = rng.choice(by_person[person_ids[j]])
        pairs.append(
            LabeledPair(
                features={"query": fields_a, "candidate": fields_b},
                is_true_match=False,
                strata={"source": _CURRENT_ALGORITHM_LINK_SOURCE},
                pair_id=f"{pid_a}::{pid_b}",
            )
        )
    return pairs


if IN_DATABRICKS:
    normalizer = NormalizationManager()
    extractor = FieldExtractor()
    extracted_rows: List[Tuple[str, str, PatientFields]] = [
        (
            row["_uuid"],
            row["person_uuid"],
            extractor.extract(normalizer.normalize(row_to_fhir_patient(row))),
        )
        for row in joined_rows
    ]
    labeled_pairs = build_person_patient_pairs(
        extracted_rows,
        n_negative_samples=min(len(extracted_rows), _MAX_NEGATIVE_SAMPLES),
    )
    print(
        f"Built {len(labeled_pairs)} LabeledPairs "
        f"({sum(p.is_true_match for p in labeled_pairs)} true-match, "
        f"{sum(not p.is_true_match for p in labeled_pairs)} sampled non-match)"
    )
else:
    extracted_rows = []
    labeled_pairs = []

# 3. Agreement rate -- does the NEW engine agree with the current algorithm's links?
# Descriptive only -- the current algorithm's links are not ground truth, so this is
# NOT a precision/recall/FPR claim (session_4.md's "Out of scope"). It answers "how
# often does the candidate engine's decision match what the current algorithm already
# decided?", not "is the candidate correct?".

_default_engine_singleton: MatchingEngine | None = None


def _default_engine() -> MatchingEngine:
    """Lazily-constructed default engine, reused across calls when no engine is injected."""
    global _default_engine_singleton
    if _default_engine_singleton is None:
        _default_engine_singleton = MatchingEngine(backend=InMemoryBackend([]))
    return _default_engine_singleton


def agreement_rate(
    pairs: Sequence[LabeledPair], engine: MatchingEngine | None = None
) -> float:
    """How often `engine.evaluate_pair` agrees with each pair's `is_true_match` label.

    `engine` defaults to a lazily-constructed module-level MatchingEngine (this notebook's
    only caller), but accepts an injected engine/stub so callers - including tests - don't
    need to go through the module-level singleton.
    """
    if not pairs:
        return float("nan")
    active_engine = engine if engine is not None else _default_engine()
    agreements = sum(
        1
        for p in pairs
        if active_engine.evaluate_pair(p.features["query"], p.features["candidate"])
        == p.is_true_match
    )
    return agreements / len(pairs)


if IN_DATABRICKS and labeled_pairs:
    rate = agreement_rate(labeled_pairs)
    print(
        f"Agreement with current algorithm's existing links: {rate:.1%} "
        f"(descriptive statistic — NOT precision/recall; the current algorithm's links are not ground truth)"
    )

# 4. Observed per-field collision rates vs. Table 3's conservative u-probabilities.
# `observed_collision_rate` estimates P(two random distinct people share >=1 common
# value for a field) as `sum_v C(n_v, 2) / C(N, 2)` -- the same collision-probability
# framing `patient_matching/matching/collision.py`'s Table 3 u-probabilities use, just
# computed empirically on this sample instead of transcribed from the CMS spec. One
# row per distinct `person_uuid` (not per raw Patient record) so a person with
# multiple linked Patient records isn't double-counted.


def observed_collision_rate(values_per_person: Sequence[Set[str]]) -> float:
    """sum_v C(n_v, 2) / C(N, 2) across distinct people's value sets for one field.

    NaN when fewer than 2 people are present (the pairwise comparison is undefined).
    """
    n = len(values_per_person)
    if n < 2:
        return float("nan")
    counts: Counter[str] = Counter()
    for values in values_per_person:
        for v in values:
            counts[v] += 1
    numerator = sum(comb(c, 2) for c in counts.values())
    denominator = comb(n, 2)
    return numerator / denominator if denominator else float("nan")


# Only fields FieldExtractor actually populates - zip_code/city/state/insurance_* are v3.3
# additions not yet extracted (candidate scope for session 6, not this session).
_COLLISION_FIELDS = (
    "first_name",
    "last_name",
    "dob",
    "street_line",
    "phone",
    "email",
    "ssn_last4",
    "itin_last4",
    "mbi",
    "legal_id",
    "namespace_id",
)

if IN_DATABRICKS and extracted_rows:
    # One representative PatientFields per distinct person_uuid (first record wins) -
    # collision rate is about distinct PEOPLE, not raw Patient records.
    per_person: Dict[str, PatientFields] = {}
    for _patient_uuid, person_uuid, fields in extracted_rows:
        per_person.setdefault(person_uuid, fields)

    print(f"{'field':<20}{'observed':>12}{'Table 3 u (exact)':>20}")
    for field_name in _COLLISION_FIELDS:
        values_per_person = [pf.get_values(field_name) for pf in per_person.values()]
        observed = observed_collision_rate(values_per_person)
        conservative_u, _fuzzy_u = FIELD_U_PROBS[field_name]
        print(f"{field_name:<20}{observed:>12.6f}{conservative_u:>20.6f}")
    print(
        "\nDescriptive (Tier 2) only — not a precision/recall claim. A field where `observed` exceeds "
        "Table 3's conservative u suggests this population is less selective on that field than the "
        "spec assumes; flag for the lead engineer/maintainer before relying on it for a rule decision."
    )
