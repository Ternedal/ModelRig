"""C31-D2 restart dormancy evidence from C12 wake + C19 session bootstrap.

This is the process-restart counterpart to the C17 dormancy bridge. It binds an
authoritative WakeReceipt to the exact WAKE_REORIENTATION SessionBootstrapReceipt
used by production restart bootstrap. It grants no new runtime authority.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .session_bootstrap import SessionBootstrapReceipt
from .sleep import WakeReceipt
from .wake_cycle import wake_receipt_ref

NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]


class RestartDormancyEvidenceError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class RestartDormancyReceipt(StrictModel):
    schema: Literal["kaliv-consciousness-core/restart-dormancy-receipt/v1"]
    qualification_id: Annotated[str, Field(pattern=r"^restart-dormancy-[a-f0-9]{32}$")]
    wake_receipt_ref: NonEmptyRef
    session_bootstrap_receipt_ref: NonEmptyRef
    self_id: Annotated[str, Field(pattern=r"^self-[a-f0-9]{32}$")]
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    dormancy_kind: Literal["PLANNED_SLEEP", "UNPLANNED_DORMANCY"]
    sleep_id: Annotated[str, Field(pattern=r"^sleep-[a-f0-9]{32}$")] | None
    entry_anchor_ref: NonEmptyRef | None
    wake_anchor_ref: NonEmptyRef
    bootstrap_kind: Literal["WAKE_REORIENTATION"]
    previous_self_state_ref: NonEmptyRef
    next_self_state_ref: NonEmptyRef
    fresh_world_state_ref: NonEmptyRef
    fresh_workspace_ref: NonEmptyRef
    duration_known: bool
    offline_duration_ms: Annotated[int, Field(ge=0, strict=True)] | None
    offline_duration_upper_bound_ms: Annotated[int, Field(ge=0, strict=True)] | None
    cognition_during_gap: Literal[False]
    explicit_wake_reorientation: Literal[True]
    prior_world_restored: Literal[False]
    prior_workspace_restored: Literal[False]
    reference_only: Literal[True]
    identity_authority: Literal[False]
    persistent_state_authority: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    model_authority: Literal[False]
    raw_chain_of_thought_persisted: Literal[False]
    production_activation: Literal[False]


def _canonical(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _ref(kind: str, value: Any) -> str:
    return f"{kind}:" + hashlib.sha256(_canonical(value)).hexdigest()


def build_restart_dormancy_receipt(
    wake_receipt: WakeReceipt | Mapping[str, Any],
    session_bootstrap_receipt: SessionBootstrapReceipt | Mapping[str, Any],
) -> RestartDormancyReceipt:
    try:
        wake = (
            wake_receipt
            if isinstance(wake_receipt, WakeReceipt)
            else WakeReceipt.model_validate(wake_receipt)
        )
        bootstrap = (
            session_bootstrap_receipt
            if isinstance(session_bootstrap_receipt, SessionBootstrapReceipt)
            else SessionBootstrapReceipt.model_validate(session_bootstrap_receipt)
        )
    except ValidationError as exc:
        raise RestartDormancyEvidenceError("invalid restart dormancy input") from exc

    if bootstrap.bootstrap_kind != "WAKE_REORIENTATION":
        raise RestartDormancyEvidenceError(
            "restart evidence requires WAKE_REORIENTATION bootstrap"
        )
    expected_wake_ref = wake_receipt_ref(wake)
    if bootstrap.wake_receipt_ref != expected_wake_ref:
        raise RestartDormancyEvidenceError(
            "session bootstrap belongs to another WakeReceipt"
        )
    if bootstrap.self_id != wake.self_id:
        raise RestartDormancyEvidenceError(
            "session bootstrap belongs to another Self identity"
        )
    if bootstrap.person_revision != wake.person_revision:
        raise RestartDormancyEvidenceError(
            "session bootstrap belongs to another Person revision"
        )
    if wake.cognition_during_gap is not False or bootstrap.cognition_during_gap is not False:
        raise RestartDormancyEvidenceError(
            "restart evidence cannot claim cognition during the gap"
        )
    if bootstrap.identity_unchanged is not True:
        raise RestartDormancyEvidenceError(
            "restart bootstrap did not preserve identity"
        )
    if bootstrap.prior_world_restored is not False or bootstrap.prior_workspace_restored is not False:
        raise RestartDormancyEvidenceError(
            "restart bootstrap may not restore prior transient world/workspace"
        )

    bootstrap_ref = _ref("session-bootstrap-receipt", bootstrap)
    seed = {
        "wake_receipt_ref": expected_wake_ref,
        "session_bootstrap_receipt_ref": bootstrap_ref,
        "self_id": wake.self_id,
        "person_revision": wake.person_revision,
    }
    return RestartDormancyReceipt(
        schema="kaliv-consciousness-core/restart-dormancy-receipt/v1",
        qualification_id=(
            "restart-dormancy-" + hashlib.sha256(_canonical(seed)).hexdigest()[:32]
        ),
        wake_receipt_ref=expected_wake_ref,
        session_bootstrap_receipt_ref=bootstrap_ref,
        self_id=wake.self_id,
        person_revision=wake.person_revision,
        dormancy_kind=wake.dormancy_kind,
        sleep_id=wake.sleep_id,
        entry_anchor_ref=wake.entry_anchor_ref,
        wake_anchor_ref="temporal-anchor:" + wake.wake_anchor.anchor_id,
        bootstrap_kind="WAKE_REORIENTATION",
        previous_self_state_ref=bootstrap.previous_self_state_ref,
        next_self_state_ref=bootstrap.next_self_state_ref,
        fresh_world_state_ref=bootstrap.fresh_world_state_ref,
        fresh_workspace_ref=bootstrap.fresh_workspace_ref,
        duration_known=wake.duration_known,
        offline_duration_ms=wake.offline_duration_ms,
        offline_duration_upper_bound_ms=wake.offline_duration_upper_bound_ms,
        cognition_during_gap=False,
        explicit_wake_reorientation=True,
        prior_world_restored=False,
        prior_workspace_restored=False,
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
