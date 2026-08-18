"""Shared SQL-safety helpers for `notebooks/` Databricks notebooks.

Widget values (table/schema/catalog names, client ids, etc.) get interpolated into
`spark.sql()` f-strings across multiple notebooks in this directory. Centralized here
(rather than copied per-notebook) so a future fix to the escaping/validation logic only
needs to be made once - see PR #22 review discussion for why the prior per-notebook
copies were consolidated.
"""

from __future__ import annotations

import re

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*$")


def _validate_sql_identifier(name: str) -> str:
    """Ensure `name` is a bare dotted identifier (letters/digits/underscore/dot only)."""
    if not name or not _IDENTIFIER_RE.match(name):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return name


def _sql_string_literal(value: str) -> str:
    """Escape `value` for safe use as a single-quoted SQL string literal."""
    return "'" + str(value).replace("'", "''") + "'"
