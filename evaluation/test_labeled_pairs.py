"""Unit tests for labeled_pairs.py (session 9).

No numpy dependency here (session 13 dropped labeled_pairs.py's use of the
reference matching engine and rule_eval entirely - generate_raw_pairs() only touches
hard_negatives.py/mutations.py/normalization_edge_cases.py/
special_populations.py, none of which need numpy), so these always run.
"""

from __future__ import annotations

from labeled_pairs import generate_raw_pairs
from mutations import SSN_SYSTEM, count_changed_fields


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


def _household_pair():
    """A real elder and a younger same-surname record living at a different street."""
    elder = _patient("p1", family="Rivera", given="Rosa")
    elder["birthDate"] = "1950-03-01"
    younger = _patient("p2", family="Rivera", given="Luis")
    younger["birthDate"] = "1988-07-14"
    younger["address"] = [
        {"line": ["9 Elm St"], "city": "LA", "state": "CA", "postalCode": "90001"}
    ]
    return elder, younger


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
                include_compound_variants=False,
                include_ssn_dropped=False,
                include_marriage_variant=False,
                include_phone_variant=False,
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

    def test_is_deterministic_given_a_seed(self) -> None:
        patients = [_patient("p1"), _patient("p2", family="Jones", given="Robert")]
        first = list(generate_raw_pairs(patients, seed=42))
        second = list(generate_raw_pairs(patients, seed=42))
        assert [p.pair_id for p in first] == [p.pair_id for p in second]

    def test_generate_raw_pairs_includes_all_new_pair_types(self) -> None:
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
                    {
                        "line": ["1 Main St"],
                        "city": "NY",
                        "state": "NY",
                        "postalCode": "10001",
                    }
                ],
                "identifier": [{"system": SSN_SYSTEM, "value": "123-45-6789"}],
            },
            _patient(
                "p2", family="Rivera", given="Ana"
            ),  # default zip 10001, dob 1980-06-15
            {
                **_patient("p3", family="Rivera", given="Luis"),
                "birthDate": "1981-01-01",  # 1-year gap from p2 -> sibling_negative, not household
            },
            {
                **_patient("p4", family="Smyth", given="Katherine"),
                "birthDate": "2001-02-02",
                "address": [
                    {
                        "line": ["9 Elm St"],
                        "city": "LA",
                        "state": "CA",
                        "postalCode": "70007",
                    }
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

    def test_can_disable_all_new_pair_types(self) -> None:
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

    def test_new_true_match_categories_never_emit_a_byte_identical_pair(self) -> None:
        # No SSN, no second name entry (no maiden-name proxy), only one phone
        # number - every one of the four new no-op-capable mutators degenerates
        # on this record, so none of their pairs should be emitted at all.
        patient = {
            "resourceType": "Patient",
            "id": "p1",
            "name": [{"family": "Smith", "given": ["Katherine"]}],
            "birthDate": "1980-06-15",
            "telecom": [{"system": "phone", "value": "555-000-1111"}],
            "address": [
                {
                    "line": ["1 Main St"],
                    "city": "NY",
                    "state": "NY",
                    "postalCode": "10001",
                }
            ],
            "identifier": [],
        }
        pairs = list(generate_raw_pairs([patient], seed=0))
        degenerate_types = {
            p.strata["pair_type"]
            for p in pairs
            if p.strata.get("pair_type")
            in {"ssn_dropped", "marriage_variant", "phone_variant"}
        }
        assert degenerate_types == set()

    def test_no_true_match_pair_has_an_identical_query_and_candidate(self) -> None:
        patients = [_patient("p1"), _patient("p2", family="Jones", given="Robert")]
        pairs = list(generate_raw_pairs(patients, seed=0))
        for pair in pairs:
            if pair.is_true_match:
                assert pair.query_patient != pair.candidate_patient, pair.pair_id

    def test_compound_variant_is_never_emitted_with_fewer_changed_fields_than_requested(
        self,
    ) -> None:
        # An empty given name (a real, common ONC shape) makes the "given"
        # field group a total no-op for every one of its mutators - the
        # compound variant must not be emitted labeled as a 2-field change
        # when only birthDate or family actually changed.
        patient = {
            "resourceType": "Patient",
            "id": "p1",
            "name": [{"family": "Smith", "given": [""]}],
            "birthDate": "1980-06-15",
            "telecom": [],
            "address": [
                {
                    "line": ["1 Main St"],
                    "city": "NY",
                    "state": "NY",
                    "postalCode": "10001",
                }
            ],
            "identifier": [],
        }
        pairs = list(
            generate_raw_pairs(
                [patient],
                include_normalization_edge_cases=False,
                include_ssn_dropped=False,
                include_marriage_variant=False,
                include_phone_variant=False,
                n_compound_mutations=3,  # forces the "given" group to be drawn
                seed=0,
            )
        )
        compound = [p for p in pairs if p.strata.get("pair_type") == "compound_variant"]
        for pair in compound:
            changed = count_changed_fields(pair.query_patient, pair.candidate_patient)
            assert changed >= 3, (pair.pair_id, changed)

    def test_constructed_household_pairs_share_the_elders_address(self) -> None:
        elder, younger = _household_pair()
        pairs = list(generate_raw_pairs([elder, younger], seed=0))
        constructed = [
            p for p in pairs if p.strata.get("address_source") == "constructed"
        ]
        assert len(constructed) == 1
        assert constructed[0].is_true_match is False
        assert constructed[0].candidate_patient["address"] == elder["address"]
        assert constructed[0].pair_id.endswith("::household_constructed")

    def test_household_constructed_max_zero_disables_the_constructed_path(self) -> None:
        elder, younger = _household_pair()
        pairs = list(
            generate_raw_pairs([elder, younger], seed=0, household_constructed_max=0)
        )
        assert not [p for p in pairs if p.strata.get("address_source")]
