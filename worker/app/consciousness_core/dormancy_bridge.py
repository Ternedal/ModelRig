"""C31-D dormancy bridge from verified wake evidence into lived continuity.

The bridge proves a runtime gap was dormancy, never hidden cognition. It joins
existing C12/C17 receipts by reference only and grants no new authority.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .sleep import WakeReceipt
from .wake_cycle import WakeOrientationReceipt, wake_receipt_ref


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
CycleId = Annotated[str, Field(pattern=r"^cycle-[a-f0-9]{32}$")]


class DormancyBridgeError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class DormancyBridgeReceipt(StrictModel):
    schema: Literal["kaliv-consciousness-core/dormancy-bridge-receipt/v1"]
    bridge_id: Annotated[str, Field(pattern=r"^dormancy-bridge-[a-f0-9]{32}$")]
    wake_receipt_ref: NonEmptyRef
    wake_orientation_ref: NonEmptyRef
    self_id: Annotated[str, Field(pattern=r"^self-[a-f0-9]{32}$")]
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    dormancy_kind: Literal["PLANNED_SLEEP", "UNPLANNED_DORMANCY"]
    sleep_id: Annotated[str, Field(pattern=r"^sleep-[a-f0-9]{32}$")] | None
    entry_anchor_ref: NonEmptyRef | None
    wake_anchor_ref: NonEmptyRef
    from_cycle_id: CycleId
    oriented_cycle_id: CycleId
    duration_known: bool
    offline_duration_ms: Annotated[int, Field(ge=0, strict=True)] | None
    offline_duration_upper_bound_ms: Annotated[int, Field(ge=0, strict=True)] | None
    cognition_during_gap: Literal[False]
    explicit_wake_reorientation: Literal[True]
    automatic_goal_resume: Literal[False]
    automatic_loop_resume: Literal[False]
    reference_only: Literal[True]
    identity_authority: Literal[False]
    persistent_state_authority: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    model_authority: Literal[False]
    raw_chain_of_thought_persisted: Literal[False]
    production_activation: Literal[False]


def _canonical_json(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _ref(kind: str, value: Any) -> str:
    return f"{kind}:" + hashlib.sha256(_canonical_json(value)).hexdigest()


def build_dormancy_bridge(
    wake_receipt: WakeReceipt | Mapping[str, Any],
    orientation_receipt: WakeOrientationReceipt | Mapping[str, Any],
) -> DormancyBridgeReceipt:
    """Bind C12 dormancy evidence to the exact C17 wake reorientation."""
    try:
        wake = wake_receipt if isinstance(wake_receipt, WakeReceipt) else WakeReceipt.model_validate(wake_receipt)
        orientation = (
            orientation_receipt
            if isinstance(orientation_receipt, WakeOrientationReceipt)
            else WakeOrientationReceipt.model_validate(orientation_receipt)
        )
    except ValidationError as exc:
        raise DormancyBridgeError("invalid dormancy bridge input") from exc

    expected_wake_ref = wake_receipt_ref(wake)
    if orientation.wake_receipt_ref != expected_wake_ref:
        raise DormancyBridgeError("wake orientation belongs to another WakeReceipt")
    if wake.cognition_during_gap is not False or orientation.cognition_during_gap is not False:
        raise DormancyBridgeError("dormancy bridge cannot claim cognition during the gap")
    if orientation.automatic_goal_resume is not False or orientation.automatic_loop_resume is not False:
        raise DormancyBridgeError("wake reorientation cannot auto-resume goals or loops")

    seed = {
        "wake_receipt_ref": expected_wake_ref,
        "wake_orientation_ref": _ref("wake-orientation", orientation),
        "self_id": wake.self_id,
        "person_revision": wake.person_revision,
        "from_cycle_id": orientation.from_cycle_id,
        "oriented_cycle_id": orientation.oriented_cycle_id,
    }
    return DormancyBridgeReceipt(
        schema="kaliv-consciousness-core/dormancy-bridge-receipt/v1",
        bridge_id="dormancy-bridge-" + hashlib.sha256(_canonical_json(seed)).hexdigest()[:32],
        wake_receipt_ref=seed["wake_receipt_ref"],
        wake_orientation_ref=seed["wake_orientation_ref"],
        self_id=wake.self_id,
        person_revision=wake.person_revision,
        dormancy_kind=wake.dormancy_kind,
        sleep_id=wake.sleep_id,
        entry_anchor_ref=wake.entry_anchor_ref,
        wake_anchor_ref="temporal-anchor:" + wake.wake_anchor.anchor_id,
        from_cycle_id=orientation.from_cycle_id,
        oriented_cycle_id=orientation.oriented_cycle_id,
        duration_known=wake.duration_known,
        offline_duration_ms=wake.offline_duration_ms,
        offline_duration_upper_bound_ms=wake.offline_duration_upper_bound_ms,
        cognition_during_gap=False,
        explicit_wake_reorientation=True,
        automatic_goal_resume=False,
        automatic_loop_resume=False,
        reference_only=True,
        identity_authority=False,
        persistent_state_authority=False,
        durable_memory_write_authority=False,
        execution_authority=False,
        scheduling_authority=False,
        model_authority=False,
        raw_chain_of_thought_persisted=False,
        production_activation=False,
    )
