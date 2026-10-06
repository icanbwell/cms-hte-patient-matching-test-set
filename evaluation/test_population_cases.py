"""Unit tests for population_cases.py (session 12)."""

from __future__ import annotations

from drift_profile import DriftProfile
from labeled_pairs import generate_raw_pairs
from population_cases import build_population_dataset
from scenarios import REGISTRY
from support_patients import drift_donors, drift_population


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
            include_compound_variants=False,
            profile=DriftProfile(rates={}),
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


class TestPopulationLabelValidity:
    def test_topup_never_adds_a_possible_same_person_as_a_decoy(self):
        patients = [
            _patient("p1"),
            _patient("p2"),
            _patient("p3", family="Jones", given="Robert"),
        ]
        # p2 is the same person as p1 (same first+family+DOB) under another id.
        dataset = build_population_dataset(patients, pool_size=10, seed=0)
        case = next(c for c in dataset.cases if c.query_id == "p1")
        assert "p2" not in case.candidate_ids

    def test_constructed_household_candidates_are_namespaced(self):
        elder = _patient("e1", family="Rivera", given="Rosa")
        elder["birthDate"] = "1950-03-01"
        younger = _patient("y1", family="Rivera", given="Luis")
        younger["birthDate"] = "1988-07-14"
        younger["address"] = [
            {"line": ["9 Elm St"], "city": "LA", "state": "CA", "postalCode": "90001"}
        ]
        dataset = build_population_dataset([elder, younger], pool_size=30, seed=0)
        case = next(c for c in dataset.cases if c.query_id == "e1")
        assert "y1::household::constructed" in case.candidate_ids
        assert "y1::household::constructed" not in case.expected_match_ids
        assert (
            dataset.candidates["y1::household::constructed"]["address"]
            == elder["address"]
        )


class TestDriftScenariosPopulationTier:
    def _dataset(self, **kwargs):
        everything = DriftProfile(rates={n: 1.0 for n in REGISTRY})
        return build_population_dataset(
            drift_population(),
            pool_size=60,
            donors=drift_donors(),
            profile=everything,
            seed=0,
            **kwargs,
        )

    def test_every_registry_scenario_appears_as_an_expected_match(self):
        dataset = self._dataset()
        suffixes = {
            cid.split("::", 1)[1]
            for case in dataset.cases
            for cid in case.expected_match_ids
        }
        for name in REGISTRY:
            assert name in suffixes, name

    def test_scenario_variants_match_the_per_provision_tier(self):
        patients = drift_population()
        everything = DriftProfile(rates={n: 1.0 for n in REGISTRY})
        dataset = build_population_dataset(
            patients, pool_size=60, donors=drift_donors(), profile=everything, seed=0
        )
        pairs = {
            p.pair_id: p.candidate_patient
            for p in generate_raw_pairs(
                patients, donors=drift_donors(), profile=everything, seed=0
            )
            if p.strata["pair_type"] in REGISTRY
        }
        assert pairs
        for pair_id, variant in pairs.items():
            assert dataset.candidates[pair_id] == variant

    def test_population_includes_compound_sibling_and_name_collision_categories(self):
        patients = drift_population()
        sibling_a = drift_population()[0]
        sibling_b = dict(
            sibling_a,
            id="sib",
            birthDate="1951-02-02",
            name=[{"family": "Smith", "given": ["Other"]}],
            identifier=[],
        )
        sibling_b["address"] = sibling_a["address"]
        collision = dict(
            patients[1],
            id="col",
            name=[{"family": "Smyth", "given": ["Given0"]}],
            birthDate="1999-09-09",
            identifier=[],
        )
        collision["address"] = [
            {"line": ["5 Far Rd"], "city": "LA", "state": "CA", "postalCode": "90001"}
        ]
        dataset = build_population_dataset(
            [*patients, sibling_b, collision],
            pool_size=80,
            profile=DriftProfile(rates={}),
            seed=0,
        )
        categories = set()
        for case in dataset.cases:
            categories |= set(case.rationale.split("/", 1)[1].split("+"))
        assert {
            "compound_variant",
            "sibling_negative",
            "name_collision_negative",
        } <= categories

    def test_decoy_categories_are_never_expected_matches(self):
        dataset = self._dataset()
        for case in dataset.cases:
            for cid in case.expected_match_ids:
                assert "::" in cid  # only generated variants are positives

    def test_compound_variants_can_be_switched_off(self):
        dataset = self._dataset(include_compound_variants=False)
        assert not [
            cid
            for case in dataset.cases
            for cid in case.candidate_ids
            if "::compound::" in cid
        ]

    def test_existing_variant_streams_are_unchanged_by_the_new_scenarios(self):
        patients = drift_population()
        base = build_population_dataset(
            patients, pool_size=60, profile=DriftProfile(rates={}), seed=0
        )
        more = build_population_dataset(
            patients,
            pool_size=60,
            donors=drift_donors(),
            profile=DriftProfile(),
            seed=0,
        )
        for pid in ("d0", "d1"):
            old = next(c for c in base.cases if c.query_id == pid)
            new = next(c for c in more.cases if c.query_id == pid)
            for cid in old.expected_match_ids:
                assert cid in new.expected_match_ids
                assert base.candidates[cid] == more.candidates[cid]


class TestHouseholdMemberDecoys:
    def test_household_members_are_decoys_in_each_others_pools_never_matches(self):
        a, b, c = drift_population()[:3]
        dataset = build_population_dataset(
            [a, b, c],
            pool_size=30,
            profile=DriftProfile(rates={}),
            households=[[a["id"], b["id"]]],
            seed=0,
        )
        pools = {case.query_id: case for case in dataset.cases}
        assert b["id"] in pools[a["id"]].candidate_ids
        assert a["id"] in pools[b["id"]].candidate_ids
        assert b["id"] not in pools[a["id"]].expected_match_ids
        assert "household_member_negative" in pools[a["id"]].rationale
        assert "household_member_negative" not in pools[c["id"]].rationale

    def test_same_person_members_and_unknown_ids_are_ignored(self):
        a, b = drift_population()[:2]
        b["name"], b["birthDate"] = a["name"], a["birthDate"]
        dataset = build_population_dataset(
            [a, b],
            pool_size=30,
            profile=DriftProfile(rates={}),
            households=[[a["id"], "missing", b["id"]]],
            seed=0,
        )
        case = next(c for c in dataset.cases if c.query_id == a["id"])
        assert "household_member_negative" not in case.rationale

    def test_households_follow_include_special_populations(self):
        a, b = drift_population()[:2]
        dataset = build_population_dataset(
            [a, b],
            pool_size=30,
            profile=DriftProfile(rates={}),
            households=[[a["id"], b["id"]]],
            include_special_populations=False,
            seed=0,
        )
        assert all(
            "household_member_negative" not in c.rationale for c in dataset.cases
        )


class TestDecoyCategories:
    def test_a_decoy_in_two_categories_is_pooled_once_and_credited_to_both(self):
        elder = _patient("e1", family="Rivera", given="Rosa")
        sibling = _patient("s1", family="Rivera", given="Luis")
        elder["birthDate"], sibling["birthDate"] = "1990-03-01", "1991-07-14"
        dataset = build_population_dataset(
            [elder, sibling],
            pool_size=30,
            profile=DriftProfile(rates={}),
            households=[["e1", "s1"]],
            include_compound_variants=False,
            seed=0,
        )
        case = next(c for c in dataset.cases if c.query_id == "e1")
        assert case.candidate_ids.count("s1") == 1
        assert "household_member_negative" in case.rationale
        assert "sibling_negative" in case.rationale
