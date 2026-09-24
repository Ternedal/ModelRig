"""Low-level canonical SelfState reference helper.

This module exists below the cognitive-cycle/continuity graph so lifecycle and
liveness code can bind durable SelfState without importing cycle.py.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from pydantic import BaseModel

from .self_state import PersistentSelfState


def _canonical_json(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def self_state_ref(
    state: PersistentSelfState | Mapping[str, Any],
) -> str:
    parsed = (
        state
        if isinstance(state, PersistentSelfState)
        else PersistentSelfState.model_validate(state)
    )
    digest = hashlib.sha256(_canonical_json(parsed)).hexdigest()
    return "self-state:" + digest
