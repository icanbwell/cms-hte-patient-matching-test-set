"""Dataset audit: label-validity, realism metrics, and naive-baseline results.

Run from the repo root:

    PYTHONPATH=. uv run python evaluation/audit.py

The duplicate detector below (SSN, phone, name, birth-date and edit-distance
helpers) is deliberately written separately from `identity_guard.py` and
`text_distance.py`: the audit must catch what the generators' own guards miss,
so it must not share their blind spots. Keep the two independent when changing
either side.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, Iterator, List, Sequence, Tuple

from fhir_conformance import violations
from identity_guard import (
    is_placeholder_ssn,
    is_possible_same_person,
    normalize_phone,
    normalize_token,
)
from naive_baselines import (
    BASELINES,
    MULTI_FIELD_BASELINE_NAME,
    SINGLE_FIELD_BASELINES,
    pair_features,
)
from population_targets import AGE_BANDS, ONC_AS_OF, age_band_targets
from rationale import category_of
from rule_eval import LabeledPair, evaluate

Patient = Dict[str, Any]
Row = Dict[str, Any]

CASES_DIR = Path(__file__).parent / "cases"
PAIRS_PATH = CASES_DIR / "sample_labeled_pairs.jsonl"
QUERIES_PATH = CASES_DIR / "population_queries.jsonl"
CANDIDATES_PATH = CASES_DIR / "population_candidates.jsonl"

# AUDIT_DATASET / release_gate.py's argument selects which exported file set to
# audit. "realistic" is generated on demand (export_realistic_dataset.py), "full"
# is the output of export_full_onc_dataset.py; "committed" is the checked-in sample.
DATASET_FILES: Dict[str, Tuple[str, str, str]] = {
    "committed": (
        "sample_labeled_pairs.jsonl",
        "population_queries.jsonl",
        "population_candidates.jsonl",
    ),
    "realistic": (
        "realistic_labeled_pairs.jsonl",
        "realistic_population_queries.jsonl",
        "realistic_population_candidates.jsonl",
    ),
    "full": (
        "full_labeled_pairs.jsonl",
        "full_population_queries.jsonl",
        "full_population_candidates.jsonl",
    ),
}


def dataset_paths(dataset: str = "committed") -> Tuple[Path, Path, Path]:
    """(pairs, queries, candidates) paths for a named dataset."""
    if dataset not in DATASET_FILES:
        raise ValueError(
            f"unknown dataset {dataset!r}; expected one of {sorted(DATASET_FILES)}"
        )
    pairs, queries, candidates = DATASET_FILES[dataset]
    return CASES_DIR / pairs, CASES_DIR / queries, CASES_DIR / candidates


REALISTIC_PATHS = dataset_paths("realistic")


def read_jsonl(path: Path) -> List[Row]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def _read_nonempty(path: Path) -> List[Row]:
    rows = read_jsonl(path)
    if not rows:
        raise ValueError(f"{path} has no rows; refusing to audit an empty dataset")
    return rows


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


def _levenshtein(a: str, b: str, limit: int) -> int:
    """Edit distance; limit + 1 once it is known to exceed limit. Independent of
    the generator's helpers on purpose (the audit must not share its blind spots)."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        new = [i]
        for j, cb in enumerate(b, 1):
            new.append(min(row[j] + 1, new[-1] + 1, row[j - 1] + (ca != cb)))
        if min(new) > limit:
            return limit + 1
        row = new
    return row[-1]


# Thresholds of the audit's own duplicate detector (independent of the guard's).
_PHONE_DIGITS = 10
_ISO_DATE_LENGTH = 10
_DUPLICATE_NAME_EDITS = 2
_DUPLICATE_DOB_EDITS = 1
_TWO_OF_THREE_AGREEMENTS = 2


def _audit_ssn(p: Patient) -> str | None:
    for ident in p.get("identifier") or []:
        if "ssn" in str(ident.get("system") or "").lower():
            digits = re.sub(r"\D", "", str(ident.get("value") or ""))
            if len(digits) == 9 and not is_placeholder_ssn(digits):
                return digits
    return None


def _audit_phones(p: Patient) -> FrozenSet[str]:
    return frozenset(v for v in _phones(p) if len(v) == _PHONE_DIGITS)


def _audit_name(p: Patient) -> str:
    names = p.get("name") or []
    if not names:
        return ""
    given = names[0].get("given") or []
    first = normalize_token(given[0]) if given else ""
    family = normalize_token(names[0].get("family"))
    return f"{first} {family}" if first and family else ""


def _dob_close(a: str, b: str, limit: int, allow_swap: bool) -> bool:
    if not (a and b):
        return False
    if _levenshtein(a, b, limit) <= limit:
        return True
    return bool(
        allow_swap
        and len(a) == len(b) == _ISO_DATE_LENGTH
        and a[:4] == b[:4]
        and a[5:7] == b[8:10]
        and a[8:10] == b[5:7]
    )


def _audit_twins(a: Patient, b: Patient) -> bool:
    """Same family name and birth date, first names at least 3 edits apart, no
    near-identical SSN, and a shared phone or address: a twin or same-day sibling,
    so not one person recorded twice. Independent of the generator's version."""
    names_a, names_b = a.get("name") or [], b.get("name") or []
    dob = str(a.get("birthDate") or "")
    if not (dob and dob == str(b.get("birthDate") or "") and names_a and names_b):
        return False
    family = normalize_token(names_a[0].get("family"))
    if not family or family != normalize_token(names_b[0].get("family")):
        return False
    given_a, given_b = names_a[0].get("given") or [], names_b[0].get("given") or []
    first_a = normalize_token(given_a[0]) if given_a else ""
    first_b = normalize_token(given_b[0]) if given_b else ""
    if not (first_a and first_b) or _levenshtein(first_a, first_b, 2) <= 2:
        return False
    ssn_a, ssn_b = _audit_ssn(a), _audit_ssn(b)
    if ssn_a and ssn_b and _levenshtein(ssn_a, ssn_b, 1) <= 1:
        return False
    return bool(_audit_phones(a) & _audit_phones(b)) or _audit_same_address(a, b)


def _audit_address(p: Patient) -> str:
    addresses = p.get("address") or []
    if not addresses:
        return ""
    lines = addresses[0].get("line") or []
    street = normalize_token(lines[0]) if lines else ""
    zip_code = normalize_token(addresses[0].get("postalCode"))
    return f"{street}|{zip_code}" if street and zip_code else ""


def _audit_same_address(a: Patient, b: Patient) -> bool:
    address = _audit_address(a)
    return bool(address) and address == _audit_address(b)


def _audit_first(p: Patient) -> str:
    names = p.get("name") or []
    given = (names[0].get("given") or []) if names else []
    return normalize_token(given[0]) if given else ""


def _looks_like_duplicate(a: Patient, b: Patient) -> bool:
    if _audit_twins(a, b):
        return False
    ssn_a, ssn_b = _audit_ssn(a), _audit_ssn(b)
    if ssn_a and ssn_b and _levenshtein(ssn_a, ssn_b, 1) <= 1:
        return True
    dob_a, dob_b = str(a.get("birthDate") or ""), str(b.get("birthDate") or "")
    if _audit_phones(a) & _audit_phones(b) and _dob_close(dob_a, dob_b, 0, False):
        return True
    # Same first name and an identical birth date under another family name: a
    # surname change that no SSN or phone survived.
    first = _audit_first(a)
    if first and first == _audit_first(b) and dob_a and dob_a == dob_b:
        return True
    name_a, name_b = _audit_name(a), _audit_name(b)
    return bool(
        name_a
        and name_b
        and _levenshtein(name_a, name_b, _DUPLICATE_NAME_EDITS) <= _DUPLICATE_NAME_EDITS
        and _dob_close(dob_a, dob_b, _DUPLICATE_DOB_EDITS, True)
    )


def probable_duplicate_negatives(
    pair_rows: Sequence[Row],
    query_rows: Sequence[Row],
    candidates: Dict[str, Patient],
) -> List[str]:
    """Non-match pairs (pairwise rows, and every non-matching population pool
    pair) whose two records look like one person recorded twice.

    A looser, independent check than same_person_negatives, which only repeats
    the generator's exact-match predicate: SSNs within edit distance 1; or a
    shared phone with an identical birth date; or first+family names within
    edit distance 2 with birth dates within edit distance 1 or a month/day swap.
    (Wider date tolerances flagged only legitimate pairs on the realistic set:
    household members sharing a phone with birth dates a character or two
    apart, and same-surname relatives decades apart.) Returns case ids ("<case_id>") and population pair ids
    ("<query_id>::<candidate_id>")."""
    flagged = [
        r["case_id"]
        for r in pair_rows
        if not r["expected_match"] and _looks_like_duplicate(r["source"], r["target"])
    ]
    for q in query_rows:
        expected = set(q["expected_match_ids"])
        for candidate_id in q["candidate_ids"]:
            if candidate_id in expected:
                continue
            if _looks_like_duplicate(q["query"], candidates[candidate_id]):
                flagged.append(f"{q['query_id']}::{candidate_id}")
    return flagged


def identical_positive_pairs(
    pair_rows: Sequence[Row],
    query_rows: Sequence[Row],
    candidates: Dict[str, Patient],
) -> List[str]:
    """True-match pairs whose two records are byte-identical: they exercise no
    matching logic and inflate recall. Returns case ids and population pair
    ids ("<query_id>::<candidate_id>")."""
    flagged = [
        r["case_id"]
        for r in pair_rows
        if r["expected_match"] and r["source"] == r["target"]
    ]
    for q in query_rows:
        for candidate_id in q["expected_match_ids"]:
            if q["query"] == candidates[candidate_id]:
                flagged.append(f"{q['query_id']}::{candidate_id}")
    return flagged


def id_equality_f1(pair_rows: Sequence[Row]) -> float:
    """F1 of the rule "match iff source.id == target.id" on the pairwise tier.
    Ids must carry no label, so this is 0 (release_rows.py hashes them)."""
    tp = sum(1 for r in pair_rows if r["expected_match"] and _same_id(r))
    fp = sum(1 for r in pair_rows if not r["expected_match"] and _same_id(r))
    fn = sum(1 for r in pair_rows if r["expected_match"] and not _same_id(r))
    return 2 * tp / (2 * tp + fp + fn) if tp else 0.0


def _same_id(row: Row) -> bool:
    return row["source"].get("id") == row["target"].get("id")


def match_count_share(query_rows: Sequence[Row], count: int) -> float:
    """Share of population queries with exactly `count` expected matches. The
    population tier must include searches where the person is absent (0) or
    appears once (1); a tier where every query has several matches flatters
    precision and cannot test false positives on "no match exists"."""
    if not query_rows:
        return 0.0
    return sum(1 for q in query_rows if len(q["expected_match_ids"]) == count) / len(
        query_rows
    )


def matches_first_rate(query_rows: Sequence[Row]) -> float:
    """Share of queries whose true matches are exactly the leading entries of
    `candidate_ids`. Pool order must not reveal the label, so this is ~0."""
    scored = [q for q in query_rows if q["expected_match_ids"]]
    if not scored:
        return 0.0
    leading = sum(
        1
        for q in scored
        if set(q["candidate_ids"][: len(q["expected_match_ids"])])
        == set(q["expected_match_ids"])
    )
    return leading / len(scored)


def conformance_violations(
    pair_rows: Sequence[Row],
    query_rows: Sequence[Row],
    candidates: Dict[str, Patient],
) -> List[str]:
    """Every FHIR structural problem across the three files, as
    "<where>: <problem>" (see fhir_conformance.violations)."""
    found: List[str] = []
    for r in pair_rows:
        for side in ("source", "target"):
            found += [f"{r['case_id']}.{side}: {v}" for v in violations(r[side])]
    for q in query_rows:
        found += [f"{q['query_id']}.query: {v}" for v in violations(q["query"])]
    for candidate_id, patient in candidates.items():
        found += [f"{candidate_id}: {v}" for v in violations(patient)]
    return found


def _two_of_three(source: Patient, target: Patient) -> bool:
    def first(p: Patient) -> str:
        names = p.get("name") or []
        given = (names[0].get("given") or []) if names else []
        return normalize_token(given[0]) if given else ""

    agreements = [
        bool(first(source)) and first(source) == first(target),
        bool(_family(source)) and _family(source) == _family(target),
        bool(source.get("birthDate"))
        and source.get("birthDate") == target.get("birthDate"),
    ]
    return sum(agreements) >= _TWO_OF_THREE_AGREEMENTS


def pairwise_two_of_three_f1(pair_rows: Sequence[Row]) -> float:
    """F1 over the pairwise rows (positive = expected_match) of the naive rule
    "match iff at least 2 of: first given name, family name, birth date agree"."""
    tp = fp = fn = 0
    for r in pair_rows:
        predicted = _two_of_three(r["source"], r["target"])
        if predicted and r["expected_match"]:
            tp += 1
        elif predicted:
            fp += 1
        elif r["expected_match"]:
            fn += 1
    denominator = 2 * tp + fp + fn
    return 2 * tp / denominator if denominator else 0.0


REQUIRED_HARD_NEGATIVE_CATEGORIES = (
    "hard_negative",
    "name_collision_negative",
    "sibling_negative",
    "near_miss_negative",
    "twin_like_negative",
)

_OVERLAP_FEATURES = ("ssn", "dob", "family", "given", "address", "phone", "email")


def negative_share(pair_rows: Sequence[Row]) -> float:
    """Fraction of pairwise cases labeled non-match."""
    if not pair_rows:
        return 0.0
    return sum(1 for r in pair_rows if not r["expected_match"]) / len(pair_rows)


def all_yes_f1(pair_rows: Sequence[Row]) -> float:
    """F1 of a matcher that answers "match" to every pairwise case: 2p/(1+p),
    p = positive share. The reviewer's check that "always yes" must not score well."""
    if not pair_rows:
        return 0.0
    positive = 1.0 - negative_share(pair_rows)
    return 2 * positive / (1 + positive)


def missing_hard_negative_categories(pair_rows: Sequence[Row]) -> List[str]:
    """Required hard-negative categories with no non-match row."""
    present = {
        category_of(r["rationale"]) for r in pair_rows if not r["expected_match"]
    }
    return [c for c in REQUIRED_HARD_NEGATIVE_CATEGORIES if c not in present]


def decoy_no_overlap_rate(
    query_rows: Sequence[Row], candidates: Dict[str, Patient]
) -> float:
    """Share of non-matching pool candidates that agree with their query on none
    of ssn, dob, family, given, address, phone or email (the easy-to-reject decoys)."""
    total = 0
    disjoint = 0
    for pair in population_pairs(query_rows, candidates):
        if pair.is_true_match:
            continue
        total += 1
        if not any(pair.features[name] for name in _OVERLAP_FEATURES):
            disjoint += 1
    return disjoint / total if total else 0.0


# Both sides of a placeholder collision must carry the shared dummy value, but a
# population query is a real record other pools also use, so this category
# exists in the pairwise tier only (session 15, Workstream B).
PAIRWISE_ONLY_CATEGORIES = frozenset({"placeholder_collision_negative"})


def tier_parity_gap(pair_rows: Sequence[Row], query_rows: Sequence[Row]) -> List[str]:
    """Per-provision categories that never appear in the population tier
    (except the documented pairwise-only ones)."""
    pair_categories = {category_of(r["rationale"]) for r in pair_rows}
    return sorted(
        pair_categories - population_categories(query_rows) - PAIRWISE_ONLY_CATEGORIES
    )


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
    patients: Sequence[Patient], as_of: date = ONC_AS_OF
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


def age_band_max_error(patients: Sequence[Patient], as_of: date = ONC_AS_OF) -> float:
    """Largest absolute gap between a band's share and its population target
    (population_targets.py); NaN without any dated patient."""
    shares = age_band_shares(patients, as_of)
    targets = age_band_targets()
    return max(abs(shares[band] - targets[band]) for band in targets)


def population_pairs(
    query_rows: Sequence[Row], candidates: Dict[str, Patient]
) -> Iterator[LabeledPair]:
    """Every (query, pool candidate) pair, labeled by expected_match_ids."""
    for q in query_rows:
        expected = set(q["expected_match_ids"])
        for candidate_id in q["candidate_ids"]:
            if candidate_id not in candidates:
                raise ValueError(
                    f"{q['query_id']} references unknown candidate {candidate_id!r}"
                )
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
    as_of: date = ONC_AS_OF,
) -> Dict[str, Any]:
    """`as_of` is the reference date ages are measured at: ONC's own vintage for
    the committed curated files, population_targets.AS_OF for the realistic files
    (whose birth dates are shifted forward)."""
    pair_rows = _read_nonempty(pairs_path)
    query_rows = _read_nonempty(queries_path)
    candidates = {r["id"]: r["patient"] for r in _read_nonempty(candidates_path)}
    patients = unique_source_patients(pair_rows)
    # A matcher that never predicts a match has an undefined (NaN) F1; score it 0
    # so max()/subtraction below cannot drop it or poison the gate.
    disagreement = positive_field_disagreement(pair_rows)
    f1s = {
        name: 0.0 if math.isnan(value) else value
        for name, value in baseline_f1s(query_rows, candidates).items()
    }
    best_single = max(f1s[name] for name in SINGLE_FIELD_BASELINES)
    return {
        "same_person_negatives": same_person_negatives(pair_rows),
        "probable_duplicate_negatives": probable_duplicate_negatives(
            pair_rows, query_rows, candidates
        ),
        "identical_positive_pairs": identical_positive_pairs(
            pair_rows, query_rows, candidates
        ),
        "conformance_violations": conformance_violations(
            pair_rows, query_rows, candidates
        ),
        "id_equality_f1": id_equality_f1(pair_rows),
        "matches_first_rate": matches_first_rate(query_rows),
        "zero_match_query_share": match_count_share(query_rows, 0),
        "single_match_query_share": match_count_share(query_rows, 1),
        "tier_parity_gap": tier_parity_gap(pair_rows, query_rows),
        "negative_share": negative_share(pair_rows),
        "all_yes_f1": all_yes_f1(pair_rows),
        "pairwise_two_of_three_f1": pairwise_two_of_three_f1(pair_rows),
        "missing_hard_negative_categories": missing_hard_negative_categories(pair_rows),
        "decoy_no_overlap_rate": decoy_no_overlap_rate(query_rows, candidates),
        "positive_field_disagreement": disagreement,
        "positive_phone_drift_rate": disagreement["phone"],
        "people_per_address": people_per_address(patients),
        "shared_phone_rate": shared_contact_rate(patients, "phone"),
        "shared_email_rate": shared_contact_rate(patients, "email"),
        "age_band_shares": age_band_shares(patients, as_of),
        "age_band_max_error": age_band_max_error(patients, as_of),
        "baseline_f1": f1s,
        "best_single_field_f1": best_single,
        "multi_field_margin": f1s[MULTI_FIELD_BASELINE_NAME] - best_single,
        "category_counts": dict(
            Counter(category_of(r["rationale"]) for r in pair_rows)
        ),
    }


if __name__ == "__main__":
    print(
        json.dumps(
            build_report(*dataset_paths(os.environ.get("AUDIT_DATASET", "committed"))),
            indent=2,
            default=list,
        )
    )
