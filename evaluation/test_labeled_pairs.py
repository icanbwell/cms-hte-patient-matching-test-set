"""Unit tests for labeled_pairs.py (session 9).

No numpy dependency here (session 13 dropped labeled_pairs.py's use of the
reference matching engine and rule_eval entirely - generate_raw_pairs() only touches
hard_negatives.py/mutations.py/normalization_edge_cases.py/
special_populations.py, none of which need numpy), so these always run.
"""

from __future__ import annotations

from labeled_pairs import generate_raw_pairs


def _patient(id_: str, family: str = "Smith", given: str = "Katherine"):
    return {
        "resourceType": "Patient",
        "id": id_,
        "name": [{"family": family, "given": [given]}],
        "birthDate": "1980-06-15",
        "telecom": [],
        "address": [
            {"line": ["1 Main St"], "city": "NY", "state": "NY", "postalCode": "10001"}
        ],
        "identifier": [],
    }


class TestGenerateRawPairs:
    def test_produces_one_fuzzy_variant_pair_per_patient_by_default(self) -> None:
        patients = [_patient("p1"), _patient("p2", family="Jones", given="Robert")]
        pairs = list(generate_raw_pairs(patients, seed=0))
        fuzzy_variants = [
            p for p in pairs if p.strata.get("pair_type") == "fuzzy_variant"
        ]
        assert len(fuzzy_variants) == len(patients)
        assert all(p.is_true_match for p in fuzzy_variants)

    def test_true_match_pairs_are_labeled_with_the_mutation_applied(self) -> None:
        pairs = list(generate_raw_pairs([_patient("p1")], seed=0))
        (pair,) = [p for p in pairs if p.strata.get("pair_type") == "fuzzy_variant"]
        assert pair.strata["mutation"]
        assert pair.pair_id == f"p1::{pair.strata['mutation']}"

    def test_hard_negative_pairs_are_labeled_non_match(self) -> None:
        # Same ZIP+DOB, distinct family names -> one mined hard negative.
        patients = [_patient("p1", family="Smith"), _patient("p2", family="Jones")]
        pairs = list(generate_raw_pairs(patients, seed=0))
        hard_negatives = [
            p for p in pairs if p.strata.get("pair_type") == "hard_negative"
        ]
        assert len(hard_negatives) == 1
        assert hard_negatives[0].is_true_match is False

    def test_more_variants_per_patient_scales_fuzzy_variant_count(self) -> None:
        pairs = list(
            generate_raw_pairs(
                [_patient("p1")],
                n_fuzzy_variants_per_patient=3,
                include_normalization_edge_cases=False,
                include_special_populations=False,
                seed=0,
            )
        )
        assert sum(p.is_true_match for p in pairs) == 3

    def test_normalization_edge_case_pairs_are_true_matches(self) -> None:
        pairs = list(generate_raw_pairs([_patient("p1")], seed=0))
        edge_cases = [
            p for p in pairs if p.strata.get("pair_type") == "normalization_edge_case"
        ]
        cases = {p.strata["case"] for p in edge_cases}
        assert cases == {"diacritic", "punctuation"}
        assert all(p.is_true_match for p in edge_cases)

    def test_special_population_household_pairs_are_true_non_matches(self) -> None:
        patients = [
            _patient("p1", family="Rivera", given="Ana"),
            _patient("p2", family="Rivera", given="Luis"),
        ]
        patients[1]["birthDate"] = "1950-01-01"  # generational gap from p1's 1980-06-15
        pairs = list(generate_raw_pairs(patients, seed=0))
        household = [
            p
            for p in pairs
            if p.strata.get("pair_type") == "special_population"
            and p.strata.get("category") == "multi_generational_household"
        ]
        assert len(household) == 1
        assert household[0].is_true_match is False

    def test_special_population_institutional_pairs_are_true_non_matches(self) -> None:
        patients = [
            _patient("p1", family="Smith"),
            _patient("p2", family="Jones"),
            _patient("p3", family="Lee"),
        ]
        pairs = list(generate_raw_pairs(patients, seed=0))
        institutional = [
            p
            for p in pairs
            if p.strata.get("pair_type") == "special_population"
            and p.strata.get("category") != "multi_generational_household"
        ]
        assert len(institutional) > 0
        assert all(p.is_true_match is False for p in institutional)

    def test_can_disable_session_10_categories(self) -> None:
        patients = [_patient("p1"), _patient("p2", family="Jones", given="Robert")]
        pairs = list(
            generate_raw_pairs(
                patients,
                include_normalization_edge_cases=False,
                include_special_populations=False,
                seed=0,
            )
        )
        pair_types = {p.strata.get("pair_type") for p in pairs}
        assert pair_types <= {"fuzzy_variant", "hard_negative"}

    def test_is_deterministic_given_a_seed(self) -> None:
        patients = [_patient("p1"), _patient("p2", family="Jones", given="Robert")]
        first = list(generate_raw_pairs(patients, seed=42))
        second = list(generate_raw_pairs(patients, seed=42))
        assert [p.pair_id for p in first] == [p.pair_id for p in second]
