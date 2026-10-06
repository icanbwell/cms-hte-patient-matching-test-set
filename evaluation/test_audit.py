"""Unit tests for audit.py (session 15)."""

from __future__ import annotations

import math
from datetime import date

import pytest
from audit import (
    age_band_shares,
    category_of,
    people_per_address,
    population_categories,
    population_pairs,
    positive_field_disagreement,
    same_person_negatives,
    shared_contact_rate,
    tier_parity_gap,
)
from identity_guard import SSN_SYSTEM


def _patient(
    id_: str,
    given: str = "Katherine",
    family: str = "Smith",
    dob: str = "1980-06-15",
    street: str = "1 Main St",
    phones: tuple[str, ...] = (),
    gender: str = "female",
    ssn: str | None = None,
):
    return {
        "resourceType": "Patient",
        "id": id_,
        "name": [{"family": family, "given": [given]}],
        "gender": gender,
        "birthDate": dob,
        "telecom": [{"system": "phone", "value": v} for v in phones],
        "address": [
            {"line": [street], "city": "NY", "state": "NY", "postalCode": "10001"}
        ],
        "identifier": [{"system": SSN_SYSTEM, "value": ssn}] if ssn else [],
    }


def _row(case_id, source, target, expected, rationale="fuzzy_variant/dob_day"):
    return {
        "case_id": case_id,
        "source": source,
        "target": target,
        "expected_match": expected,
        "rationale": rationale,
        "frequency": 1.0,
    }


class TestCategoryOf:
    @pytest.mark.parametrize(
        "rationale,expected",
        [
            ("fuzzy_variant/family_typo", "fuzzy_variant"),
            ("marriage_variant", "marriage_variant"),
            ("sibling_negative (age_gap_years=1, family_name=X)", "sibling_negative"),
            ("compound_variant (mutations=a,b)", "compound_variant"),
        ],
    )
    def test_extracts_leading_category(self, rationale, expected):
        assert category_of(rationale) == expected


class TestSamePersonNegatives:
    def test_flags_only_negatives_that_could_be_the_same_person(self):
        dup = _row("dup", _patient("a"), _patient("b"), False, "sibling_negative")
        distinct = _row(
            "ok", _patient("a"), _patient("c", given="Robert"), False, "hard_negative"
        )
        positive = _row("pos", _patient("a"), _patient("a"), True)
        assert same_person_negatives([dup, distinct, positive]) == ["dup"]


class TestTierParity:
    def test_lists_pair_categories_missing_from_population_rationales(self):
        pair_rows = [
            _row("1", _patient("a"), _patient("a"), True, "fuzzy_variant/dob_day"),
            _row("2", _patient("a"), _patient("a"), True, "marriage_variant"),
        ]
        query_rows = [{"rationale": "population/fuzzy_variant+hard_negative"}]
        assert population_categories(query_rows) == {"fuzzy_variant", "hard_negative"}
        assert tier_parity_gap(pair_rows, query_rows) == ["marriage_variant"]


class TestPositiveFieldDisagreement:
    def test_reports_the_share_of_positives_where_each_field_differs(self):
        same = _row(
            "1", _patient("a", phones=("1",)), _patient("a", phones=("1",)), True
        )
        drift = _row(
            "2",
            _patient("a", phones=("1",), gender="female"),
            _patient("a", phones=("2",), gender="male"),
            True,
        )
        negative = _row("3", _patient("a"), _patient("b", phones=("9",)), False)
        rates = positive_field_disagreement([same, drift, negative])
        assert rates["phone"] == 0.5
        assert rates["gender"] == 0.5
        assert rates["birthDate"] == 0.0


class TestPopulationMetrics:
    def test_people_per_address(self):
        patients = [
            _patient("a"),
            _patient("b", given="Robert"),
            _patient("c", street="9 Elm St"),
        ]
        assert people_per_address(patients) == 1.5

    def test_shared_contact_rate_counts_patients_not_values(self):
        patients = [
            _patient("a", phones=("347-984-6839",)),
            _patient("b", given="Robert", phones=("(347) 984-6839",)),
            _patient("c", given="Ana", phones=("212-555-0100",)),
            _patient("d", given="Luis"),
        ]
        assert shared_contact_rate(patients, "phone") == pytest.approx(2 / 3)

    def test_age_band_shares_use_the_fixed_as_of_date(self):
        patients = [
            _patient("a", dob="2015-01-01"),
            _patient("b", dob="1980-01-01"),
            _patient("c", dob="1930-01-01"),
            _patient("d", dob="1990-01-01"),
        ]
        shares = age_band_shares(patients, as_of=date(2026, 1, 1))
        assert shares == {"0-17": 0.25, "18-64": 0.5, "65-84": 0.0, "85+": 0.25}


class TestPopulationPairs:
    def test_labels_candidates_by_expected_match_ids(self):
        query = _patient("q")
        candidates = {"m": _patient("q"), "x": _patient("x", given="Robert")}
        rows = [
            {
                "query_id": "q",
                "query": query,
                "candidate_ids": ["m", "x"],
                "expected_match_ids": ["m"],
                "rationale": "population/fuzzy_variant",
            }
        ]
        pairs = list(population_pairs(rows, candidates))
        assert [(p.pair_id, p.is_true_match) for p in pairs] == [
            ("q::m", True),
            ("q::x", False),
        ]


class TestDegenerateInputs:
    def test_empty_inputs_return_nan_instead_of_raising(self):
        assert all(math.isnan(v) for v in positive_field_disagreement([]).values())
        assert math.isnan(people_per_address([]))
        assert math.isnan(shared_contact_rate([], "phone"))
        assert all(math.isnan(v) for v in age_band_shares([]).values())

    def test_bare_patients_do_not_raise(self):
        bare = [
            {"resourceType": "Patient", "id": "x"},
            {"resourceType": "Patient", "id": "y"},
        ]
        assert math.isnan(people_per_address(bare))
        assert math.isnan(shared_contact_rate(bare, "email"))

    def test_unparseable_birth_dates_are_skipped_not_fatal(self):
        patients = [
            _patient("a", dob="unknown"),
            _patient("b", dob="1980-01-01"),
            {"resourceType": "Patient", "id": "c", "birthDate": ""},
        ]
        shares = age_band_shares(patients, as_of=date(2026, 1, 1))
        assert shares["18-64"] == 1.0

    def test_phone_sharing_ignores_formatting_and_country_code(self):
        patients = [
            _patient("a", phones=("347-984-6839",)),
            _patient("b", given="Robert", phones=("+1 (347) 984-6839",)),
        ]
        assert shared_contact_rate(patients, "phone") == 1.0


class TestBuildReportGuards:
    def _write(self, path, rows):
        import json

        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        return path

    def _inputs(self, tmp_path, pairs=True, queries=True, candidates=True):
        a, b = _patient("q"), _patient("x", given="Robert", family="Jones")
        return (
            self._write(
                tmp_path / "pairs.jsonl",
                [_row("c1", a, a, True)] if pairs else [],
            ),
            self._write(
                tmp_path / "queries.jsonl",
                [
                    {
                        "query_id": "q",
                        "query": a,
                        "candidate_ids": ["x"],
                        "expected_match_ids": [],
                        "rationale": "population/fuzzy_variant",
                    }
                ]
                if queries
                else [],
            ),
            self._write(
                tmp_path / "cands.jsonl",
                [{"id": "x", "patient": b}] if candidates else [],
            ),
        )

    @pytest.mark.parametrize("empty", ["pairs", "queries", "candidates"])
    def test_an_empty_input_file_raises_instead_of_passing_vacuously(
        self, tmp_path, empty
    ):
        from audit import build_report

        pairs, queries, candidates = self._inputs(tmp_path, **{empty: False})
        with pytest.raises(ValueError, match="no rows"):
            build_report(pairs, queries, candidates)

    def test_a_baseline_that_never_predicts_scores_zero_not_nan(self, tmp_path):
        from audit import build_report

        report = build_report(*self._inputs(tmp_path))
        assert all(v == 0.0 for v in report["baseline_f1"].values())
        assert report["best_single_field_f1"] == 0.0
        assert report["multi_field_margin"] == 0.0
