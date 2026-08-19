"""Unit tests for export_test_dataset.py (session 10 continuation).

Depends on numpy transitively via labeled_pairs -> rule_eval - see
test_rule_eval.py's module docstring for why these importorskip("numpy").
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("numpy")

from export_test_dataset import (  # noqa: E402
    LabeledCaseRecord,
    build_test_case_records,
    format_rationale,
    uniform_frequency,
    write_jsonl,
)


def _patient(id_: str, family: str = "Smith", given: str = "Katherine"):
    return {
        "resourceType": "Patient",
        "id": id_,
        "name": [{"family": family, "given": [given]}],
        "birthDate": "1980-06-15",
        "telecom": [],
        "address": [{"line": ["1 Main St"], "city": "NY", "state": "NY", "postalCode": "10001"}],
        "identifier": [],
    }


class TestFormatRationale:
    def test_includes_mutation_subtype(self):
        rationale = format_rationale({"pair_type": "fuzzy_variant", "mutation": "dob_day"})
        assert "fuzzy_variant" in rationale
        assert "dob_day" in rationale

    def test_includes_all_strata_keys_for_hard_negative(self):
        rationale = format_rationale(
            {"pair_type": "hard_negative", "postalCode": "10001", "birthDate": "1980-01-01"}
        )
        assert "hard_negative" in rationale
        assert "postalCode=10001" in rationale
        assert "birthDate=1980-01-01" in rationale

    def test_category_is_treated_as_a_subtype_not_extra_context(self):
        """category is one of the subtype keys (mutation/case/category), so it
        folds into the "<pair_type>/<subtype>" head, same as mutation/case -
        it should not also appear as a separate "category=..." context term."""
        rationale = format_rationale({"pair_type": "special_population", "category": "shelter"})
        assert rationale == "special_population/shelter"

    def test_bare_pair_type_with_no_subtype_or_context(self):
        rationale = format_rationale({"pair_type": "fuzzy_variant"})
        assert rationale == "fuzzy_variant"


class TestUniformFrequency:
    def test_always_returns_one_regardless_of_rationale(self):
        assert uniform_frequency("fuzzy_variant/dob_day") == 1.0
        assert uniform_frequency("special_population/shelter") == 1.0
        assert uniform_frequency("anything else entirely") == 1.0


class TestBuildLabeledCaseRecords:
    def test_produces_records_with_raw_fhir_patients(self):
        patients = [_patient("p1"), _patient("p2", family="Jones", given="Robert")]
        records = build_test_case_records(patients, seed=0)
        assert len(records) > 0
        for r in records:
            assert isinstance(r, LabeledCaseRecord)
            assert r.source.get("resourceType") == "Patient"
            assert r.target.get("resourceType") == "Patient"
            assert isinstance(r.expected_match, bool)
            assert r.rationale
            assert r.case_id

    def test_defaults_every_record_to_uniform_frequency(self):
        """No real-world-prevalence weighting yet - every case counts equally
        until a real, cited frequency_lookup is supplied (see a follow-up PR
        for that)."""
        patients = [_patient("p1"), _patient("p2", family="Jones", given="Robert")]
        records = build_test_case_records(patients, seed=0)
        assert all(r.frequency == 1.0 for r in records)

    def test_custom_frequency_lookup_is_applied_per_rationale(self):
        patients = [_patient("p1")]
        records = build_test_case_records(
            patients, seed=0, frequency_lookup=lambda rationale: 42.0
        )
        assert all(r.frequency == 42.0 for r in records)

    def test_is_deterministic_given_a_seed(self):
        patients = [_patient("p1"), _patient("p2", family="Jones", given="Robert")]
        first = build_test_case_records(patients, seed=42)
        second = build_test_case_records(patients, seed=42)
        assert [r.case_id for r in first] == [r.case_id for r in second]

    def test_true_match_and_non_match_records_both_present(self):
        patients = [_patient("p1", family="Smith"), _patient("p2", family="Jones")]
        records = build_test_case_records(patients, seed=0)
        assert any(r.expected_match for r in records)
        assert any(not r.expected_match for r in records)


class TestWriteJsonl:
    def test_writes_one_json_object_per_line(self, tmp_path):
        records = [
            LabeledCaseRecord(
                case_id="case-1",
                source=_patient("p1"),
                target=_patient("p2"),
                expected_match=True,
                rationale="fuzzy_variant/dob_day",
            ),
            LabeledCaseRecord(
                case_id="case-2",
                source=_patient("p3"),
                target=_patient("p4"),
                expected_match=False,
                rationale="hard_negative",
            ),
        ]
        out_path = tmp_path / "cases.jsonl"
        write_jsonl(records, out_path)

        lines = out_path.read_text().strip().split("\n")
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["case_id"] == "case-1"
        assert first["source"]["id"] == "p1"
        assert first["target"]["id"] == "p2"
        assert first["expected_match"] is True
        assert first["rationale"] == "fuzzy_variant/dob_day"
        assert first["frequency"] == 1.0

    def test_creates_parent_directory_if_missing(self, tmp_path):
        records = [
            LabeledCaseRecord(
                case_id="case-1",
                source=_patient("p1"),
                target=_patient("p2"),
                expected_match=True,
                rationale="fuzzy_variant/dob_day",
            )
        ]
        out_path = tmp_path / "nested" / "dir" / "cases.jsonl"
        write_jsonl(records, out_path)
        assert out_path.exists()
