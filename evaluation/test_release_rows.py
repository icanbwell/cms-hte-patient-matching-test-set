"""Unit tests for release_rows.py: no emitted id may reveal a label."""

from __future__ import annotations

from export_test_dataset import LabeledCaseRecord
from population_cases import PopulationCase, build_population_dataset
from release_rows import (
    CANDIDATE_NAMESPACE,
    QUERY_NAMESPACE,
    candidate_row,
    opaque_id,
    pair_row,
    query_row,
)


def _patient(id_: str, family: str = "Smith", given: str = "Katherine") -> dict:
    return {
        "resourceType": "Patient",
        "id": id_,
        "name": [{"family": family, "given": [given]}],
        "birthDate": "1980-06-15",
    }


def _record(case_id: str, source: dict, target: dict, match: bool) -> LabeledCaseRecord:
    return LabeledCaseRecord(
        case_id=case_id,
        source=source,
        target=target,
        expected_match=match,
        rationale="fuzzy_variant/dob_day",
    )


class TestOpaqueId:
    def test_is_deterministic_and_hides_the_input(self):
        assert opaque_id("12345::dob_day") == opaque_id("12345::dob_day")
        assert "12345" not in opaque_id("12345::dob_day")
        assert opaque_id("a") != opaque_id("b")

    def test_a_namespace_changes_the_id(self):
        raw = "12345"
        ids = {
            opaque_id(raw),
            opaque_id(raw, QUERY_NAMESPACE),
            opaque_id(raw, CANDIDATE_NAMESPACE),
        }
        assert len(ids) == 3


class TestPairRow:
    def test_true_match_source_and_target_ids_differ(self):
        source = _patient("p1")
        row = pair_row(_record("p1::dob_day", source, dict(source), True))
        assert row["source"]["id"] != row["target"]["id"]

    def test_source_id_is_stable_across_cases_and_target_id_is_per_case(self):
        source = _patient("p1")
        a = pair_row(_record("p1::a", source, dict(source), True))
        b = pair_row(_record("p1::b", source, _patient("p2"), False))
        assert a["source"]["id"] == b["source"]["id"] == opaque_id("p1")
        assert a["target"]["id"] != b["target"]["id"]

    def test_does_not_mutate_the_input(self):
        source = _patient("p1")
        pair_row(_record("c", source, dict(source), True))
        assert source["id"] == "p1"


class TestPopulationRows:
    def test_candidate_row_id_matches_its_patient_id_and_hides_the_raw_id(self):
        row = candidate_row("q::dob_day", _patient("q"))
        assert (
            row["id"]
            == row["patient"]["id"]
            == opaque_id("q::dob_day", CANDIDATE_NAMESPACE)
        )
        assert "::" not in row["id"]

    def test_query_row_maps_every_reference_consistently(self):
        case = PopulationCase(
            query_id="q",
            query_patient=_patient("q"),
            candidate_ids=["q::dob_day", "other"],
            expected_match_ids=["q::dob_day"],
            rationale="population/fuzzy_variant",
        )
        row = query_row(case)
        assert row["query"]["id"] == row["query_id"] == opaque_id("q", QUERY_NAMESPACE)
        assert row["candidate_ids"] == [
            opaque_id("q::dob_day", CANDIDATE_NAMESPACE),
            opaque_id("other", CANDIDATE_NAMESPACE),
        ]
        assert row["expected_match_ids"] == [
            opaque_id("q::dob_day", CANDIDATE_NAMESPACE)
        ]


def test_a_candidate_never_has_the_id_of_a_query_even_for_the_same_record():
    # "other" is both a query (its own row) and a non-matching candidate in "q"'s
    # pool: with one shared hash that coincidence labeled every non-match.
    q = PopulationCase("q", _patient("q"), ["q::dob_day", "other"], ["q::dob_day"], "r")
    other = PopulationCase("other", _patient("other"), ["q"], [], "r")
    query_ids = {query_row(q)["query_id"], query_row(other)["query_id"]}
    candidate_ids = {
        i for row in (query_row(q), query_row(other)) for i in row["candidate_ids"]
    }
    candidate_ids.add(candidate_row("other", _patient("other"))["id"])
    assert query_ids.isdisjoint(candidate_ids)


def test_true_matches_are_not_listed_first_in_the_pool():
    patients = [
        _patient(f"p{i}", family=f"Name{i}", given=f"Given{i}") for i in range(30)
    ]
    dataset = build_population_dataset(patients, pool_size=20, seed=0)
    first_is_match = [
        case.candidate_ids[0] in case.expected_match_ids for case in dataset.cases
    ]
    assert not all(first_is_match)
    assert any(
        case.candidate_ids[: len(case.expected_match_ids)] != case.expected_match_ids
        for case in dataset.cases
    )
