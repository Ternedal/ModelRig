"""Kaliv rename: read KALIV_* env vars, fall back to the old ALVA_* names.

The app was renamed Alva -> Kaliv (Anders' decision 2026-07-09). The engine
stays ModelRig. Anders' rig has ALVA_* variables in muscle memory, shell
history and HANDOFF.md, so a hard rename would break a working setup for no
gain. Precedence: KALIV_X wins if set, else ALVA_X, else the default.

Deliberately narrow: this covers the Voice env vars only. MODELRIG_* names
belong to the engine and do NOT change.
"""
from __future__ import annotations

import os
from typing import Optional


def env(suffix: str, default: Optional[str] = None) -> Optional[str]:
    """Look up KALIV_<suffix>, then ALVA_<suffix>, then default.

    An empty string counts as "set" -- the caller asked for an empty value.
    """
    val = os.environ.get(f"KALIV_{suffix}")
    if val is not None:
        return val
    val = os.environ.get(f"ALVA_{suffix}")
    if val is not None:
        return val
    return default


def legacy_names_in_use() -> list[str]:
    """Which old ALVA_* names are set without a KALIV_* equivalent.

    Used by the status endpoints so a migration is visible rather than silent.
    """
    out: list[str] = []
    for key in os.environ:
        if key.startswith("ALVA_") and f"KALIV_{key[5:]}" not in os.environ:
            out.append(key)
    return sorted(out)
