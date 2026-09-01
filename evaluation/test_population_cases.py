"""Unit tests for population_cases.py (session 12)."""

from __future__ import annotations

from population_cases import build_population_dataset


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


class TestBuildPopulationDataset:
    def test_every_case_query_id_maps_to_input_patient(self):
        patients = [_patient("p1"), _patient("p2", family="Jones", given="Robert")]
        dataset = build_population_dataset(patients, seed=0)
        assert {c.query_id for c in dataset.cases} == {"p1", "p2"}

    def test_expected_match_ids_is_subset_of_candidate_ids(self):
        patients = [_patient("p1"), _patient("p2", family="Jones", given="Robert")]
        dataset = build_population_dataset(patients, seed=0)
        for case in dataset.cases:
            assert set(case.expected_match_ids) <= set(case.candidate_ids)

    def test_fuzzy_variants_produce_a_non_empty_expected_match_set(self):
        patients = [_patient("p1")]
        dataset = build_population_dataset(
            patients, n_fuzzy_variants_per_patient=1, seed=0
        )
        (case,) = dataset.cases
        assert case.expected_match_ids

    def test_no_generated_variants_produces_an_empty_expected_match_set(self):
        """The current Doc calls this out explicitly as a real case ('possibly
        empty'), not an edge case to special-case away - it must actually be
        reachable, not just documented."""
        patients = [_patient("p1"), _patient("p2", family="Jones", given="Robert")]
        dataset = build_population_dataset(
            patients,
            n_fuzzy_variants_per_patient=0,
            include_normalization_edge_cases=False,
            include_special_populations=False,
            seed=0,
        )
        case = next(c for c in dataset.cases if c.query_id == "p1")
        assert case.expected_match_ids == []
        # The pool is still non-empty - queried against a real population,
        # just one with no true match in it (p2 fills it as a distractor).
        assert case.candidate_ids

    def test_hard_negative_decoys_never_appear_as_expected_matches(self):
        # Same ZIP+DOB, distinct family names -> one mined hard negative.
        patients = [_patient("p1", family="Smith"), _patient("p2", family="Jones")]
        dataset = build_population_dataset(
            patients,
            n_fuzzy_variants_per_patient=0,
            include_normalization_edge_cases=False,
            seed=0,
        )
        by_id = {c.query_id: c for c in dataset.cases}
        assert "p2" in by_id["p1"].candidate_ids
        assert "p2" not in by_id["p1"].expected_match_ids

    def test_candidate_pool_is_capped_at_pool_size(self):
        patients = [_patient(f"p{i}", given=f"Name{i}") for i in range(60)]
        dataset = build_population_dataset(
            patients, pool_size=10, n_fuzzy_variants_per_patient=1, seed=0
        )
        for case in dataset.cases:
            assert len(case.candidate_ids) <= 10

    def test_true_matches_are_never_dropped_to_fit_pool_size(self):
        patients = [_patient(f"p{i}", given=f"Name{i}") for i in range(60)]
        dataset = build_population_dataset(
            patients, pool_size=1, n_fuzzy_variants_per_patient=1, seed=0
        )
        for case in dataset.cases:
            assert set(case.expected_match_ids) <= set(case.candidate_ids)

    def test_candidates_registry_contains_every_referenced_id(self):
        patients = [_patient("p1"), _patient("p2", family="Jones", given="Robert")]
        dataset = build_population_dataset(patients, seed=0)
        for case in dataset.cases:
            for candidate_id in case.candidate_ids:
                assert candidate_id in dataset.candidates

    def test_is_deterministic_given_a_seed(self):
        patients = [_patient("p1"), _patient("p2", family="Jones", given="Robert")]
        first = build_population_dataset(patients, seed=42)
        second = build_population_dataset(patients, seed=42)
        assert [(c.query_id, c.candidate_ids) for c in first.cases] == [
            (c.query_id, c.candidate_ids) for c in second.cases
        ]

    def test_institutional_candidate_ids_are_namespaced_not_bare_enterprise_ids(self):
        """An institutional-negative candidate's body has a fabricated address
        overwritten on top of a real EnterpriseID - it must not collide, in
        the shared candidate registry, with that same person's plain,
        address-intact record (see module docstring's 'Known simplification')."""
        patients = [
            _patient("p1", family="Smith"),
            _patient("p2", family="Jones"),
            _patient("p3", family="Lee"),
        ]
        dataset = build_population_dataset(
            patients,
            n_fuzzy_variants_per_patient=0,
            include_normalization_edge_cases=False,
            seed=0,
        )
        institutional_ids = [
            cid for cid in dataset.candidates if "::institutional::" in cid
        ]
        assert institutional_ids
        for cid in institutional_ids:
            plain_id = cid.split("::institutional::")[0]
            assert (
                dataset.candidates[cid]["address"]
                != dataset.candidates[plain_id]["address"]
            )
