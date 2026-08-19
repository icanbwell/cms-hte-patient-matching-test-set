"""Tests for fhir_match_data_source.py's non-Databricks-dependent logic.

Real Databricks/Mongo access can't be unit-tested locally (see session_4.md's
"Unit tests required") - this covers the pure query-building, transform, and
collision-rate/agreement-rate logic that only needs plain dicts and a stub engine,
not a live Spark session or the real MatchingEngine. SQL-safety helper tests live in
`test__sql_safety.py` since `notebooks/_sql_safety.py` is now shared by multiple
notebooks (PR #22 review).

fhir_match_data_source imports LabeledPair from evaluation/rule_eval.py, which
requires numpy transitively - see evaluation/test_rule_eval.py's module docstring
for why this importorskip's numpy rather than failing hard in the default
(numpy-less) service CI image.
"""

from __future__ import annotations

import pytest

pytest.importorskip("numpy")

from notebooks.fhir_match_data_source import (  # noqa: E402
    _CURRENT_ALGORITHM_LINK_SOURCE,
    agreement_rate,
    build_join_query,
    build_person_patient_pairs,
    observed_collision_rate,
    row_to_fhir_patient,
)
from evaluation.rule_eval import LabeledPair  # noqa: E402


class TestBuildJoinQuery:
    def test_generates_expected_sql(self):
        query = build_join_query("bronze.fhir_lake.patient_4_0_0", "silver.fhir_lite.person_patient", 5000)
        assert query == (
            "SELECT p._uuid, p.name, p.birthDate, p.telecom, p.address, p.identifier, p.gender, "
            "m.person_uuid AS person_uuid "
            "FROM bronze.fhir_lake.patient_4_0_0 p "
            "JOIN silver.fhir_lite.person_patient m ON p._uuid = m.patient_uuid "
            "LIMIT 5000"
        )

    @pytest.mark.parametrize(
        "fhir_table,match_table",
        [
            ("bronze; DROP TABLE x", "silver.fhir_lite.person_patient"),
            ("bronze.fhir_lake.patient_4_0_0", "silver; DROP TABLE x"),
        ],
    )
    def test_rejects_unsafe_identifiers(self, fhir_table, match_table):
        with pytest.raises(ValueError):
            build_join_query(fhir_table, match_table, 5000)


class TestRowToFhirPatient:
    """Converts a flattened join-row dict (what .asDict(recursive=True) on the
    Spark join query's Row objects produces) into the plain FHIR Patient dict
    shape FieldExtractor/NormalizationManager expect."""

    def test_extracts_patient_shaped_fields_only(self):
        row = {
            "patient_uuid": "abc-123",
            "person_uuid": "person-1",
            "name": [{"family": "Smith", "given": ["Jane"]}],
            "birthDate": "1990-01-01",
            "telecom": [{"system": "phone", "value": "+15551234567"}],
            "address": [{"line": ["1 Main St"], "city": "Springfield"}],
            "identifier": [],
            "gender": "female",
        }
        patient = row_to_fhir_patient(row)
        assert patient["name"] == row["name"]
        assert patient["birthDate"] == "1990-01-01"
        assert patient["telecom"] == row["telecom"]
        assert "patient_uuid" not in patient
        assert "person_uuid" not in patient

    def test_missing_optional_fields_default_to_empty(self):
        row = {"patient_uuid": "x", "person_uuid": "p", "birthDate": None}
        patient = row_to_fhir_patient(row)
        assert patient["name"] == []
        assert patient["telecom"] == []
        assert patient["address"] == []
        assert patient["identifier"] == []
        assert patient["birthDate"] == ""


class TestBuildPersonPatientPairs:
    """True-match pairs come from patient_uuids sharing a person_uuid (the
    current algorithm's existing link) - never treated as ground truth, only
    tagged strata={"source": "current_algorithm_link"} per session_4.md's
    'Out of scope' note."""

    def _fields(self, first, last, dob="2000-01-01"):
        from patient_matching.matching.field_extractor import PatientFields

        return PatientFields(first_names={first}, last_names={last}, dob={dob})

    def test_same_person_uuid_yields_true_match_pair(self):
        rows = [
            ("p1", "person-A", self._fields("jane", "smith")),
            ("p2", "person-A", self._fields("jane", "smith")),
        ]
        pairs = build_person_patient_pairs(rows, n_negative_samples=0, seed=0)
        true_matches = [p for p in pairs if p.is_true_match]
        assert len(true_matches) == 1
        assert true_matches[0].strata == {"source": "current_algorithm_link"}

    def test_negative_sampling_only_draws_cross_person_pairs(self):
        rows = [
            ("p1", "person-A", self._fields("jane", "smith")),
            ("p2", "person-B", self._fields("john", "doe")),
            ("p3", "person-C", self._fields("mary", "jones")),
        ]
        pairs = build_person_patient_pairs(rows, n_negative_samples=2, seed=0)
        negatives = [p for p in pairs if not p.is_true_match]
        assert len(negatives) == 2
        assert all(p.strata == {"source": "current_algorithm_link"} for p in negatives)

    def test_no_true_match_pairs_when_every_person_uuid_is_unique(self):
        rows = [
            ("p1", "person-A", self._fields("jane", "smith")),
            ("p2", "person-B", self._fields("john", "doe")),
        ]
        pairs = build_person_patient_pairs(rows, n_negative_samples=1, seed=0)
        assert not any(p.is_true_match for p in pairs)


class TestObservedCollisionRate:
    """sum_v C(n_v, 2) / C(N, 2) - probability two random distinct people share
    a value for this field, the same collision-probability framing as Table 3's
    u-probabilities (patient_matching/matching/collision.py)."""

    def test_all_distinct_values_gives_zero_collision_rate(self):
        values_per_person = [{"a"}, {"b"}, {"c"}]
        assert observed_collision_rate(values_per_person) == 0.0

    def test_all_shared_value_gives_full_collision_rate(self):
        values_per_person = [{"a"}, {"a"}, {"a"}]
        assert observed_collision_rate(values_per_person) == 1.0

    def test_partial_overlap(self):
        # 3 people, 2 share "a" -> 1 colliding pair out of C(3,2)=3 total pairs
        values_per_person = [{"a"}, {"a"}, {"b"}]
        assert observed_collision_rate(values_per_person) == pytest.approx(1 / 3)

    def test_fewer_than_two_people_is_undefined(self):
        import math

        assert math.isnan(observed_collision_rate([{"a"}]))
        assert math.isnan(observed_collision_rate([]))


class _StubEngine:
    """Fake engine for agreement_rate tests - avoids constructing a real
    MatchingEngine/InMemoryBackend or going through the module-level singleton."""

    def __init__(self, decision: bool):
        self._decision = decision

    def evaluate_pair(self, query_fields, candidate_fields):
        return self._decision


class TestAgreementRate:
    """agreement_rate takes an injected engine (default: the module-level lazy
    singleton) so it's testable against a stub rather than a real MatchingEngine."""

    def _pair(self, is_true_match):
        return LabeledPair(
            features={"query": "q", "candidate": "c"},
            is_true_match=is_true_match,
            strata={"source": _CURRENT_ALGORITHM_LINK_SOURCE},
        )

    def test_empty_pairs_is_nan(self):
        import math

        assert math.isnan(agreement_rate([], engine=_StubEngine(True)))

    def test_full_agreement_when_engine_always_matches_true_pairs(self):
        pairs = [self._pair(True), self._pair(True)]
        assert agreement_rate(pairs, engine=_StubEngine(True)) == 1.0

    def test_zero_agreement_when_engine_disagrees_with_every_label(self):
        pairs = [self._pair(True), self._pair(True)]
        assert agreement_rate(pairs, engine=_StubEngine(False)) == 0.0

    def test_partial_agreement(self):
        pairs = [self._pair(True), self._pair(True), self._pair(False)]
        # Engine always returns True: agrees on the two True-labeled pairs, disagrees on the False one.
        assert agreement_rate(pairs, engine=_StubEngine(True)) == pytest.approx(2 / 3)
