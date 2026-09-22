"""C19-A authoritative runtime session bootstrap for Consciousness Core.

PersistentSelfState survives process restarts; RuntimeWorldState and
CognitiveWorkspace intentionally do not. This module creates a fresh bounded
runtime session without pretending the previous transient objects were restored.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .contracts import PersonalitySnapshot
from .cycle import (
    CognitiveWorkspace,
    RuntimeWorldState,
    WorkspaceCandidate,
    WorldObservation,
    build_workspace,
    self_state_ref,
    workspace_ref,
    world_state_ref,
)
from .self_state import PersistentSelfState, advance_self_state, verify_active_person
from .sleep import WakeReceipt


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
CycleId = Annotated[str, Field(pattern=r"^cycle-[a-f0-9]{32}$")]
CandidateId = Annotated[str, Field(pattern=r"^wc-[a-f0-9]{32}$")]


class SessionBootstrapError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class ActivePersonBindingSnapshot(StrictModel):
    schema: Literal["kaliv-consciousness-core/active-person-binding/v1"]
    person_id: Annotated[str, Field(pattern=r"^person-[a-f0-9]{32}$")]
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    body_revision: Annotated[str, Field(pattern=r"^body-r[0-9]{4,}$")]
    voice_revision: Annotated[str, Field(pattern=r"^voice-r[0-9]{4,}$")]
    personality_revision: Annotated[
        str,
        Field(pattern=r"^personality-r[0-9]{4,}$"),
    ]
    body_source_ref: NonEmptyRef
    voice_source_ref: NonEmptyRef
    registry_source_ref: NonEmptyRef
    production_activation: Literal[False]


class SessionBootstrapReceipt(StrictModel):
    schema: Literal["kaliv-consciousness-core/session-bootstrap-receipt/v1"]
    bootstrap_kind: Literal["RUNTIME_START", "WAKE_REORIENTATION"]
    bootstrap_source_ref: NonEmptyRef
    wake_receipt_ref: NonEmptyRef | None
    previous_self_state_ref: NonEmptyRef
    next_self_state_ref: NonEmptyRef
    previous_world_state_ref: NonEmptyRef
    previous_workspace_ref: NonEmptyRef
    fresh_world_state_ref: NonEmptyRef
    fresh_workspace_ref: NonEmptyRef
    personality_snapshot_ref: NonEmptyRef
    self_id: Annotated[str, Field(pattern=r"^self-[a-f0-9]{32}$")]
    person_id: Annotated[str, Field(pattern=r"^person-[a-f0-9]{32}$")]
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    self_revision_before: Annotated[int, Field(ge=1, strict=True)]
    self_revision_after: Annotated[int, Field(ge=2, strict=True)]
    prior_world_restored: Literal[False]
    prior_workspace_restored: Literal[False]
    identity_unchanged: Literal[True]
    active_goal_bindings_unchanged: Literal[True]
    active_intention_bindings_unchanged: Literal[True]
    affect_unchanged: Literal[True]
    durable_uncertainties_unchanged: Literal[True]
    last_experience_binding_unchanged: Literal[True]
    cognition_during_gap: Literal[False] | None
    model_calls: Literal[0]
    self_state_store_write_applied: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    production_activation: Literal[False]


class RuntimeSessionContext(StrictModel):
    schema: Literal["kaliv-consciousness-core/runtime-session-context/v1"]
    state: PersistentSelfState
    world: RuntimeWorldState
    workspace: CognitiveWorkspace
    personality_snapshot: PersonalitySnapshot
    receipt: SessionBootstrapReceipt
    production_activation: Literal[False]


def _canonical_json(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _ref(kind: str, value: Any) -> str:
    return f"{kind}:{_digest(value)}"


def active_person_binding_from_registry(
    bindings: Mapping[str, Any],
    *,
    registry_source_ref: str,
) -> ActivePersonBindingSnapshot:
    """Project PersonRegistry.active_bindings() into a strict Core snapshot."""
    if not isinstance(bindings, Mapping):
        raise SessionBootstrapError("active Person binding must be a mapping")

    body = bindings.get("body")
    voice = bindings.get("voice")
    personality = bindings.get("personality")
    if not isinstance(body, Mapping):
        raise SessionBootstrapError("active Person binding has no body revision")
    if not isinstance(voice, Mapping):
        raise SessionBootstrapError("active Person binding has no voice revision")
    if not isinstance(personality, Mapping):
        raise SessionBootstrapError(
            "active Person binding has no personality revision"
        )

    try:
        return ActivePersonBindingSnapshot(
            schema="kaliv-consciousness-core/active-person-binding/v1",
            person_id=str(bindings["person_id"]),
            person_revision=str(bindings["person_revision"]),
            body_revision=str(body["id"]),
            voice_revision=str(voice["id"]),
            personality_revision=str(personality["id"]),
            body_source_ref=f"bodyrig:{body['source_id']}",
            voice_source_ref=f"voicerig:{voice['source_id']}",
            registry_source_ref=registry_source_ref,
            production_activation=False,
        )
    except (KeyError, ValidationError, TypeError, ValueError) as exc:
        raise SessionBootstrapError("invalid active Person registry binding") from exc


def active_person_binding_ref(
    binding: ActivePersonBindingSnapshot | Mapping[str, Any],
) -> str:
    try:
        value = (
            binding
            if isinstance(binding, ActivePersonBindingSnapshot)
            else ActivePersonBindingSnapshot.model_validate(binding)
        )
    except ValidationError as exc:
        raise SessionBootstrapError("invalid active Person binding") from exc
    return _ref("active-person-binding", value)


def personality_snapshot_ref(
    snapshot: PersonalitySnapshot | Mapping[str, Any],
) -> str:
    try:
        value = (
            snapshot
            if isinstance(snapshot, PersonalitySnapshot)
            else PersonalitySnapshot.model_validate(snapshot)
        )
    except ValidationError as exc:
        raise SessionBootstrapError("invalid PersonalitySnapshot") from exc
    return _ref("personality-snapshot", value)


def _wake_receipt_ref(wake: WakeReceipt) -> str:
    return _ref("wake-receipt", wake)


def _observation_id(role: str, source_ref: str) -> str:
    return "obs-" + _digest({"role": role, "source_ref": source_ref})[:32]


def _candidate_id(role: str, source_ref: str) -> str:
    return "wc-" + _digest({"role": role, "source_ref": source_ref})[:32]


def _fresh_world_id(
    *,
    state_reference: str,
    bootstrap_source_ref: str,
    wake_reference: str | None,
) -> str:
    return "world-" + _digest(
        {
            "self_state_ref": state_reference,
            "bootstrap_source_ref": bootstrap_source_ref,
            "wake_receipt_ref": wake_reference,
            "transition": "runtime-session-bootstrap-v1",
        }
    )[:32]


def _fresh_cycle_id(
    *,
    state_reference: str,
    bootstrap_source_ref: str,
    wake_reference: str | None,
) -> str:
    return "cycle-" + _digest(
        {
            "self_state_ref": state_reference,
            "bootstrap_source_ref": bootstrap_source_ref,
            "wake_receipt_ref": wake_reference,
            "transition": "runtime-session-workspace-v1",
        }
    )[:32]


def _wake_summary(wake: WakeReceipt) -> str:
    if wake.duration_known and wake.offline_duration_ms is not None:
        duration = f"{wake.offline_duration_ms} ms"
    else:
        duration = "unknown"
    return (
        f"Runtime resumed after {wake.dormancy_kind}; offline duration is "
        f"{duration}; the verified wake receipt states that cognition did not "
        "continue during the gap."
    )


def bootstrap_runtime_session(
    *,
    persistent_state: PersistentSelfState | Mapping[str, Any],
    active_person: ActivePersonBindingSnapshot | Mapping[str, Any],
    bootstrap_source_ref: str,
    wake_receipt: WakeReceipt | Mapping[str, Any] | None = None,
    max_active: int = 8,
) -> RuntimeSessionContext:
    """Bind durable identity continuity to a fresh transient runtime context."""
    try:
        state = (
            persistent_state
            if isinstance(persistent_state, PersistentSelfState)
            else PersistentSelfState.model_validate(persistent_state)
        )
        person = (
            active_person
            if isinstance(active_person, ActivePersonBindingSnapshot)
            else ActivePersonBindingSnapshot.model_validate(active_person)
        )
        wake = (
            None
            if wake_receipt is None
            else wake_receipt
            if isinstance(wake_receipt, WakeReceipt)
            else WakeReceipt.model_validate(wake_receipt)
        )
    except ValidationError as exc:
        raise SessionBootstrapError("invalid runtime session bootstrap input") from exc

    if not isinstance(bootstrap_source_ref, str) or not bootstrap_source_ref.strip():
        raise SessionBootstrapError("bootstrap_source_ref is required")
    if isinstance(max_active, bool) or not isinstance(max_active, int):
        raise SessionBootstrapError("max_active must be an integer")
    if max_active < 1 or max_active > 16:
        raise SessionBootstrapError("max_active must be between 1 and 16")

    try:
        verify_active_person(
            state,
            active_person_id=person.person_id,
            active_person_revision=person.person_revision,
        )
    except Exception as exc:
        raise SessionBootstrapError(
            "active Person binding does not match durable SelfState"
        ) from exc

    wake_reference: str | None = None
    if wake is not None:
        if wake.self_id != state.self_id:
            raise SessionBootstrapError("WakeReceipt belongs to another self")
        if wake.person_revision != state.person_revision:
            raise SessionBootstrapError(
                "WakeReceipt belongs to another Person Revision"
            )
        if wake.cognition_during_gap is not False:
            raise SessionBootstrapError(
                "WakeReceipt may not claim cognition during the offline gap"
            )
        wake_reference = _wake_receipt_ref(wake)

    state_reference = self_state_ref(state)
    person_reference = active_person_binding_ref(person)
    personality_snapshot = PersonalitySnapshot(
        person_revision=person.person_revision,
        personality_revision=person.personality_revision,
        personality_state_ref=state.personality_state_ref,
        source_refs=[
            person.registry_source_ref,
            person_reference,
            f"person-revision:{person.person_revision}",
            f"personality-revision:{person.personality_revision}",
            person.body_source_ref,
            person.voice_source_ref,
        ],
    )

    observations = [
        WorldObservation(
            observation_id=_observation_id(
                "runtime-session-bootstrap",
                bootstrap_source_ref,
            ),
            subject_ref=f"self:{state.self_id}",
            proposition=(
                "A new Consciousness Core runtime session was initialized. "
                "The previous transient WorldState and CognitiveWorkspace "
                "objects were not restored from their durable references."
            ),
            confidence=1.0,
            epistemic_status="observed",
            source_refs=[bootstrap_source_ref, state_reference],
        ),
        WorldObservation(
            observation_id=_observation_id(
                "active-person-binding",
                person_reference,
            ),
            subject_ref=f"person:{person.person_id}",
            proposition=(
                f"Active Person Revision {person.person_revision} was verified "
                "against the durable SelfState for this runtime session."
            ),
            confidence=1.0,
            epistemic_status="observed",
            source_refs=[person.registry_source_ref, person_reference],
        ),
    ]
    if wake is not None and wake_reference is not None:
        observations.append(
            WorldObservation(
                observation_id=_observation_id(
                    "wake-continuity",
                    wake_reference,
                ),
                subject_ref=f"self:{state.self_id}",
                proposition=_wake_summary(wake),
                confidence=wake.duration_confidence if wake.duration_known else 1.0,
                epistemic_status="observed",
                source_refs=[wake_reference],
            )
        )

    world = RuntimeWorldState(
        schema="kaliv-consciousness-core/world-state/v1",
        world_id=_fresh_world_id(
            state_reference=state_reference,
            bootstrap_source_ref=bootstrap_source_ref,
            wake_reference=wake_reference,
        ),
        revision=1,
        observations=observations,
        production_activation=False,
    )

    candidates: list[WorkspaceCandidate] = [
        WorkspaceCandidate(
            candidate_id=_candidate_id(
                "runtime-session-bootstrap",
                bootstrap_source_ref,
            ),
            kind="perception",
            salience=1.0,
            summary=(
                "Fresh runtime cognitive context is active; prior transient "
                "world/workspace objects were not restored."
            ),
            source_ref=bootstrap_source_ref,
        )
    ]
    if wake is not None and wake_reference is not None:
        candidates.append(
            WorkspaceCandidate(
                candidate_id=_candidate_id("wake-continuity", wake_reference),
                kind="perception",
                salience=0.96,
                summary=_wake_summary(wake),
                source_ref=wake_reference,
            )
        )

    for goal_ref in list(dict.fromkeys(state.active_goal_refs))[:64]:
        candidates.append(
            WorkspaceCandidate(
                candidate_id=_candidate_id("durable-active-goal", goal_ref),
                kind="goal",
                salience=0.84,
                summary=(
                    "Durable SelfState carries this active goal reference into "
                    "the fresh runtime context; no execution is implied."
                ),
                source_ref=goal_ref,
            )
        )

    for intention_ref in list(dict.fromkeys(state.active_intention_refs))[:64]:
        candidates.append(
            WorkspaceCandidate(
                candidate_id=_candidate_id(
                    "durable-active-intention",
                    intention_ref,
                ),
                kind="memory",
                salience=0.78,
                summary=(
                    "Durable SelfState carries this active intention reference "
                    "as continuity context; it is not automatically dispatched."
                ),
                source_ref=intention_ref,
            )
        )

    if state.last_experience_ref is not None:
        candidates.append(
            WorkspaceCandidate(
                candidate_id=_candidate_id(
                    "last-experience-ref",
                    state.last_experience_ref,
                ),
                kind="memory",
                salience=0.72,
                summary=(
                    "Durable SelfState retains a reference to the last accepted "
                    "experience; C19-A does not materialize or rewrite it."
                ),
                source_ref=state.last_experience_ref,
            )
        )

    workspace = build_workspace(
        cycle_id=_fresh_cycle_id(
            state_reference=state_reference,
            bootstrap_source_ref=bootstrap_source_ref,
            wake_reference=wake_reference,
        ),
        candidates=candidates,
        max_active=max_active,
    )

    next_state = advance_self_state(
        state,
        world_state_ref=world_state_ref(world),
        workspace_ref=workspace_ref(workspace),
    )

    if next_state.self_id != state.self_id:
        raise SessionBootstrapError("runtime bootstrap changed self identity")
    if next_state.person_id != state.person_id:
        raise SessionBootstrapError("runtime bootstrap changed person identity")
    if next_state.person_revision != state.person_revision:
        raise SessionBootstrapError("runtime bootstrap changed Person Revision")
    if next_state.personality_state_ref != state.personality_state_ref:
        raise SessionBootstrapError("runtime bootstrap changed personality binding")
    if next_state.active_goal_refs != state.active_goal_refs:
        raise SessionBootstrapError("runtime bootstrap changed active goals")
    if next_state.active_intention_refs != state.active_intention_refs:
        raise SessionBootstrapError("runtime bootstrap changed active intentions")
    if next_state.affect != state.affect:
        raise SessionBootstrapError("runtime bootstrap changed affect")
    if next_state.known_uncertainties != state.known_uncertainties:
        raise SessionBootstrapError("runtime bootstrap changed durable uncertainties")
    if next_state.last_experience_ref != state.last_experience_ref:
        raise SessionBootstrapError("runtime bootstrap changed experience binding")

    receipt = SessionBootstrapReceipt(
        schema="kaliv-consciousness-core/session-bootstrap-receipt/v1",
        bootstrap_kind=(
            "WAKE_REORIENTATION" if wake is not None else "RUNTIME_START"
        ),
        bootstrap_source_ref=bootstrap_source_ref,
        wake_receipt_ref=wake_reference,
        previous_self_state_ref=state_reference,
        next_self_state_ref=self_state_ref(next_state),
        previous_world_state_ref=state.world_state_ref,
        previous_workspace_ref=state.workspace_ref,
        fresh_world_state_ref=world_state_ref(world),
        fresh_workspace_ref=workspace_ref(workspace),
        personality_snapshot_ref=personality_snapshot_ref(personality_snapshot),
        self_id=state.self_id,
        person_id=state.person_id,
        person_revision=state.person_revision,
        self_revision_before=state.revision,
        self_revision_after=next_state.revision,
        prior_world_restored=False,
        prior_workspace_restored=False,
        identity_unchanged=True,
        active_goal_bindings_unchanged=True,
        active_intention_bindings_unchanged=True,
        affect_unchanged=True,
        durable_uncertainties_unchanged=True,
        last_experience_binding_unchanged=True,
        cognition_during_gap=False if wake is not None else None,
        model_calls=0,
        self_state_store_write_applied=False,
        durable_memory_write_authority=False,
        execution_authority=False,
        scheduling_authority=False,
        production_activation=False,
    )
    return RuntimeSessionContext(
        schema="kaliv-consciousness-core/runtime-session-context/v1",
        state=next_state,
        world=world,
        workspace=workspace,
        personality_snapshot=personality_snapshot,
        receipt=receipt,
        production_activation=False,
    )
