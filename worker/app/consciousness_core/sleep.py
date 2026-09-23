"""C12 sleep/dormancy lifecycle for Consciousness Core.

A powered-off process performs no cognition. This module represents the boundary
before shutdown and the continuity receipt after startup. It owns no scheduler,
tool execution, durable memory store, or background compute.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .liveness import RuntimeLivenessWitness, runtime_liveness_witness_ref
from .temporal import TemporalAnchor, TemporalContractError, relate_anchors

NonEmptyRef=Annotated[str,Field(min_length=1,max_length=256)]
NonNegativeInt=Annotated[int,Field(ge=0,strict=True)]
UnitInterval=Annotated[float,Field(ge=0.0,le=1.0,strict=True,allow_inf_nan=False)]
SelfStateRevision=Annotated[int,Field(ge=1,strict=True)]

SleepReason=Literal["app_closed","host_shutdown","suspend"]
DormancyKind=Literal["PLANNED_SLEEP","UNPLANNED_DORMANCY"]
WakeState=Literal["WAKING"]


class SleepContractError(RuntimeError): pass


class StrictModel(BaseModel):
    model_config=ConfigDict(extra="forbid",strict=True,allow_inf_nan=False,frozen=True)


class SleepRecord(StrictModel):
    schema: Literal["kaliv-consciousness-core/sleep-record/v1"]
    sleep_id: Annotated[str,Field(pattern=r"^sleep-[a-f0-9]{32}$")]
    self_id: Annotated[str,Field(pattern=r"^self-[a-f0-9]{32}$")]
    person_revision: Annotated[str,Field(pattern=r"^person-r[0-9]{4,}$")]
    durable_self_state_ref: NonEmptyRef|None=None
    durable_self_state_revision: SelfStateRevision|None=None
    reason: SleepReason
    entry_anchor: TemporalAnchor
    open_goal_refs: Annotated[list[NonEmptyRef],Field(max_length=64)]
    open_loop_refs: Annotated[list[NonEmptyRef],Field(max_length=64)]
    pending_review_refs: Annotated[list[NonEmptyRef],Field(max_length=64)]
    clean_shutdown: Literal[True]
    cognition_continues: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    durable_memory_write_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_self_state_binding(self) -> "SleepRecord":
        if (
            self.durable_self_state_ref is None
        ) != (
            self.durable_self_state_revision is None
        ):
            raise ValueError(
                "sleep durable SelfState ref/revision must be both present or absent"
            )
        return self


class WakeReceipt(StrictModel):
    schema: Literal["kaliv-consciousness-core/wake-receipt/v1"]
    wake_id: Annotated[str,Field(pattern=r"^wake-[a-f0-9]{32}$")]
    self_id: Annotated[str,Field(pattern=r"^self-[a-f0-9]{32}$")]
    person_revision: Annotated[str,Field(pattern=r"^person-r[0-9]{4,}$")]
    durable_self_state_ref: NonEmptyRef|None=None
    durable_self_state_revision: SelfStateRevision|None=None
    sleep_id: Annotated[str,Field(pattern=r"^sleep-[a-f0-9]{32}$")]|None
    dormancy_kind: DormancyKind
    entry_anchor_ref: NonEmptyRef|None
    wake_anchor: TemporalAnchor
    offline_duration_ms: NonNegativeInt|None
    duration_confidence: UnitInterval
    duration_known: bool
    last_known_alive_witness_ref: NonEmptyRef|None=None
    last_known_alive_anchor_ref: NonEmptyRef|None=None
    offline_duration_upper_bound_ms: NonNegativeInt|None=None
    offline_duration_upper_bound_confidence: UnitInterval=0.0
    continuity_preserved: Literal[True]
    cognition_during_gap: Literal[False]
    wake_state: WakeState
    resume_goal_refs: Annotated[list[NonEmptyRef],Field(max_length=64)]
    resume_open_loop_refs: Annotated[list[NonEmptyRef],Field(max_length=64)]
    pending_review_refs: Annotated[list[NonEmptyRef],Field(max_length=64)]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    durable_memory_write_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_self_state_binding(self) -> "WakeReceipt":
        if (
            self.durable_self_state_ref is None
        ) != (
            self.durable_self_state_revision is None
        ):
            raise ValueError(
                "wake durable SelfState ref/revision must be both present or absent"
            )
        return self

    @model_validator(mode="after")
    def exact_liveness_bound(self) -> "WakeReceipt":
        refs_present = (
            self.last_known_alive_witness_ref is not None,
            self.last_known_alive_anchor_ref is not None,
        )
        if refs_present[0] != refs_present[1]:
            raise ValueError(
                "wake liveness witness/anchor refs must be both present or absent"
            )
        if self.dormancy_kind != "UNPLANNED_DORMANCY":
            if (
                any(refs_present)
                or self.offline_duration_upper_bound_ms is not None
                or self.offline_duration_upper_bound_confidence != 0.0
            ):
                raise ValueError(
                    "planned sleep cannot carry unplanned liveness evidence"
                )
            return self

        if self.offline_duration_upper_bound_ms is not None:
            if not all(refs_present):
                raise ValueError(
                    "unplanned duration upper bound requires liveness evidence"
                )
            if self.offline_duration_upper_bound_confidence <= 0.0:
                raise ValueError(
                    "duration upper bound requires positive confidence"
                )
            if self.duration_known or self.offline_duration_ms is not None:
                raise ValueError(
                    "duration upper bound cannot become exact offline duration"
                )
        elif self.offline_duration_upper_bound_confidence != 0.0:
            raise ValueError(
                "duration upper-bound confidence requires an upper bound"
            )
        return self


def _digest(payload:Mapping[str,Any])->str:
    raw=json.dumps(payload,sort_keys=True,separators=(",",":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def prepare_sleep(
    *,
    self_id:str,
    person_revision:str,
    entry_anchor:TemporalAnchor|Mapping[str,Any],
    reason:SleepReason,
    durable_self_state_ref:str|None=None,
    durable_self_state_revision:int|None=None,
    open_goal_refs:list[str]|None=None,
    open_loop_refs:list[str]|None=None,
    pending_review_refs:list[str]|None=None,
)->SleepRecord:
    """Create the clean shutdown boundary before the process actually exits."""
    try:
        anchor=entry_anchor if isinstance(entry_anchor,TemporalAnchor) else TemporalAnchor.model_validate(entry_anchor)
    except ValidationError as exc:
        raise SleepContractError("invalid sleep entry anchor") from exc
    seed={"self_id":self_id,"person_revision":person_revision,"anchor":anchor.anchor_id,"reason":reason}
    if durable_self_state_ref is not None or durable_self_state_revision is not None:
        seed["durable_self_state_ref"]=durable_self_state_ref
        seed["durable_self_state_revision"]=durable_self_state_revision
    return SleepRecord(
        schema="kaliv-consciousness-core/sleep-record/v1",
        sleep_id="sleep-"+_digest(seed)[:32],
        self_id=self_id,
        person_revision=person_revision,
        durable_self_state_ref=durable_self_state_ref,
        durable_self_state_revision=durable_self_state_revision,
        reason=reason,
        entry_anchor=anchor,
        open_goal_refs=list(dict.fromkeys(open_goal_refs or []))[:64],
        open_loop_refs=list(dict.fromkeys(open_loop_refs or []))[:64],
        pending_review_refs=list(dict.fromkeys(pending_review_refs or []))[:64],
        clean_shutdown=True,
        cognition_continues=False,
        execution_authority=False,
        scheduling_authority=False,
        durable_memory_write_authority=False,
        production_activation=False,
    )


def wake_from_sleep(
    *,
    wake_anchor:TemporalAnchor|Mapping[str,Any],
    sleep_record:SleepRecord|Mapping[str,Any]|None=None,
    last_known_anchor:TemporalAnchor|Mapping[str,Any]|None=None,
    expected_self_id:str|None=None,
    expected_person_revision:str|None=None,
)->WakeReceipt:
    """Re-orient after startup without pretending cognition happened offline."""
    try:
        wake=wake_anchor if isinstance(wake_anchor,TemporalAnchor) else TemporalAnchor.model_validate(wake_anchor)
        sleep=None if sleep_record is None else sleep_record if isinstance(sleep_record,SleepRecord) else SleepRecord.model_validate(sleep_record)
        last=None if last_known_anchor is None else last_known_anchor if isinstance(last_known_anchor,TemporalAnchor) else TemporalAnchor.model_validate(last_known_anchor)
    except ValidationError as exc:
        raise SleepContractError("invalid wake input") from exc

    if sleep is None and last is None:
        raise SleepContractError("wake requires SleepRecord or prior anchor")

    if sleep is not None:
        self_id=sleep.self_id
        person_revision=sleep.person_revision
        durable_self_state_ref=sleep.durable_self_state_ref
        durable_self_state_revision=sleep.durable_self_state_revision
        entry=sleep.entry_anchor
        kind:DormancyKind="PLANNED_SLEEP"
        goal_refs=sleep.open_goal_refs
        loop_refs=sleep.open_loop_refs
        review_refs=sleep.pending_review_refs
        sleep_id=sleep.sleep_id
    else:
        if expected_self_id is None or expected_person_revision is None:
            raise SleepContractError("unplanned dormancy requires expected identity binding")
        self_id=expected_self_id
        person_revision=expected_person_revision
        durable_self_state_ref=None
        durable_self_state_revision=None
        entry=last
        kind="UNPLANNED_DORMANCY"
        goal_refs=[]; loop_refs=[]; review_refs=[]; sleep_id=None

    if expected_self_id is not None and self_id!=expected_self_id:
        raise SleepContractError("sleep record belongs to another self")
    if expected_person_revision is not None and person_revision!=expected_person_revision:
        raise SleepContractError("sleep record belongs to another Person Revision")

    duration=None; confidence=0.0; known=False
    # Offline sleep normally crosses runtime epochs, so elapsed duration must
    # bridge through trusted wall-clock evidence. A backwards wall clock is
    # never accepted as a tiny "same window" sleep: keep duration unknown
    # rather than inventing time that did not progress.
    wall_clock_rolled_back = (
        entry.runtime_epoch_id != wake.runtime_epoch_id
        and entry.wall_time_unix_ms is not None
        and wake.wall_time_unix_ms is not None
        and wake.wall_time_unix_ms < entry.wall_time_unix_ms
    )
    if not wall_clock_rolled_back:
        try:
            relation=relate_anchors(entry,wake)
            if relation.relation in {"AFTER","SAME_WINDOW"} and relation.elapsed_ms is not None:
                duration=relation.elapsed_ms
                confidence=relation.confidence
                known=True
        except TemporalContractError:
            pass

    seed={"self_id":self_id,"person_revision":person_revision,"wake":wake.anchor_id,"sleep_id":sleep_id,"kind":kind}
    return WakeReceipt(
        schema="kaliv-consciousness-core/wake-receipt/v1",
        wake_id="wake-"+_digest(seed)[:32],
        self_id=self_id,
        person_revision=person_revision,
        durable_self_state_ref=durable_self_state_ref,
        durable_self_state_revision=durable_self_state_revision,
        sleep_id=sleep_id,
        dormancy_kind=kind,
        entry_anchor_ref=f"temporal-anchor:{entry.anchor_id}",
        wake_anchor=wake,
        offline_duration_ms=duration,
        duration_confidence=confidence,
        duration_known=known,
        continuity_preserved=True,
        cognition_during_gap=False,
        wake_state="WAKING",
        resume_goal_refs=goal_refs,
        resume_open_loop_refs=loop_refs,
        pending_review_refs=review_refs,
        execution_authority=False,
        scheduling_authority=False,
        durable_memory_write_authority=False,
        production_activation=False,
    )



def wake_from_unplanned_restart(
    *,
    wake_anchor: TemporalAnchor | Mapping[str, Any],
    self_id: str,
    person_revision: str,
    source_ref: str,
    liveness_witness: RuntimeLivenessWitness | Mapping[str, Any] | None = None,
) -> WakeReceipt:
    """Represent an unclean restart without inventing a crash timestamp."""
    try:
        wake = (
            wake_anchor
            if isinstance(wake_anchor, TemporalAnchor)
            else TemporalAnchor.model_validate(wake_anchor)
        )
        witness = (
            None
            if liveness_witness is None
            else liveness_witness
            if isinstance(liveness_witness, RuntimeLivenessWitness)
            else RuntimeLivenessWitness.model_validate(liveness_witness)
        )
    except ValidationError as exc:
        raise SleepContractError("invalid unplanned wake input") from exc

    if not isinstance(source_ref, str) or not source_ref.strip():
        raise SleepContractError("unplanned wake source_ref is required")

    witness_ref = None
    alive_anchor_ref = None
    upper_bound = None
    upper_bound_confidence = 0.0
    if witness is not None:
        if witness.self_id != self_id:
            raise SleepContractError(
                "liveness witness belongs to another self"
            )
        if witness.person_revision != person_revision:
            raise SleepContractError(
                "liveness witness belongs to another Person Revision"
            )
        witness_ref = runtime_liveness_witness_ref(witness)
        alive_anchor_ref = "temporal-anchor:" + witness.anchor.anchor_id

        # A last-known-alive witness can bound the possible outage window but
        # cannot identify the crash instant. Across runtime epochs, only a
        # forward trusted wall clock may provide the bound.
        wall_clock_rolled_back = (
            witness.anchor.runtime_epoch_id != wake.runtime_epoch_id
            and witness.anchor.wall_time_unix_ms is not None
            and wake.wall_time_unix_ms is not None
            and wake.wall_time_unix_ms
            < witness.anchor.wall_time_unix_ms
        )
        if not wall_clock_rolled_back:
            try:
                relation = relate_anchors(witness.anchor, wake)
            except TemporalContractError:
                relation = None
            if (
                relation is not None
                and relation.relation in {"AFTER", "SAME_WINDOW"}
                and relation.elapsed_ms is not None
            ):
                upper_bound = relation.elapsed_ms
                upper_bound_confidence = relation.confidence

    seed = {
        "self_id": self_id,
        "person_revision": person_revision,
        "wake": wake.anchor_id,
        "source_ref": source_ref,
        "kind": "UNPLANNED_DORMANCY",
        "liveness_witness_ref": witness_ref,
    }
    return WakeReceipt(
        schema="kaliv-consciousness-core/wake-receipt/v1",
        wake_id="wake-" + _digest(seed)[:32],
        self_id=self_id,
        person_revision=person_revision,
        durable_self_state_ref=None,
        durable_self_state_revision=None,
        sleep_id=None,
        dormancy_kind="UNPLANNED_DORMANCY",
        entry_anchor_ref=None,
        wake_anchor=wake,
        offline_duration_ms=None,
        duration_confidence=0.0,
        duration_known=False,
        last_known_alive_witness_ref=witness_ref,
        last_known_alive_anchor_ref=alive_anchor_ref,
        offline_duration_upper_bound_ms=upper_bound,
        offline_duration_upper_bound_confidence=upper_bound_confidence,
        continuity_preserved=True,
        cognition_during_gap=False,
        wake_state="WAKING",
        resume_goal_refs=[],
        resume_open_loop_refs=[],
        pending_review_refs=[],
        execution_authority=False,
        scheduling_authority=False,
        durable_memory_write_authority=False,
        production_activation=False,
    )
