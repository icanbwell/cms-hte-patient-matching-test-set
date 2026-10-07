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
from typing import Any, Callable, Dict, List, Tuple

from nicknames import NickNamer

Patient = Dict[str, Any]

# One shared NickNamer instance - it loads a static lookup table on construction,
# so reuse it across calls rather than rebuilding it per mutation (same rationale
# as onc_baseline.py's _engine() lru_cache: a read-only resource, safe to share).
_nick_namer: NickNamer | None = None


def get_nick_namer() -> NickNamer:
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


def _can_swap_month_day(d: date) -> bool:
    """True if transposing month and day gives a different, valid date."""
    return d.day <= 12 and d.day != d.month


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
        if _can_swap_month_day(d):
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
    nicknames = {n for n in get_nick_namer().nicknames_of(value.lower()) if n}
    if not nicknames:
        return patient
    _set_name_value(
        patient, "given", rng.choice(sorted(nicknames)).title(), name_index=name_index
    )
    return patient


# --------------------------------------------------------------------------------------
# Identifier mutations
# --------------------------------------------------------------------------------------

# Matches onc_loader.py's own SSN identifier.system value exactly.
SSN_SYSTEM = "http://hl7.org/fhir/sid/us-ssn"


def ssn_dropped_variant(patient: Patient) -> Patient:
    """Return a copy of `patient` with its SSN identifier removed - models the
    realistic case Luke Breyer (Epic) raised in the 2026-09-22 workgroup
    meeting, where one of a person's two on-file records carries a Social
    Security Number and the other doesn't. Matches the Epic reference doc's
    "Missing/placeholder SSN" data-quality category. No-op if `patient` has no
    SSN identifier to begin with."""
    patient = _copy_patient(patient)
    identifiers = patient.get("identifier") or []
    patient["identifier"] = [i for i in identifiers if i.get("system") != SSN_SYSTEM]
    return patient


def marriage_variant(patient: Patient, donor: Patient) -> Patient:
    """Return a copy of `patient` with its family name replaced by its second
    `name` entry (onc_loader.py loads MOTHERS_MAIDEN_NAME as a second `name`
    entry for household-linkage purposes; repurposed here as a pre-marriage
    surname proxy, since ONC has no dedicated maiden-name column) and its
    address replaced by `donor`'s address (modeling a marriage-driven move -
    ONC carries no address history for one person to draw a second address
    from, so an unrelated real ONC record's address stands in for it).
    Represents the "surname + address changed together" scenario Luke Breyer
    (Epic) raised in the 2026-09-22 workgroup meeting. No-op on the name
    change if `patient` has fewer than two `name` entries - measured against
    the vendored ONC shard, only ~5.3% of records carry a second `name` entry
    (MOTHERS_MAIDEN_NAME is sparse in the source data), so this category's
    yield is intentionally small, not a bug.

    The variant collapses to a single `name` entry carrying the maiden
    surname - keeping both entries after overwriting name[0] would leave the
    variant with the same surname twice (e.g. "Jones" at both name[0] and
    name[1]), a shape no real record has and one that would leak the maiden
    surname onto both sides of the pair via name[1] as well as name[0]."""
    patient = _copy_patient(patient)
    names = patient.get("name") or []
    if len(names) > 1:
        patient["name"] = [
            {"family": names[1]["family"], "given": names[0].get("given")}
        ]
    patient["address"] = copy.deepcopy(donor.get("address") or [])
    return patient


def phone_variant(patient: Patient) -> Patient:
    """Return a copy of `patient` using its second phone number in place of
    its first - models the same person having two different on-file phone
    numbers (e.g. an old home line vs. a newer cell number), the scenario
    Luke Breyer (Epic) named in the 2026-09-22 workgroup meeting. ONC has no
    phone `use` code (home/mobile) to draw on, so this deliberately does not
    fabricate a FHIR ContactPoint.use value - it only demonstrates two
    genuinely different real phone strings for one person. No-op if
    `patient` has fewer than two phone-system telecom entries, or if the
    first two happen to carry the identical value (PHONE2 duplicating
    PHONE verbatim is a common ONC data shape - swapping two identical
    values is not a "different phone number" scenario, and dropping the
    duplicate would shrink the telecom list without that being a
    meaningful change) - measured against the vendored ONC shard, only
    ~15.1% of records carry a PHONE2 value - and of those, ~70% duplicate
    PHONE verbatim (also a no-op here), so the real usable yield is closer
    to ~5% - this category's yield is intentionally small, not a bug."""
    patient = _copy_patient(patient)
    telecom = patient.get("telecom") or []
    phones = [t for t in telecom if t.get("system") == "phone"]
    if len(phones) < 2 or phones[0].get("value") == phones[1].get("value"):
        return patient
    non_phone = [t for t in telecom if t.get("system") != "phone"]
    patient["telecom"] = [phones[1]] + non_phone
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


# How many times to retry one mutation type on a patient before treating it as
# inapplicable. Deterministic no-ops (a name with no known nickname, a DOB that
# cannot be transposed) fail every attempt; randomly-failing ones (a dob_typo whose
# digit lands on an invalid calendar date, a transposition of two identical
# letters) usually succeed within a few, so retrying keeps them from being
# under-sampled.
_MAX_ATTEMPTS_PER_MUTATION = 10


def generate_fuzzy_variant(
    patient: Patient, mutation_type: str = "random", *, rng: random.Random | None = None
) -> Tuple[Patient, str]:
    """Apply one named mutation (or a randomly-chosen one) to `patient`.

    Returns (mutated_patient, mutation_type_applied) so callers can record which
    mutation produced a given labeled pair (e.g. as rule_eval.LabeledPair.strata).

    A "random" draw never returns an unchanged patient while any mutation can
    change it: a drawn type that does nothing on this patient (a swap on a DOB
    that cannot be transposed, a nickname for a name with none, a typo that
    lands on an invalid date) is retried and then replaced by another type. Only
    a patient nothing applies to (no DOB and no usable name) is returned
    unchanged; callers should skip emitting a pair for it. An explicit
    `mutation_type` is applied once and may legitimately no-op.
    """
    rng = _rng(rng)
    if mutation_type != "random":
        if mutation_type not in MUTATIONS:
            raise ValueError(f"Unknown mutation_type: {mutation_type!r}")
        return MUTATIONS[mutation_type](patient, rng), mutation_type

    remaining = list(MUTATIONS)
    while True:
        drawn = rng.choice(remaining)
        for _ in range(_MAX_ATTEMPTS_PER_MUTATION):
            variant = MUTATIONS[drawn](patient, rng)
            if variant != patient:
                return variant, drawn
        remaining.remove(drawn)
        if not remaining:
            return variant, drawn


# Each MUTATIONS key targets exactly one of these three top-level fields.
# generate_compound_variant() draws whole groups (not individual mutation
# keys) so that "n_mutations" means "n distinct fields changed", not "n
# mutator calls that might collide on the same field or no-op silently".
_MUTATION_FIELD_GROUPS: Dict[str, Tuple[str, ...]] = {
    "birthDate": ("dob_day", "dob_month", "dob_year", "dob_swap", "dob_typo"),
    "family": ("family_typo", "family_transpose", "family_drop_letters"),
    "given": ("given_nickname", "given_abbreviate"),
}


def count_changed_fields(original: Patient, variant: Patient) -> int:
    """Count how many of the three fields generate_compound_variant() targets
    (birthDate, family, given) actually differ between `original` and
    `variant`. Ground truth for whether a compound variant met its own
    "touches >=n_mutations distinct fields" contract - a field group whose
    mutators all legitimately no-op (e.g. an empty given name, a missing
    birthDate) must not be counted as changed just because a mutator was
    tried against it."""
    changed = 0
    if original.get("birthDate") != variant.get("birthDate"):
        changed += 1
    original_names = original.get("name") or []
    variant_names = variant.get("name") or []
    original_family = original_names[0].get("family") if original_names else None
    variant_family = variant_names[0].get("family") if variant_names else None
    if original_family != variant_family:
        changed += 1
    original_given = original_names[0].get("given") if original_names else None
    variant_given = variant_names[0].get("given") if variant_names else None
    if original_given != variant_given:
        changed += 1
    return changed


def generate_compound_variant(
    patient: Patient,
    *,
    n_mutations: int = 2,
    rng: random.Random | None = None,
) -> Tuple[Patient, List[str]]:
    """Apply mutators from `n_mutations` distinct field groups (birthDate/
    family/given) to `patient` in sequence, each acting on the previous
    mutator's output - models the realistic multi-field true-match pair Luke
    Breyer (Epic) raised in the 2026-09-22 workgroup meeting ("every correct
    match pair was an exact copy with only one field changed").
    generate_fuzzy_variant() itself is unchanged and still applies exactly
    one mutation - several CMS provisions specifically need that
    single-field-diff shape to test one rule in isolation, so this is an
    additional true-match category, not a replacement.

    Within each chosen field group, every mutator in the group is tried (in
    random order) until one actually changes that field on this patient -
    guarding against a field group's mutators legitimately no-op'ing (e.g.
    substitute_nickname on a name with no known nickname) and silently
    yielding a variant that touches fewer than `n_mutations` distinct
    fields. If every mutator in a group no-ops for this patient (e.g. no
    birthDate to mutate at all), that field is left unchanged rather than
    guessing - see this repo's mutators' own no-op docstrings.

    Returns (mutated_patient, mutation_types_applied); the list always has
    exactly `n_mutations` entries, one per field group, in the order the
    groups were drawn. Raises ValueError if n_mutations < 2 (a single
    mutation is generate_fuzzy_variant()'s job, not this function's) or if
    n_mutations exceeds the number of distinct field groups (there are only
    3 - birthDate, family, given - so a field can never be repeated)."""
    if n_mutations < 2:
        raise ValueError("generate_compound_variant requires n_mutations >= 2")
    if n_mutations > len(_MUTATION_FIELD_GROUPS):
        raise ValueError(
            "generate_compound_variant supports at most "
            f"{len(_MUTATION_FIELD_GROUPS)} distinct fields "
            f"({', '.join(_MUTATION_FIELD_GROUPS)}), got n_mutations={n_mutations}"
        )
    rng = _rng(rng)
    field_names = rng.sample(list(_MUTATION_FIELD_GROUPS), n_mutations)
    variant = patient
    mutation_types: List[str] = []
    for field_name in field_names:
        candidates = list(_MUTATION_FIELD_GROUPS[field_name])
        rng.shuffle(candidates)
        applied = candidates[0]
        for mutation_type in candidates:
            attempt = MUTATIONS[mutation_type](variant, rng)
            if attempt != variant:
                variant = attempt
                applied = mutation_type
                break
        mutation_types.append(applied)
    return variant, mutation_types
