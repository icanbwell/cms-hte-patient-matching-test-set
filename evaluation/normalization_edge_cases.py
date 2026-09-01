"""Normalization edge-case variants: the Google Doc's Section 2 "normalization
edge cases" (diacritic-folded names, punctuation/whitespace variation, and
placeholder/out-of-range dates of birth), per CMS spec SS V.A.3-4.

Unlike mutations.py's fuzzy-comparison variants (which rely on an edit-
distance tolerance and are expected to match only because fuzzy comparison is
*permitted* for that field), the two variant generators here produce values
that CMS SS V.A requires normalization to fold into an EXACT match - a
diacritic-folded or punctuation-stripped name is not "close enough via fuzzy
tolerance", it is required to become byte-identical to the un-accented/
unpunctuated form after a spec-compliant normalization step runs. Marking
these true-matches therefore exercises normalization behavior specifically,
not fuzzy comparison - any matching engine under test is expected to
normalize before comparing, per Design Principle 1.

The third edge case (placeholder/out-of-range DOB) is deliberately NOT a
variant-pair generator here - a placeholder/out-of-range DOB should be
excluded from matching entirely (never reach a matchable field), which is a
single-patient normalization behavior, not a match/non-match pair this
repo's pairwise/population manifests can express.
"""

from __future__ import annotations

import copy
import random
from typing import Any, Dict, Tuple

Patient = Dict[str, Any]

_MIN_MUTATABLE_LENGTH = 3

# Common Latin-script diacritics folded by the reference matching engine's
# normalization.text_utils.fold_diacritics.
DIACRITIC_MAP: Dict[str, str] = {
    "a": "á",
    "e": "é",
    "i": "í",
    "o": "ó",
    "u": "ú",
    "n": "ñ",
    "c": "ç",
}

# One punctuation/whitespace insertion per case, matching CMS SS V.A.2-3's list
# of characters normalization must remove/ignore: hyphen, apostrophe, period,
# and doubled internal whitespace.
PUNCTUATION_CHARS: Tuple[str, ...] = ("-", "'", ".", "  ")


def _copy_patient(patient: Patient) -> Patient:
    return copy.deepcopy(patient)


def _rng(rng: random.Random | None) -> random.Random:
    return rng if rng is not None else random.Random()


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


def diacritic_variant(
    patient: Patient,
    field: str = "given",
    *,
    name_index: int = 0,
    rng: random.Random | None = None,
) -> Patient:
    """Replace the first occurrence of a foldable character in `field` with
    its accented form (e.g. "Nunez" -> "Nuñez", "Jose" -> "José"). No-op if
    the value contains none of DIACRITIC_MAP's keys or is too short."""
    rng = _rng(rng)
    patient = _copy_patient(patient)
    value = _name_value(patient, field, name_index=name_index)
    if len(value) < _MIN_MUTATABLE_LENGTH:
        return patient
    lowered = value.lower()
    foldable_positions = [i for i, ch in enumerate(lowered) if ch in DIACRITIC_MAP]
    if not foldable_positions:
        return patient
    pos = rng.choice(foldable_positions)
    accented = DIACRITIC_MAP[lowered[pos]]
    new_value = value[:pos] + accented + value[pos + 1 :]
    _set_name_value(patient, field, new_value, name_index=name_index)
    return patient


def punctuation_variant(
    patient: Patient,
    field: str = "family",
    *,
    name_index: int = 0,
    punctuation: str = "random",
    rng: random.Random | None = None,
) -> Patient:
    """Insert one punctuation/whitespace character from PUNCTUATION_CHARS into
    `field` at a random internal position (e.g. "OBrien" -> "O'Brien",
    "SmithJones" -> "Smith-Jones"). No-op if the value is too short to have an
    internal position."""
    rng = _rng(rng)
    patient = _copy_patient(patient)
    value = _name_value(patient, field, name_index=name_index)
    if len(value) < _MIN_MUTATABLE_LENGTH:
        return patient
    if punctuation == "random":
        punctuation = rng.choice(PUNCTUATION_CHARS)
    elif punctuation not in PUNCTUATION_CHARS:
        raise ValueError(f"Unknown punctuation: {punctuation!r}")
    pos = rng.randrange(1, len(value))
    new_value = value[:pos] + punctuation + value[pos:]
    _set_name_value(patient, field, new_value, name_index=name_index)
    return patient
