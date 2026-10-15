"""Unit tests for audit.py (session 15)."""

from __future__ import annotations

import math
from datetime import date

import pytest
from audit import (
    age_band_shares,
    all_yes_f1,
    category_of,
    conformance_violations,
    decoy_no_overlap_rate,
    id_equality_f1,
    identical_positive_pairs,
    match_count_share,
    matches_first_rate,
    missing_hard_negative_categories,
    negative_share,
    pairwise_two_of_three_f1,
    people_per_address,
    population_categories,
    population_pairs,
    positive_field_disagreement,
    probable_duplicate_negatives,
    same_person_negatives,
    shared_contact_rate,
    tier_parity_gap,
)
from fhir_conformance import export_ready
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
            ("address_move", "address_move"),
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
            _row("2", _patient("a"), _patient("a"), True, "address_move"),
        ]
        query_rows = [{"rationale": "population/fuzzy_variant+hard_negative"}]
        assert population_categories(query_rows) == {"fuzzy_variant", "hard_negative"}
        assert tier_parity_gap(pair_rows, query_rows) == ["address_move"]


class TestTierParityExemption:
    def test_pairwise_only_categories_are_not_a_parity_gap(self):
        pair_rows = [
            _row(
                "1",
                _patient("a"),
                _patient("b"),
                False,
                "placeholder_collision_negative/ssn",
            ),
            _row("2", _patient("a"), _patient("a"), True, "address_move"),
        ]
        query_rows = [{"rationale": "population/fuzzy_variant"}]
        assert tier_parity_gap(pair_rows, query_rows) == ["address_move"]


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
        assert report["positive_phone_drift_rate"] == 0.0


class TestAgeBandMaxError:
    def test_zero_when_the_shares_equal_the_targets(self):
        from audit import age_band_max_error
        from population_targets import age_band_targets

        years = {"0-17": 2015, "18-64": 1980, "65-84": 1950, "85+": 1930}
        patients = []
        for band, share in age_band_targets().items():
            patients += [
                _patient(f"{band}-{i}", dob=f"{years[band]}-06-15")
                for i in range(round(share * 10000))
            ]
        assert age_band_max_error(patients, as_of=date(2026, 1, 1)) < 0.001

    def test_reports_the_largest_band_gap_and_nan_without_dates(self):
        from audit import age_band_max_error

        elderly = [_patient(f"e{i}", dob="1930-06-15") for i in range(10)]
        assert age_band_max_error(elderly, as_of=date(2026, 1, 1)) == pytest.approx(
            1.0 - 0.0195
        )
        assert math.isnan(age_band_max_error([], as_of=date(2026, 1, 1)))


def test_dataset_paths_rejects_unknown_dataset():
    import pytest
    from audit import dataset_paths

    with pytest.raises(ValueError, match="unknown dataset"):
        dataset_paths("nope")


def test_population_pairs_rejects_dangling_candidate():
    import pytest
    from audit import population_pairs

    queries = [
        {
            "query_id": "q1",
            "query": {},
            "candidate_ids": ["x"],
            "expected_match_ids": [],
        }
    ]
    with pytest.raises(ValueError, match="unknown candidate"):
        list(population_pairs(queries, {}))


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
            "twin_like_negative",
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


def _query_row(query, candidates, expected=()):
    return {
        "query_id": query["id"],
        "query": query,
        "candidate_ids": [c["id"] for c in candidates],
        "expected_match_ids": list(expected),
    }


class TestProbableDuplicateNegatives:
    def test_flags_the_same_first_name_and_birth_date_under_another_surname(self):
        a = _patient("a", "Katherine", "Smith", dob="1980-06-15")
        b = _patient("b", "Katherine", "Okafor", dob="1980-06-15")
        assert self._flag(a, b) == ["c1"]

    def test_does_not_flag_a_different_first_name_with_the_same_birth_date(self):
        a = _patient("a", "Katherine", "Smith", dob="1980-06-15")
        b = _patient("b", "Maria", "Okafor", dob="1980-06-15")
        assert self._flag(a, b) == []

    def _flag(self, a, b):
        row = _row("c1", a, b, False, "hard_negative")
        return probable_duplicate_negatives([row], [], {})

    def test_flags_ssn_one_digit_off(self):
        a = _patient("a", "Eugene", "Benally", ssn="892-39-5115")
        b = _patient("b", "Maria", "Lopez", dob="1999-09-09", ssn="892-39-5116")
        assert self._flag(a, b) == ["c1"]

    def test_flags_a_name_typo_with_a_birth_month_off_by_one(self):
        a = _patient("a", "Gerald", "Gutschow", dob="1980-11-05")
        b = _patient("b", "Gerald", "Gutachow", dob="1980-12-05")
        assert self._flag(a, b) == ["c1"]

    def test_flags_shared_phone_with_identical_dob(self):
        a = _patient("a", "Harris", "Greene", dob="1980-06-15", phones=("3479846839",))
        b = _patient("b", "Jim", "Other", dob="1980-06-15", phones=("(347) 984-6839",))
        assert self._flag(a, b) == ["c1"]

    def test_does_not_flag_household_members_with_birth_dates_a_digit_apart(self):
        a = _patient(
            "a", "Kathleen", "Hileman", dob="1958-03-07", phones=("2017226909",)
        )
        b = _patient("b", "Krista", "Burke", dob="1958-03-04", phones=("2017226909",))
        assert self._flag(a, b) == []

    def test_does_not_flag_a_same_name_pair_decades_apart(self):
        a = _patient("a", "Angela", "Damron", dob="1977-07-05")
        b = _patient("b", "Angela", "Damron", dob="1927-04-05")
        assert self._flag(a, b) == []

    def test_flags_identical_rare_name_with_dob_one_digit_apart(self):
        a = _patient("a", "Rosalind", "Vandermeer", dob="1980-06-15")
        b = _patient("b", "Rosalind", "Vandermeer", dob="1980-06-25")
        assert self._flag(a, b) == ["c1"]

    def test_flags_a_month_day_swap_with_the_same_name(self):
        a = _patient("a", "Rosalind", "Vandermeer", dob="1980-03-11")
        b = _patient("b", "Rosalind", "Vandermeer", dob="1980-11-03")
        assert self._flag(a, b) == ["c1"]

    def test_does_not_flag_a_name_collision_with_unrelated_dobs(self):
        a = _patient("a", "Rosalind", "Vandermeer", dob="1950-06-15")
        b = _patient("b", "Rosalind", "Vandermeer", dob="1991-12-30")
        assert self._flag(a, b) == []

    def test_does_not_flag_a_household_sharing_a_phone_across_generations(self):
        a = _patient(
            "a", "Rosalind", "Vandermeer", dob="1950-06-15", phones=("3479846839",)
        )
        b = _patient(
            "b", "Tess", "Vandermeer", dob="1985-01-02", phones=("3479846839",)
        )
        assert self._flag(a, b) == []

    def test_does_not_flag_placeholder_ssns_one_digit_apart(self):
        a = _patient("a", "Eugene", "Benally", dob="1950-01-01", ssn="123-45-6789")
        b = _patient("b", "Maria", "Lopez", dob="1999-09-09", ssn="123-45-6788")
        assert self._flag(a, b) == []

    def test_does_not_flag_positives(self):
        row = _row("c1", _patient("a"), _patient("a"), True)
        assert probable_duplicate_negatives([row], [], {}) == []

    def test_checks_every_non_matching_population_pool_pair(self):
        query = _patient("q", "Eugene", "Benally", dob="1971-02-02")
        typo = _patient("typo", "Etgene", "Benally", dob="1971-02-03")
        other = _patient("other", "Maria", "Lopez", dob="1999-09-09")
        true_match = _patient("m", "Eugene", "Benally", dob="1971-02-02")
        rows = [_query_row(query, [typo, other, true_match], expected=["m"])]
        candidates = {p["id"]: p for p in (typo, other, true_match)}
        assert probable_duplicate_negatives([], rows, candidates) == ["q::typo"]


class TestProbableDuplicateExemptsTwins:
    def _pair(self, second_given, phone="212-555-0101"):
        a = _patient("a", "Ana", "Rivera", dob="2010-03-04", phones=(phone,))
        b = _patient("b", second_given, "Rivera", dob="2010-03-04", phones=(phone,))
        return probable_duplicate_negatives(
            [_row("c", a, b, False, "twin_like_negative")], [], {}
        )

    def test_twins_sharing_a_phone_are_not_flagged(self):
        assert self._pair("Beatriz") == []

    def test_a_name_typo_sharing_a_phone_is_still_flagged(self):
        assert self._pair("Anna") == ["c"]


class TestIdenticalPositivePairs:
    def test_flags_byte_identical_positives_in_both_tiers(self):
        a = _patient("a")
        pair_rows = [
            _row("same", a, dict(a), True),
            _row("changed", a, _patient("a", dob="1980-06-16"), True),
            _row("negative", a, dict(a), False),
        ]
        query = _patient("q")
        twin = dict(query)
        edited = _patient("q", dob="1980-06-16")
        rows = [_query_row(query, [twin, edited], expected=["q", "q2"])]
        candidates = {"q": twin, "q2": edited}
        assert identical_positive_pairs(pair_rows, rows, candidates) == [
            "same",
            "q::q",
        ]


class TestConformanceViolations:
    def test_reports_problems_in_every_file(self):
        bad = {**_patient("b"), "telecom": [{"system": "phone", "value": ""}]}
        pair_rows = [_row("p", _patient("a"), bad, True)]
        query_rows = [_query_row(bad, [bad], expected=["b"])]
        found = conformance_violations(pair_rows, query_rows, {"b": bad})
        assert any(v.startswith("p.target:") for v in found)
        assert any(v.startswith("b.query:") for v in found)
        assert any(v.startswith("b:") for v in found)

    def test_is_empty_for_conformant_patients(self):
        good = export_ready(_patient("a"))
        assert conformance_violations([_row("p", good, good, True)], [], {}) == []


class TestIdEqualityF1:
    def test_is_perfect_when_ids_reveal_the_label(self):
        a = _patient("a")
        rows = [_row("p", a, dict(a), True), _row("n", a, _patient("b"), False)]
        assert id_equality_f1(rows) == 1.0

    def test_is_zero_when_ids_are_label_free(self):
        a, b = _patient("a"), _patient("b")
        rows = [_row("p", a, _patient("c"), True), _row("n", a, b, False)]
        assert id_equality_f1(rows) == 0.0


class TestMatchCountShare:
    def test_counts_queries_with_exactly_n_matches(self):
        q = _patient("q")
        rows = [
            _query_row(q, [_patient("x")], expected=[]),
            _query_row(q, [_patient("m"), _patient("x")], expected=["m"]),
            _query_row(q, [_patient("m"), _patient("n")], expected=["m", "n"]),
            _query_row(q, [_patient("x")], expected=[]),
        ]
        assert match_count_share(rows, 0) == 0.5
        assert match_count_share(rows, 1) == 0.25
        assert match_count_share(rows, 2) == 0.25

    def test_is_zero_without_queries(self):
        assert match_count_share([], 0) == 0.0


class TestMatchesFirstRate:
    def test_counts_queries_whose_matches_lead_the_pool(self):
        q = _patient("q")
        leading = _query_row(q, [_patient("m"), _patient("x")], expected=["m"])
        trailing = _query_row(q, [_patient("x"), _patient("m")], expected=["m"])
        assert matches_first_rate([leading, trailing]) == 0.5

    def test_ignores_queries_without_matches(self):
        q = _patient("q")
        assert matches_first_rate([_query_row(q, [_patient("x")])]) == 0.0


class TestPairwiseTwoOfThreeF1:
    def test_scores_the_two_of_three_rule(self):
        base = _patient("a")
        match_same_name_dob = _row("1", base, _patient("b", street="9 Elm"), True)
        miss_positive = _row(
            "2", base, _patient("c", given="Zed", family="Z", dob="1999-01-01"), True
        )
        false_alarm = _row(
            "3", base, _patient("d", given="Zed", dob="1980-06-15"), False
        )
        quiet_negative = _row(
            "4", base, _patient("e", given="Zed", family="Z", dob="1999-01-01"), False
        )
        # predictions: 1 yes (tp), 2 no (fn), 3 yes (fp: family+dob), 4 no
        assert pairwise_two_of_three_f1(
            [match_same_name_dob, miss_positive, false_alarm, quiet_negative]
        ) == pytest.approx(2 * 1 / (2 * 1 + 1 + 1))

    def test_empty_or_all_negative_rows_score_zero(self):
        assert pairwise_two_of_three_f1([]) == 0.0
