"""Tests for the shared `notebooks/_sql_safety.py` helpers.

Moved out of `test_fhir_match_data_source.py` when the helpers were deduplicated out of
`fhir_match_data_source.py` and a sibling member-matching-analysis notebook into this shared
module (PR #22 review) - both notebooks now import from here, so the contract is tested
once instead of per-notebook.
"""

from __future__ import annotations

import pytest

from notebooks._sql_safety import _sql_string_literal, _validate_sql_identifier


class TestSqlSafetyHelpers:
    @pytest.mark.parametrize(
        "identifier,should_raise",
        [
            ("bronze.fhir_lake.patient_4_0_0", False),
            ("bronze", False),
            ("bronze; DROP TABLE x", True),
            ("bronze.fhir_lake.patient_4_0_0--", True),
            ("", True),
        ],
    )
    def test_validate_sql_identifier(self, identifier, should_raise):
        if should_raise:
            with pytest.raises(ValueError):
                _validate_sql_identifier(identifier)
        else:
            assert _validate_sql_identifier(identifier) == identifier

    def test_sql_string_literal_escapes_quotes(self):
        assert _sql_string_literal("o'brien") == "'o''brien'"
