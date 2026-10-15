"""Unit tests for text_distance.py."""

from __future__ import annotations

import pytest
from text_distance import levenshtein_distance


@pytest.mark.parametrize(
    "a,b,expected",
    [
        ("", "", 0),
        ("abc", "abc", 0),
        ("abc", "", 3),
        ("", "abcd", 4),
        ("kitten", "sitting", 3),
        ("smith", "smyth", 1),
        ("ab", "ba", 2),
    ],
)
def test_exact_distance_without_a_limit(a, b, expected):
    assert levenshtein_distance(a, b) == expected
    assert levenshtein_distance(b, a) == expected


class TestEarlyAbort:
    def test_returns_the_exact_distance_when_within_the_limit(self):
        assert levenshtein_distance("smith", "smyth", 1) == 1
        assert levenshtein_distance("kitten", "sitting", 3) == 3

    def test_returns_limit_plus_one_once_the_distance_exceeds_the_limit(self):
        assert levenshtein_distance("kitten", "sitting", 2) == 3
        assert levenshtein_distance("abcdef", "uvwxyz", 1) == 2

    def test_a_length_gap_beyond_the_limit_short_circuits(self):
        assert levenshtein_distance("a", "abcdefgh", 2) == 3

    def test_equal_strings_are_zero_even_with_a_zero_limit(self):
        assert levenshtein_distance("same", "same", 0) == 0
        assert levenshtein_distance("same", "sane", 0) == 1
