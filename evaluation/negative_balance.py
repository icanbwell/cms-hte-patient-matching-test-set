"""Rebalance the pairwise tier toward a target negative share (session 16).

An "always match" answer scores F1 = 2p/(1+p) on a tier that is p positive, so
a 96%-positive tier cannot separate algorithms. Positives are cheap to
regenerate and negatives are scarce, so this drops *positives* (never
negatives), proportionally by category, keeping at least `min_per_category`
of each category (or all of a smaller one). If negatives are too few to reach
the target once those floors apply, the share is left below target: the
audit's `negative_share` gate reports it rather than this function raising.
"""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Dict, List, Set

from export_test_dataset import LabeledCaseRecord
from rationale import category_of


def rebalance_negatives(
    records: List[LabeledCaseRecord],
    *,
    target_share: float,
    seed: int,
    min_per_category: int = 25,
) -> List[LabeledCaseRecord]:
    if not 0.0 < target_share < 1.0:
        raise ValueError(f"target_share must be in (0, 1), got {target_share}")
    n_negatives = sum(1 for r in records if not r.expected_match)
    positives = [i for i, r in enumerate(records) if r.expected_match]
    budget = int(n_negatives * (1 - target_share) / target_share)
    if len(positives) <= budget:
        return list(records)
    by_category: Dict[str, List[int]] = defaultdict(list)
    for index in positives:
        by_category[category_of(records[index].rationale)].append(index)
    floors = {c: min(len(g), min_per_category) for c, g in by_category.items()}
    keep = {
        c: min(len(g), max(floors[c], round(len(g) * budget / len(positives))))
        for c, g in by_category.items()
    }
    excess = sum(keep.values()) - budget
    while excess > 0:
        reducible = [c for c in keep if keep[c] > floors[c]]
        if not reducible:
            break
        biggest = max(reducible, key=lambda c: (keep[c], c))
        keep[biggest] -= 1
        excess -= 1
    dropped: Set[int] = set()
    for category, group in by_category.items():
        rng = random.Random(f"{seed}:rebalance:{category}")
        kept = set(rng.sample(group, keep[category]))
        dropped.update(i for i in group if i not in kept)
    return [r for i, r in enumerate(records) if i not in dropped]
