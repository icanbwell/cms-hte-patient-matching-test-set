"""Field-level record mutations for generating "should-still-match" fuzzy-tolerance
test pairs.

These implement the Google Doc's ("Proposal: A Shared Test Dataset for CMS v3.3.0
Patient Matching Compliance") Section 2 definition of a fuzzy-eligible positive
pair: "a single-character edit (insertion, deletion, substitution, or
transposition ... the spec's own definition of the fuzzy tolerance it allows)".
Each mutation function therefore applies exactly one such edit per call by
default, so a caller can compose `generate_fuzzy_variant()` output directly into
a labeled pair alongside the unmutated original: (original, variant,
is_true_match=True).

Ported from two prior, never-merged internal prototypes and rewritten to operate on
onc_loader.py's FHIR Patient dict shape (not the ONC CSV's flat FIRST/LAST/DOB
columns those prototypes used), and to use rapidfuzz (already a core
dependency of the reference matching engine) instead of the prototypes' Redis/embedding/
CNN-training machinery, which doesn't apply to this repo's rule-based matcher:

  - DOB mutations: an internal rapid-prototyping repo's record-modification
    utility (`RecordModifier.modify_birthdate`)
  - Name mutations: an unmerged `embed-proto` branch of the legacy production
    matching engine's embedding-prototype work (its `NameModifier` hierarchy) -
    ported as plain functions here rather than a class hierarchy, to match this
    module's existing function-based style (onc_baseline.py, rule_eval.py), and
    with the embedding-specific `TargetStrategy`/`ConstructorStrategy`
    machinery dropped entirely, since it only existed to build embedding-model
    input strings.

See SYNTHETIC_DATA_COMPARISON.md for the full accounting of what was carried
over, what was deliberately left behind, and why.
"""

from __future__ import annotations

import copy
import random
import string
from datetime import date, timedelta
from typing import Any, Callable, Dict, Tuple

from nicknames import NickNamer

Patient = Dict[str, Any]

# One shared NickNamer instance - it loads a static lookup table on construction,
# so reuse it across calls rather than rebuilding it per mutation (same rationale
# as onc_baseline.py's _engine() lru_cache: a read-only resource, safe to share).
_nick_namer: NickNamer | None = None


def _get_nick_namer() -> NickNamer:
    global _nick_namer
    if _nick_namer is None:
        _nick_namer = NickNamer()
    return _nick_namer


def _copy_patient(patient: Patient) -> Patient:
    return copy.deepcopy(patient)


def _rng(rng: random.Random | None) -> random.Random:
    return rng if rng is not None else random.Random()


# --------------------------------------------------------------------------------------
# DOB mutations
# --------------------------------------------------------------------------------------

DOB_ERROR_TYPES = ("day", "month", "year", "swap", "typo")


def mutate_dob(
    patient: Patient, error_type: str = "random", *, rng: random.Random | None = None
) -> Patient:
    """Return a copy of `patient` with `birthDate` perturbed by `error_type`.

    error_type: one of DOB_ERROR_TYPES, or "random" to pick one uniformly.
    No-ops (returns an unmodified copy) if `birthDate` is absent - mirrors
    onc_loader.py's own "only set birthDate when DOB is present" convention
    rather than raising on the ONC "Null" shard's intentionally-missing dates.
    """
    rng = _rng(rng)
    patient = _copy_patient(patient)
    raw = patient.get("birthDate")
    if not raw:
        return patient

    if error_type == "random":
        error_type = rng.choice(DOB_ERROR_TYPES)
    if error_type not in DOB_ERROR_TYPES:
        raise ValueError(f"Unknown DOB error_type: {error_type!r}")

    d = date.fromisoformat(raw)

    if error_type == "day":
        d = d + timedelta(days=rng.choice([-3, -2, -1, 1, 2, 3]))
    elif error_type == "month":
        new_month = ((d.month - 1 + rng.choice([-2, -1, 1, 2])) % 12) + 1
        d = _safe_replace(d, month=new_month)
    elif error_type == "year":
        d = _safe_replace(d, year=d.year + rng.choice([-2, -1, 1, 2]))
    elif error_type == "swap":
        # Month/day transposition - only meaningful when both are valid as the
        # other (day <= 12) and actually different (else it's a no-op mutation).
        if d.day <= 12 and d.day != d.month:
            d = d.replace(month=d.day, day=d.month)
    elif error_type == "typo":
        d = _typo_digit(d, rng) or d

    patient["birthDate"] = d.isoformat()
    return patient


def _safe_replace(d: date, **kwargs: int) -> date:
    """date.replace(), falling back to day=28 on an invalid day-of-month (e.g.
    Jan 31 -> Feb 31) rather than raising - a real DOB data-entry error would
    exhibit the same "nearby but not identical" failure mode, not a crash."""
    try:
        return d.replace(**kwargs)
    except ValueError:
        return d.replace(day=28, **kwargs)


def _typo_digit(d: date, rng: random.Random) -> date | None:
    """Substitute one digit of YYYYMMDD with a different digit, re-parsing the
    result. Returns None (caller keeps the original date) if the typo produces
    an invalid calendar date, rather than raising."""
    digits = list(d.isoformat().replace("-", ""))
    pos = rng.randrange(len(digits))
    digits[pos] = rng.choice([c for c in "0123456789" if c != digits[pos]])
    new_raw = "".join(digits)
    try:
        return date(int(new_raw[:4]), int(new_raw[4:6]), int(new_raw[6:8]))
    except ValueError:
        return None


# --------------------------------------------------------------------------------------
# Name mutations
# --------------------------------------------------------------------------------------

_MIN_MUTATABLE_LENGTH = 3


def _name_value(patient: Patient, field: str, *, name_index: int = 0) -> str:
    names = patient.get("name") or []
    if name_index >= len(names):
        return ""
    entry = names[name_index]
    if field == "family":
        return str(entry.get("family") or "")
    if field == "given":
        given = entry.get("given") or []
        return str(given[0]) if given else ""
    raise ValueError(f"Unknown name field: {field!r}")


def _set_name_value(
    patient: Patient, field: str, value: str, *, name_index: int = 0
) -> None:
    names = patient.get("name") or []
    if name_index >= len(names):
        return
    if field == "family":
        names[name_index]["family"] = value
    elif field == "given":
        given = names[name_index].get("given") or []
        if given:
            given[0] = value
        else:
            names[name_index]["given"] = [value]
    else:
        raise ValueError(f"Unknown name field: {field!r}")


def drop_letters(
    patient: Patient,
    field: str = "family",
    *,
    name_index: int = 0,
    drop_ratio: float = 0.2,
    rng: random.Random | None = None,
) -> Patient:
    """Drop a random subset of letters from `field`. No-op if the value is
    shorter than _MIN_MUTATABLE_LENGTH (dropping letters from e.g. "Li" isn't a
    realistic data-entry error, it's a different name)."""
    rng = _rng(rng)
    patient = _copy_patient(patient)
    value = _name_value(patient, field, name_index=name_index)
    if len(value) < _MIN_MUTATABLE_LENGTH:
        return patient
    n_drops = max(1, int(len(value) * drop_ratio))
    positions = set(rng.sample(range(len(value)), min(n_drops, len(value) - 1)))
    new_value = "".join(c for i, c in enumerate(value) if i not in positions)
    _set_name_value(patient, field, new_value, name_index=name_index)
    return patient


def abbreviate(
    patient: Patient,
    field: str = "given",
    *,
    name_index: int = 0,
    add_period: bool = True,
) -> Patient:
    """Reduce `field` to its first initial - the common "William" -> "W."
    intake-form abbreviation."""
    patient = _copy_patient(patient)
    value = _name_value(patient, field, name_index=name_index)
    if not value:
        return patient
    abbreviated = value[0] + ("." if add_period else "")
    _set_name_value(patient, field, abbreviated, name_index=name_index)
    return patient


def transpose_characters(
    patient: Patient,
    field: str = "family",
    *,
    name_index: int = 0,
    rng: random.Random | None = None,
) -> Patient:
    """Swap one adjacent pair of characters in `field` - the transposition edit
    the CMS spec's fuzzy-tolerance definition names explicitly."""
    rng = _rng(rng)
    patient = _copy_patient(patient)
    value = _name_value(patient, field, name_index=name_index)
    if len(value) < 2:
        return patient
    chars = list(value)
    pos = rng.randrange(len(chars) - 1)
    chars[pos], chars[pos + 1] = chars[pos + 1], chars[pos]
    _set_name_value(patient, field, "".join(chars), name_index=name_index)
    return patient


def typo_edit(
    patient: Patient,
    field: str = "family",
    *,
    name_index: int = 0,
    num_edits: int = 1,
    char_pool: str = string.ascii_uppercase,
    rng: random.Random | None = None,
) -> Patient:
    """Apply `num_edits` single-character insert/delete/substitute operations to
    `field` - the other two edit types the CMS spec's fuzzy-tolerance definition
    names (insertion, deletion, substitution), alongside transpose_characters's
    transposition. Defaults to num_edits=1 to match the spec's single-character
    tolerance exactly; pass a higher value deliberately to generate a case that
    should exceed that tolerance (see SYNTHETIC_DATA_COMPARISON.md's discussion
    of hard-negative vs. fuzzy-positive boundary cases)."""
    rng = _rng(rng)
    patient = _copy_patient(patient)
    value = _name_value(patient, field, name_index=name_index)
    if len(value) < _MIN_MUTATABLE_LENGTH:
        return patient

    text = value
    for _ in range(num_edits):
        text = _apply_single_edit(text, rng, char_pool)
    _set_name_value(patient, field, text, name_index=name_index)
    return patient


def _apply_single_edit(text: str, rng: random.Random, char_pool: str) -> str:
    operation = rng.choice(["insert", "delete", "substitute"])
    if operation == "insert" or len(text) <= 1:
        pos = rng.randint(0, len(text))
        return text[:pos] + rng.choice(char_pool) + text[pos:]
    if operation == "delete":
        pos = rng.randrange(len(text))
        return text[:pos] + text[pos + 1 :]
    pos = rng.randrange(len(text))
    return text[:pos] + rng.choice(char_pool) + text[pos + 1 :]


def substitute_nickname(
    patient: Patient, *, name_index: int = 0, rng: random.Random | None = None
) -> Patient:
    """Replace the given (first) name with one of its common nicknames/
    diminutives (e.g. "Katherine" -> "Kate"), per the CMS Doc's Section 2 call for
    "normalization edge cases". No-op if the given name has no known nicknames.
    """
    rng = _rng(rng)
    patient = _copy_patient(patient)
    value = _name_value(patient, "given", name_index=name_index)
    if not value:
        return patient
    nicknames = {n for n in _get_nick_namer().nicknames_of(value.lower()) if n}
    if not nicknames:
        return patient
    _set_name_value(
        patient, "given", rng.choice(sorted(nicknames)).title(), name_index=name_index
    )
    return patient


# --------------------------------------------------------------------------------------
# Composition
# --------------------------------------------------------------------------------------

# A mutator is (patient, rng) -> mutated patient copy. Registered under a stable
# name so callers/tests can request a specific mutation type or "random".
MUTATIONS: Dict[str, Callable[[Patient, random.Random], Patient]] = {
    "dob_day": lambda p, rng: mutate_dob(p, "day", rng=rng),
    "dob_month": lambda p, rng: mutate_dob(p, "month", rng=rng),
    "dob_year": lambda p, rng: mutate_dob(p, "year", rng=rng),
    "dob_swap": lambda p, rng: mutate_dob(p, "swap", rng=rng),
    "dob_typo": lambda p, rng: mutate_dob(p, "typo", rng=rng),
    "family_typo": lambda p, rng: typo_edit(p, "family", rng=rng),
    "family_transpose": lambda p, rng: transpose_characters(p, "family", rng=rng),
    "family_drop_letters": lambda p, rng: drop_letters(p, "family", rng=rng),
    "given_nickname": lambda p, rng: substitute_nickname(p, rng=rng),
    "given_abbreviate": lambda p, rng: abbreviate(p, "given"),
}


def generate_fuzzy_variant(
    patient: Patient, mutation_type: str = "random", *, rng: random.Random | None = None
) -> Tuple[Patient, str]:
    """Apply one named mutation (or a randomly-chosen one) to `patient`.

    Returns (mutated_patient, mutation_type_applied) so callers can record which
    mutation produced a given labeled pair (e.g. as rule_eval.LabeledPair.strata).
    """
    rng = _rng(rng)
    if mutation_type == "random":
        mutation_type = rng.choice(list(MUTATIONS))
    if mutation_type not in MUTATIONS:
        raise ValueError(f"Unknown mutation_type: {mutation_type!r}")
    return MUTATIONS[mutation_type](patient, rng), mutation_type
