"""C26-A authoritative wake-followup CognitionEvent projection.

A validated WakeReceipt is continuity evidence, not cognition. This module turns
that receipt into one bounded pending attention event; it does not run a model,
consume the event, persist state or schedule work.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from pydantic import BaseModel, ValidationError

from .sleep import WakeReceipt
from .supervisor import CognitionEvent


class WakeFollowupAdmissionError(RuntimeError):
    pass


WAKE_FOLLOWUP_SALIENCE = 0.96


def _canonical_json(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def wake_receipt_ref(wake: WakeReceipt | Mapping[str, Any]) -> str:
    try:
        receipt = (
            wake
            if isinstance(wake, WakeReceipt)
            else WakeReceipt.model_validate(wake)
        )
    except ValidationError as exc:
        raise WakeFollowupAdmissionError("invalid WakeReceipt") from exc
    return "wake-receipt:" + hashlib.sha256(
        _canonical_json(receipt)
    ).hexdigest()


def wake_followup_event_id(
    wake: WakeReceipt | Mapping[str, Any],
) -> str:
    reference = wake_receipt_ref(wake)
    return "cevt-" + hashlib.sha256(
        ("wake-followup-v1|" + reference).encode("utf-8")
    ).hexdigest()[:32]


def _wake_summary(wake: WakeReceipt) -> str:
    duration = (
        f"{wake.offline_duration_ms} ms"
        if wake.duration_known and wake.offline_duration_ms is not None
        else "unknown"
    )
    liveness = ""
    if wake.offline_duration_upper_bound_ms is not None:
        liveness = (
            " Last-known-alive evidence bounds the possible offline duration "
            f"to at most {wake.offline_duration_upper_bound_ms} ms; this is "
            "not a crash timestamp."
        )
    return (
        f"Wake reorientation after {wake.dormancy_kind}; offline duration is "
        f"{duration}; verified continuity states that cognition did not "
        "continue during the offline gap."
        + liveness
    )


def build_wake_followup_event(
    wake: WakeReceipt | Mapping[str, Any],
    *,
    expected_self_id: str,
    expected_person_revision: str,
) -> CognitionEvent:
    """Project one identity-bound WakeReceipt into one deterministic event."""
    try:
        receipt = (
            wake
            if isinstance(wake, WakeReceipt)
            else WakeReceipt.model_validate(wake)
        )
    except ValidationError as exc:
        raise WakeFollowupAdmissionError("invalid WakeReceipt") from exc

    if receipt.self_id != expected_self_id:
        raise WakeFollowupAdmissionError(
            "WakeReceipt belongs to another self"
        )
    if receipt.person_revision != expected_person_revision:
        raise WakeFollowupAdmissionError(
            "WakeReceipt belongs to another Person Revision"
        )
    if receipt.cognition_during_gap is not False:
        raise WakeFollowupAdmissionError(
            "WakeReceipt may not claim cognition during offline gap"
        )

    reference = wake_receipt_ref(receipt)
    return CognitionEvent(
        schema="kaliv-consciousness-core/cognition-event/v1",
        event_id=wake_followup_event_id(receipt),
        kind="wake_followup",
        source_ref=reference,
        summary=_wake_summary(receipt),
        salience=WAKE_FOLLOWUP_SALIENCE,
        observed_sequence=receipt.wake_anchor.sequence,
        production_activation=False,
    )
