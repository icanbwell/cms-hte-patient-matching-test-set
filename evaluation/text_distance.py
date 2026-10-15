"""Edit distance shared by the generators and the same-person guards.

A leaf module (no repo imports) so identity_guard, hard_negatives and
near_miss can all use one implementation without an import cycle."""

from __future__ import annotations


def levenshtein_distance(a: str, b: str, max_distance: int | None = None) -> int:
    """Standard edit distance, stdlib-only - session 13 confirmed rapidfuzz
    is not an actual dependency of this repo (cited only in a docstring,
    never imported), so this avoids adding one just for this.

    `max_distance`, if given, aborts as soon as every entry in the current
    row exceeds it (the true distance can only grow from there), returning
    `max_distance + 1` rather than the exact distance - callers that only
    need a "<= max_distance?" answer avoid the full O(len(a)*len(b)) matrix
    on pairs that are obviously too far apart."""
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    if max_distance is not None and abs(len(a) - len(b)) > max_distance:
        return max_distance + 1
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            current[j] = min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + cost,
            )
        if max_distance is not None and min(current) > max_distance:
            return max_distance + 1
        previous = current
    return previous[-1]
