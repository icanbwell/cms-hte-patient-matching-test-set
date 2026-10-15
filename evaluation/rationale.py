"""Rationale-string helpers shared by the generators and the audit."""

from __future__ import annotations

import re


def category_of(rationale: str) -> str:
    """'sibling_negative (age_gap_years=1)' -> 'sibling_negative'; 'fuzzy_variant/x' -> 'fuzzy_variant'."""
    return re.split(r"[/ (]", rationale, maxsplit=1)[0]
