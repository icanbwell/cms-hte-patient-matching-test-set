"""Unit tests for the ONC self-match baseline wiring (session 3).

Depends on numpy transitively via rule_eval - see test_rule_eval.py's module
docstring for why these tests importorskip("numpy") rather than failing hard.
"""

from __future__ import annotations

import pytest

pytest.importorskip("numpy")

from onc_baseline import (
    MASKING_SCENARIOS,
    build_onc_pairs,
    current_engine_matcher,
)
from onc_loader import _decode_sas_date


class TestOncTransform:
    @pytest.mark.parametrize(
        "raw_offset,expected_iso",
        [
            ("2", "1900-01-01"),  # offset 0 after the -2 correction
            ("367", "1901-01-01"),  # 365 days later (1900 is not a leap year)
            ("36527", "2000-01-02"),
        ],
    )
    def test_decode_sas_date_boundaries(
        self, raw_offset: str, expected_iso: str
    ) -> None:
        assert _decode_sas_date(raw_offset) == expected_iso


class TestEvaluatePairEquivalence:
    """MatchingEngine.evaluate_pair should agree with match()'s decision on this simple,
    single-valued-field case. This is a consistency check between the two decision paths,
    not a refactor-equivalence proof - see the known blocking-vs-full-value-set limitation
    noted on evaluate_pair()'s docstring."""

    def test_evaluate_pair_agrees_with_match_for_matching_pair(self) -> None:
        from patient_matching.matching.field_extractor import FieldExtractor
        from patient_matching.matching.in_memory_backend import InMemoryBackend
        from patient_matching.matching.matching_engine import MatchingEngine

        def _patient(mbi: str) -> dict:
            return {
                "resourceType": "Patient",
                "name": [{"family": "smith", "given": ["john"]}],
                "birthDate": "1980-01-01",
                "telecom": [],
                "address": [],
                "identifier": [
                    {"system": "http://hl7.org/fhir/sid/us-mbi", "value": mbi}
                ],
            }

        candidate = _patient("1abc2de3f45")
        candidate["id"] = "cand-1"
        backend = InMemoryBackend([candidate])
        engine = MatchingEngine(backend=backend)
        query = _patient("1abc2de3f45")

        match_result = engine.match(query)
        extractor = FieldExtractor()
        pairwise_result = engine.evaluate_pair(
            extractor.extract(query), extractor.extract(candidate)
        )

        assert (match_result.outcome.value == "match") == pairwise_result

    def test_current_engine_matcher_matches_evaluate_pair(self) -> None:
        """current_engine_matcher is a thin adapter - confirm it delegates correctly.

        First+last+DOB alone satisfies no Table 2 rule (every rule needs a 4th
        identifying field - street line, phone, email, SSN, or similar); add a
        phone number so this pair actually satisfies rule 02.
        """
        from patient_matching.matching.field_extractor import FieldExtractor

        extractor = FieldExtractor()
        patient = {
            "resourceType": "Patient",
            "name": [{"family": "smith", "given": ["john"]}],
            "birthDate": "1980-01-01",
            "telecom": [{"system": "phone", "value": "+15035551234"}],
            "address": [],
            "identifier": [],
        }
        fields = extractor.extract(patient)
        assert current_engine_matcher({"query": fields, "candidate": fields}) is True


class TestBuildOncPairs:
    def test_true_match_pairs_outnumber_or_equal_masking_scenarios(self) -> None:
        patients = [
            {
                "id": "p1",
                "name": [{"family": "smith", "given": ["john"]}],
                "birthDate": "1980-01-01",
                "telecom": [],
                "address": [],
                "identifier": [],
            }
        ]
        pairs = build_onc_pairs(patients, n_negative_samples=0)
        true_pairs = [p for p in pairs if p.is_true_match]
        assert len(true_pairs) == len(MASKING_SCENARIOS)

    def test_negative_sample_count_is_respected(self) -> None:
        patients = [
            {
                "id": f"p{i}",
                "name": [{"family": "smith", "given": ["john"]}],
                "birthDate": "1980-01-01",
                "telecom": [],
                "address": [],
                "identifier": [],
            }
            for i in range(10)
        ]
        pairs = build_onc_pairs(patients, n_negative_samples=5, seed=0)
        negative_pairs = [p for p in pairs if not p.is_true_match]
        assert len(negative_pairs) == 5

    def test_negative_pairs_never_pair_a_record_with_itself(self) -> None:
        patients = [
            {
                "id": f"p{i}",
                "name": [{"family": "smith", "given": ["john"]}],
                "birthDate": "1980-01-01",
                "telecom": [],
                "address": [],
                "identifier": [],
            }
            for i in range(10)
        ]
        pairs = build_onc_pairs(patients, n_negative_samples=8, seed=1)
        for p in pairs:
            if not p.is_true_match:
                assert p.pair_id is not None
                q_id, c_id = p.pair_id.split("::")
                assert q_id != c_id

    def test_true_match_pair_id_encodes_record_and_scenario(self) -> None:
        patients = [
            {
                "id": "p1",
                "name": [{"family": "smith", "given": ["john"]}],
                "birthDate": "1980-01-01",
                "telecom": [{"system": "phone", "value": "5035551234"}],
                "address": [],
                "identifier": [],
            }
        ]
        pairs = build_onc_pairs(patients, n_negative_samples=0)
        pair_ids = {p.pair_id for p in pairs}
        assert pair_ids == {"p1::none", "p1::drop_email_phone"}
