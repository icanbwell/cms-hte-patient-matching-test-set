"""Unit tests for export_population_dataset.py (session 12)."""

from __future__ import annotations

import json

from export_population_dataset import write_population_dataset
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


class TestWritePopulationDataset:
    def test_round_trips_every_referenced_candidate_id(self, tmp_path):
        patients = [_patient("p1"), _patient("p2", family="Jones", given="Robert")]
        dataset = build_population_dataset(patients, seed=0)

        candidates_path = tmp_path / "population_candidates.jsonl"
        queries_path = tmp_path / "population_queries.jsonl"
        write_population_dataset(dataset, candidates_path, queries_path)

        candidate_ids = {
            json.loads(line)["id"] for line in candidates_path.read_text().splitlines()
        }
        for line in queries_path.read_text().splitlines():
            row = json.loads(line)
            for candidate_id in row["candidate_ids"]:
                assert candidate_id in candidate_ids
            assert set(row["expected_match_ids"]) <= set(row["candidate_ids"])

    def test_writes_one_query_row_per_input_patient(self, tmp_path):
        patients = [_patient("p1"), _patient("p2", family="Jones", given="Robert")]
        dataset = build_population_dataset(patients, seed=0)

        queries_path = tmp_path / "population_queries.jsonl"
        write_population_dataset(
            dataset, tmp_path / "population_candidates.jsonl", queries_path
        )

        rows = [json.loads(line) for line in queries_path.read_text().splitlines()]
        assert {row["query_id"] for row in rows} == {"p1", "p2"}

    def test_creates_parent_directories_if_missing(self, tmp_path):
        dataset = build_population_dataset([_patient("p1")], seed=0)
        candidates_path = tmp_path / "nested" / "candidates.jsonl"
        queries_path = tmp_path / "nested" / "queries.jsonl"
        write_population_dataset(dataset, candidates_path, queries_path)
        assert candidates_path.exists()
        assert queries_path.exists()
