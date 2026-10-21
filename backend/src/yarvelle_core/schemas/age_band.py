# Yarvelle Core — Domain-Neutral AI Agent Runtime & Execution Engine
# Copyright 2026 Spectrayan (https://spectrayan.com)
#
# Licensed under the PolyForm Noncommercial License 1.0.0 and the
# Yarvelle Core Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
# Personal and household local use only. Commercial use, hosted service
# offering, rebranding, white-labeling, and redistribution of modified
# forks are prohibited without a written commercial license from Spectrayan.
#
# Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)

"""Canonical age-band vocabulary shared by core safety gates and every pack.

Core gates and packs must agree on one key per band, otherwise an under-13
safeguard silently never fires. Packs persist the canonical value; legacy
aliases are accepted on read and mapped conservatively (an ambiguous "child"
is treated as under 13).
"""

from __future__ import annotations

from typing import Final, Literal, Mapping, Optional

AgeBand = Literal["child_under_13", "teen_13_17", "adult", "older_adult"]

CHILD_UNDER_13: Final = "child_under_13"
TEEN_13_17: Final = "teen_13_17"
ADULT: Final = "adult"
OLDER_ADULT: Final = "older_adult"

AGE_BANDS: Final = (CHILD_UNDER_13, TEEN_13_17, ADULT, OLDER_ADULT)

LEGACY_AGE_BAND_ALIASES: Final[Mapping[str, str]] = {
    "child_u13": CHILD_UNDER_13,
    "under_13": CHILD_UNDER_13,
    "u13": CHILD_UNDER_13,
    "child": CHILD_UNDER_13,
    "teen": TEEN_13_17,
    "older": OLDER_ADULT,
}


def canonical_age_band(value: Optional[str], default: str = ADULT) -> str:
    """Returns the canonical age band for value, mapping legacy aliases.

    Unknown non-empty values are returned normalized (lower-case, underscores)
    so callers can still reject them explicitly.
    """
    if value is None:
        return default
    clean = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    if not clean:
        return default
    return LEGACY_AGE_BAND_ALIASES.get(clean, clean)


def is_child_under_13(value: Optional[str]) -> bool:
    """True when value denotes a child under 13 under any accepted spelling."""
    return canonical_age_band(value) == CHILD_UNDER_13


__all__ = [
    "AgeBand",
    "AGE_BANDS",
    "ADULT",
    "CHILD_UNDER_13",
    "LEGACY_AGE_BAND_ALIASES",
    "OLDER_ADULT",
    "TEEN_13_17",
    "canonical_age_band",
    "is_child_under_13",
]
