"""Dataset audit: label-validity, realism metrics, and naive-baseline results.

Run from the repo root:

    PYTHONPATH=. uv run python evaluation/audit.py
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Sequence, Tuple

from identity_guard import is_possible_same_person, normalize_phone, normalize_token
from naive_baselines import (
    BASELINES,
    MULTI_FIELD_BASELINE_NAME,
    SINGLE_FIELD_BASELINES,
    pair_features,
)
from rule_eval import LabeledPair, evaluate

Patient = Dict[str, Any]
Row = Dict[str, Any]

CASES_DIR = Path(__file__).parent / "cases"
PAIRS_PATH = CASES_DIR / "sample_labeled_pairs.jsonl"
QUERIES_PATH = CASES_DIR / "population_queries.jsonl"
CANDIDATES_PATH = CASES_DIR / "population_candidates.jsonl"

# Fixed (not date.today()) so the report is deterministic. See Open Question 5.
AS_OF = date(2026, 1, 1)

AGE_BANDS: Tuple[Tuple[str, int, int], ...] = (
    ("0-17", 0, 18),
    ("18-64", 18, 65),
    ("65-84", 65, 85),
    ("85+", 85, 200),
)


def read_jsonl(path: Path) -> List[Row]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def category_of(rationale: str) -> str:
    """'sibling_negative (age_gap_years=1)' -> 'sibling_negative'; 'fuzzy_variant/x' -> 'fuzzy_variant'."""
    return re.split(r"[/ (]", rationale, maxsplit=1)[0]


def population_categories(query_rows: Sequence[Row]) -> set[str]:
    """Categories named in population rationales, e.g. 'population/a+b' -> {'a','b'}."""
    found: set[str] = set()
    for row in query_rows:
        rationale = str(row["rationale"])
        if rationale.startswith("population/"):
            found.update(rationale.split("/", 1)[1].split("+"))
    return found


def same_person_negatives(pair_rows: Sequence[Row]) -> List[str]:
    """case_ids labeled non-match whose two records could be the same person."""
    return [
        r["case_id"]
        for r in pair_rows
        if not r["expected_match"] and is_possible_same_person(r["source"], r["target"])
    ]


def tier_parity_gap(pair_rows: Sequence[Row], query_rows: Sequence[Row]) -> List[str]:
    """Per-provision categories that never appear in the population tier."""
    pair_categories = {category_of(r["rationale"]) for r in pair_rows}
    return sorted(pair_categories - population_categories(query_rows))


def _phones(p: Patient) -> frozenset[str]:
    return frozenset(
        normalize_phone(t["value"])
        for t in p.get("telecom") or []
        if t.get("system") == "phone" and normalize_phone(t.get("value"))
    )


def _emails(p: Patient) -> frozenset[str]:
    return frozenset(
        str(t["value"]).strip().casefold()
        for t in p.get("telecom") or []
        if t.get("system") == "email" and t.get("value")
    )


def _family(p: Patient) -> str:
    names = p.get("name") or []
    return normalize_token(names[0].get("family")) if names else ""


def _address(p: Patient) -> str:
    addresses = p.get("address") or []
    if not addresses:
        return ""
    a = addresses[0]
    parts = [*(a.get("line") or []), a.get("city"), a.get("state"), a.get("postalCode")]
    return "|".join(normalize_token(x) for x in parts)


_DISAGREEMENT_FIELDS: Dict[str, Callable[[Patient], Any]] = {
    "phone": _phones,
    "email": _emails,
    "gender": lambda p: p.get("gender"),
    "surname": _family,
    "address": _address,
    "birthDate": lambda p: p.get("birthDate"),
}


def positive_field_disagreement(pair_rows: Sequence[Row]) -> Dict[str, float]:
    """Share of expected-match pairs where each field differs between the two sides."""
    positives = [r for r in pair_rows if r["expected_match"]]
    if not positives:
        return {name: float("nan") for name in _DISAGREEMENT_FIELDS}
    return {
        name: sum(get(r["source"]) != get(r["target"]) for r in positives)
        / len(positives)
        for name, get in _DISAGREEMENT_FIELDS.items()
    }


def unique_source_patients(pair_rows: Sequence[Row]) -> List[Patient]:
    """One record per distinct source id (the un-mutated side of every pair)."""
    by_id: Dict[str, Patient] = {}
    for r in pair_rows:
        by_id.setdefault(r["source"]["id"], r["source"])
    return list(by_id.values())


def people_per_address(patients: Sequence[Patient]) -> float:
    """Mean number of patients per distinct non-empty address."""
    counts = Counter(a for a in map(_address, patients) if a.strip("|"))
    return sum(counts.values()) / len(counts) if counts else float("nan")


def shared_contact_rate(patients: Sequence[Patient], system: str) -> float:
    """Of patients with at least one phone/email, the share with a value another patient also holds."""
    getter = _phones if system == "phone" else _emails
    holders: Dict[str, set[str]] = defaultdict(set)
    for p in patients:
        for value in getter(p):
            holders[value].add(p["id"])
    with_contact = [p for p in patients if getter(p)]
    if not with_contact:
        return float("nan")
    shared = sum(any(len(holders[v]) > 1 for v in getter(p)) for p in with_contact)
    return shared / len(with_contact)


def age_band_shares(
    patients: Sequence[Patient], as_of: date = AS_OF
) -> Dict[str, float]:
    ages = []
    for p in patients:
        try:
            ages.append(as_of.year - int(str(p.get("birthDate") or "")[:4]))
        except ValueError:
            continue
    if not ages:
        return {band: float("nan") for band, _, _ in AGE_BANDS}
    return {
        band: sum(lo <= age < hi for age in ages) / len(ages)
        for band, lo, hi in AGE_BANDS
    }


def population_pairs(
    query_rows: Sequence[Row], candidates: Dict[str, Patient]
) -> Iterator[LabeledPair]:
    """Every (query, pool candidate) pair, labeled by expected_match_ids."""
    for q in query_rows:
        expected = set(q["expected_match_ids"])
        for candidate_id in q["candidate_ids"]:
            yield LabeledPair(
                features=pair_features(q["query"], candidates[candidate_id]),
                is_true_match=candidate_id in expected,
                pair_id=f"{q['query_id']}::{candidate_id}",
            )


def baseline_f1s(
    query_rows: Sequence[Row], candidates: Dict[str, Patient]
) -> Dict[str, float]:
    pairs = list(population_pairs(query_rows, candidates))
    return {name: evaluate(matcher, pairs).f1 for name, matcher in BASELINES.items()}


def build_report(
    pairs_path: Path = PAIRS_PATH,
    queries_path: Path = QUERIES_PATH,
    candidates_path: Path = CANDIDATES_PATH,
) -> Dict[str, Any]:
    pair_rows = read_jsonl(pairs_path)
    query_rows = read_jsonl(queries_path)
    candidates = {r["id"]: r["patient"] for r in read_jsonl(candidates_path)}
    patients = unique_source_patients(pair_rows)
    f1s = baseline_f1s(query_rows, candidates)
    best_single = max(f1s[name] for name in SINGLE_FIELD_BASELINES)
    return {
        "same_person_negatives": same_person_negatives(pair_rows),
        "tier_parity_gap": tier_parity_gap(pair_rows, query_rows),
        "positive_field_disagreement": positive_field_disagreement(pair_rows),
        "people_per_address": people_per_address(patients),
        "shared_phone_rate": shared_contact_rate(patients, "phone"),
        "shared_email_rate": shared_contact_rate(patients, "email"),
        "age_band_shares": age_band_shares(patients),
        "baseline_f1": f1s,
        "best_single_field_f1": best_single,
        "multi_field_margin": f1s[MULTI_FIELD_BASELINE_NAME] - best_single,
        "category_counts": dict(
            Counter(category_of(r["rationale"]) for r in pair_rows)
        ),
    }


if __name__ == "__main__":
    print(json.dumps(build_report(), indent=2, default=list))
