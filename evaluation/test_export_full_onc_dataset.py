"""Unit tests for export_full_onc_dataset.py (BAI-1074).

The real ONC shards are replaced with two tiny in-memory "shards" so the
one-shard-at-a-time loop, JSONL shape, and cross-shard accumulation are
exercised without loading ~1M records.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import export_full_onc_dataset as full
import pytest


def _patient(id_: str, family: str, given: str, zip_code: str, dob: str):
    return {
        "resourceType": "Patient",
        "id": id_,
        "name": [{"family": family, "given": [given]}],
        "birthDate": dob,
        "telecom": [],
        "address": [
            {"line": ["1 Main St"], "city": "NY", "state": "NY", "postalCode": zip_code}
        ],
        "identifier": [],
    }


@pytest.fixture
def fake_shards(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> List[Path]:
    shards = [tmp_path / "a.csv", tmp_path / "b.csv"]
    by_shard: Dict[Path, list] = {
        shards[0]: [
            _patient("a1", "Smith", "Katherine", "10001", "1980-06-15"),
            _patient("a2", "Jones", "Robert", "20002", "1975-02-03"),
        ],
        shards[1]: [
            _patient("b1", "Garcia", "Maria", "30003", "1990-09-09"),
            _patient("b2", "Nguyen", "Linh", "40004", "1985-12-25"),
        ],
    }
    loaded: List[List[Path]] = []

    def fake_load(paths: List[Path]):
        loaded.append(paths)
        return by_shard[paths[0]]

    monkeypatch.setattr(full, "_all_shards", lambda: shards)
    monkeypatch.setattr(full, "load_onc_patients", fake_load)
    monkeypatch.setattr(full, "_loaded_calls", loaded, raising=False)
    return shards


def _read(path: Path) -> list:
    return [json.loads(line) for line in path.read_text().splitlines()]


class TestExportFullTestDataset:
    def test_loads_one_shard_at_a_time(self, fake_shards, tmp_path):
        full.export_full_test_dataset(tmp_path / "out.jsonl")
        assert full._loaded_calls == [[s] for s in fake_shards]  # type: ignore[attr-defined]

    def test_writes_cases_from_every_shard_with_expected_fields(
        self, fake_shards, tmp_path
    ):
        out = tmp_path / "out.jsonl"
        full.export_full_test_dataset(out)
        rows = _read(out)
        assert {"case_id", "expected_match", "rationale", "frequency"} <= set(rows[0])
        case_ids = " ".join(r["case_id"] for r in rows)
        assert "a1" in case_ids and "b1" in case_ids

    def test_skips_name_collision_negatives(self, fake_shards, tmp_path, monkeypatch):
        seen = []
        real = full.build_test_case_records

        def spy(patients, **kwargs):
            seen.append(kwargs.get("include_name_collision_negatives"))
            return real(patients, **kwargs)

        monkeypatch.setattr(full, "build_test_case_records", spy)
        full.export_full_test_dataset(tmp_path / "out.jsonl")
        assert seen == [False, False]


class TestExportFullPopulationDataset:
    def test_one_query_per_patient_across_shards(self, fake_shards, tmp_path):
        cands, queries = tmp_path / "c.jsonl", tmp_path / "q.jsonl"
        full.export_full_population_dataset(cands, queries, pool_size=40)
        assert {r["query_id"] for r in _read(queries)} == {"a1", "a2", "b1", "b2"}

    def test_every_referenced_candidate_is_written(self, fake_shards, tmp_path):
        cands, queries = tmp_path / "c.jsonl", tmp_path / "q.jsonl"
        full.export_full_population_dataset(cands, queries, pool_size=40)
        candidate_ids = {r["id"] for r in _read(cands)}
        for row in _read(queries):
            assert set(row["candidate_ids"]) <= candidate_ids
            assert set(row["expected_match_ids"]) <= set(row["candidate_ids"])


def test_default_paths_do_not_overwrite_committed_sample_files():
    names = {
        full.DEFAULT_OUTPUT_PATH.name,
        full.DEFAULT_CANDIDATES_PATH.name,
        full.DEFAULT_QUERIES_PATH.name,
    }
    assert names.isdisjoint(
        {
            "sample_labeled_pairs.jsonl",
            "population_candidates.jsonl",
            "population_queries.jsonl",
        }
    )
