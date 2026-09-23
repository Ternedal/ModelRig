"""C11 Temporal Sense for Consciousness Core."""
from __future__ import annotations
import hashlib, json
from typing import Annotated, Any, Literal, Mapping
from pydantic import BaseModel, ConfigDict, Field, ValidationError

UnitInterval=Annotated[float,Field(ge=0.0,le=1.0,strict=True,allow_inf_nan=False)]
NonNegativeInt=Annotated[int,Field(ge=0,strict=True)]
NonEmptyRef=Annotated[str,Field(min_length=1,max_length=256)]
DayPhase=Literal["night","morning","afternoon","evening"]
ClockBasis=Literal["monotonic","wall_clock","sequence"]
ClockAnomaly=Literal["none","wall_clock_backward","runtime_epoch_changed"]

class TemporalContractError(RuntimeError): pass
class StrictModel(BaseModel):
    model_config=ConfigDict(extra="forbid",strict=True,allow_inf_nan=False,frozen=True)

class ClockSample(StrictModel):
    schema: Literal["kaliv-consciousness-core/clock-sample/v1"]
    sample_id: Annotated[str,Field(pattern=r"^clock-[a-f0-9]{32}$")]
    wall_time_unix_ms: NonNegativeInt
    timezone_name: Annotated[str,Field(min_length=1,max_length=128)]
    utc_offset_minutes: Annotated[int,Field(ge=-840,le=840,strict=True)]
    local_hour: Annotated[int,Field(ge=0,le=23,strict=True)]
    monotonic_ms: NonNegativeInt
    runtime_epoch_id: Annotated[str,Field(pattern=r"^epoch-[a-f0-9]{32}$")]
    sampled_sequence: NonNegativeInt
    source_ref: NonEmptyRef
    confidence: UnitInterval
    production_activation: Literal[False]

class TemporalAnchor(StrictModel):
    schema: Literal["kaliv-consciousness-core/temporal-anchor/v1"]
    anchor_id: Annotated[str,Field(pattern=r"^tanch-[a-f0-9]{32}$")]
    event_ref: NonEmptyRef
    wall_time_unix_ms: NonNegativeInt|None
    runtime_epoch_id: Annotated[str,Field(pattern=r"^epoch-[a-f0-9]{32}$")]|None
    monotonic_ms: NonNegativeInt|None
    sequence: NonNegativeInt
    source_refs: Annotated[list[NonEmptyRef],Field(min_length=1,max_length=32)]
    confidence: UnitInterval
    production_activation: Literal[False]

class TemporalRelation(StrictModel):
    schema: Literal["kaliv-consciousness-core/temporal-relation/v1"]
    relation: Literal["BEFORE","AFTER","SAME_WINDOW"]
    elapsed_ms: NonNegativeInt|None
    clock_basis: ClockBasis
    confidence: UnitInterval
    production_activation: Literal[False]

class TemporalState(StrictModel):
    schema: Literal["kaliv-consciousness-core/temporal-state/v1"]
    self_id: Annotated[str,Field(pattern=r"^self-[a-f0-9]{32}$")]
    person_revision: Annotated[str,Field(pattern=r"^person-r[0-9]{4,}$")]
    runtime_epoch_id: Annotated[str,Field(pattern=r"^epoch-[a-f0-9]{32}$")]
    now_anchor: TemporalAnchor
    session_elapsed_ms: NonNegativeInt|None
    continuity_gap_detected: bool
    continuity_gap_ms: NonNegativeInt|None
    clock_anomaly: ClockAnomaly
    local_day_phase: DayPhase
    uncertainty: UnitInterval
    production_activation: Literal[False]

class DeadlineState(StrictModel):
    schema: Literal["kaliv-consciousness-core/deadline-state/v1"]
    orientation: Literal["PAST","PRESENT","FUTURE","UNKNOWN"]
    remaining_ms: NonNegativeInt|None
    overdue_ms: NonNegativeInt|None
    clock_basis: ClockBasis
    scheduling_authority: Literal[False]
    execution_authority: Literal[False]
    production_activation: Literal[False]

class TemporalExperienceState(StrictModel):
    schema: Literal["kaliv-consciousness-core/temporal-experience-state/v1"]
    objective_elapsed_ms: Annotated[int,Field(gt=0,strict=True)]
    event_count: NonNegativeInt
    attention_load: UnitInterval
    duration_salience: Literal["compressed","neutral","expanded"]
    production_activation: Literal[False]

def _digest(v:Mapping[str,Any])->str:
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def _phase(h:int)->DayPhase:
    return "morning" if 5<=h<12 else "afternoon" if 12<=h<17 else "evening" if 17<=h<23 else "night"

def anchor_from_clock(sample:ClockSample|Mapping[str,Any],*,event_ref:str)->TemporalAnchor:
    try: s=sample if isinstance(sample,ClockSample) else ClockSample.model_validate(sample)
    except ValidationError as exc: raise TemporalContractError("invalid ClockSample") from exc
    return TemporalAnchor(schema="kaliv-consciousness-core/temporal-anchor/v1",anchor_id="tanch-"+_digest({"sample":s.sample_id,"event":event_ref})[:32],event_ref=event_ref,wall_time_unix_ms=s.wall_time_unix_ms,runtime_epoch_id=s.runtime_epoch_id,monotonic_ms=s.monotonic_ms,sequence=s.sampled_sequence,source_refs=[s.source_ref],confidence=s.confidence,production_activation=False)

def relate_anchors(left:TemporalAnchor,right:TemporalAnchor,*,same_window_ms:int=1000)->TemporalRelation:
    if left.runtime_epoch_id==right.runtime_epoch_id and left.monotonic_ms is not None and right.monotonic_ms is not None:
        delta=right.monotonic_ms-left.monotonic_ms; basis="monotonic"
        if (right.sequence-left.sequence>0 and delta<0): raise TemporalContractError("monotonic order contradicts sequence")
    elif left.wall_time_unix_ms is not None and right.wall_time_unix_ms is not None:
        delta=right.wall_time_unix_ms-left.wall_time_unix_ms; basis="wall_clock"
    else:
        delta=right.sequence-left.sequence; basis="sequence"
    rel="SAME_WINDOW" if abs(delta)<=same_window_ms and basis!="sequence" else "AFTER" if delta>0 else "BEFORE" if delta<0 else "SAME_WINDOW"
    return TemporalRelation(schema="kaliv-consciousness-core/temporal-relation/v1",relation=rel,elapsed_ms=None if basis=="sequence" else abs(delta),clock_basis=basis,confidence=min(left.confidence,right.confidence),production_activation=False)

def build_temporal_state(*,self_id:str,person_revision:str,current_sample:ClockSample,session_started_anchor:TemporalAnchor,previous_sample:ClockSample|None=None)->TemporalState:
    if previous_sample and current_sample.sampled_sequence<=previous_sample.sampled_sequence: raise TemporalContractError("stale ClockSample")
    anomaly="none"; gap=False; gap_ms=None
    if previous_sample:
        if previous_sample.runtime_epoch_id!=current_sample.runtime_epoch_id:
            anomaly="runtime_epoch_changed"; gap=True
            if current_sample.wall_time_unix_ms>=previous_sample.wall_time_unix_ms: gap_ms=current_sample.wall_time_unix_ms-previous_sample.wall_time_unix_ms
        elif current_sample.wall_time_unix_ms<previous_sample.wall_time_unix_ms: anomaly="wall_clock_backward"
    elapsed=None
    if session_started_anchor.runtime_epoch_id==current_sample.runtime_epoch_id and session_started_anchor.monotonic_ms is not None:
        if current_sample.monotonic_ms<session_started_anchor.monotonic_ms: raise TemporalContractError("monotonic time moved backwards")
        elapsed=current_sample.monotonic_ms-session_started_anchor.monotonic_ms
    return TemporalState(schema="kaliv-consciousness-core/temporal-state/v1",self_id=self_id,person_revision=person_revision,runtime_epoch_id=current_sample.runtime_epoch_id,now_anchor=anchor_from_clock(current_sample,event_ref="consciousness-core:now"),session_elapsed_ms=elapsed,continuity_gap_detected=gap,continuity_gap_ms=gap_ms,clock_anomaly=anomaly,local_day_phase=_phase(current_sample.local_hour),uncertainty=round(1-current_sample.confidence,6),production_activation=False)

def deadline_state(*,now_anchor:TemporalAnchor,deadline_anchor:TemporalAnchor)->DeadlineState:
    r=relate_anchors(now_anchor,deadline_anchor)
    if r.relation=="AFTER": orientation,remaining,overdue="FUTURE",r.elapsed_ms,None
    elif r.relation=="BEFORE": orientation,remaining,overdue="PAST",None,r.elapsed_ms
    else: orientation,remaining,overdue="PRESENT",0,None
    return DeadlineState(schema="kaliv-consciousness-core/deadline-state/v1",orientation=orientation,remaining_ms=remaining,overdue_ms=overdue,clock_basis=r.clock_basis,scheduling_authority=False,execution_authority=False,production_activation=False)

def temporal_experience_state(*,observation_window_ms:int,event_count:int,attention_load:float)->TemporalExperienceState:
    if observation_window_ms<=0 or event_count<0 or not 0<=attention_load<=1: raise TemporalContractError("invalid temporal experience input")
    density=min(1.0,event_count/max(1.0,(observation_window_ms/60000)*12.0))
    score=.65*density+.35*attention_load
    salience="expanded" if score>=.72 else "compressed" if score<=.25 else "neutral"
    return TemporalExperienceState(schema="kaliv-consciousness-core/temporal-experience-state/v1",objective_elapsed_ms=observation_window_ms,event_count=event_count,attention_load=attention_load,duration_salience=salience,production_activation=False)
