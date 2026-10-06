"""Shared inputs for the export scripts: the sampled patients, the held-out
donor pool, and the drift profile.

Donors are the rows IMMEDIATELY AFTER the sample in the same ONC shard, so
they are never in the generated set: a donated surname, address, phone or
email cannot collide with an in-set record. The usual memory caution applies
(one shard only, see SYNTHETIC_DATA_SETUP.md "Memory & scale").
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

from drift_profile import DriftProfile
from onc_loader import load_onc_patients

Patient = Dict[str, Any]

DEFAULT_DONOR_SIZE = 2000
ONC_DIR = Path(__file__).parent / "fixtures" / "onc"


def load_sample_and_donors(
    sample_size: int, donor_size: int = DEFAULT_DONOR_SIZE, *, shard_index: int = 0
) -> Tuple[List[Patient], List[Patient]]:
    shard = sorted(ONC_DIR.glob("*.csv"))[shard_index]
    loaded = load_onc_patients([shard])
    return loaded[:sample_size], loaded[sample_size : sample_size + donor_size]


def load_profile() -> DriftProfile:
    """DRIFT_PROFILE_PATH if set, else the placeholder default profile."""
    path = os.environ.get("DRIFT_PROFILE_PATH")
    return DriftProfile.from_json(Path(path)) if path else DriftProfile()
