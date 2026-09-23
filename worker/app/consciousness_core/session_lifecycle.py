"""C19-B production in-memory cognitive session owner.

The session owner sits above C18-B and C19-A. It owns the live transient
Self/World/Workspace/Personality context for one worker process, while the
replaceable CognitiveProfile remains caller-supplied and non-authoritative.

No route, scheduler, thread, timer, durable write, tool execution, or automatic
model call is introduced here.
"""
from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from functools import wraps
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..person_api import registry_path
from ..person_registry import PersonRegistry
from .contracts import CognitiveProfile, PersonalitySnapshot
from .cycle import (
    CognitiveWorkspace,
    RuntimeWorldState,
    self_state_ref,
    workspace_ref,
    world_state_ref,
)
from .metacognition import OutcomeObservation, PredictionRecord
from .embodiment import EmbodimentState, InferredEmbodimentState
from .embodiment_attention import (
    EmbodimentAttentionAdmissionResult,
    plan_embodiment_attention,
)
from .experience import MemoryContextSnapshot
from .memory_recall_attention import (
    MemoryRecallAdmissionResult,
    MemoryRecallPlan,
    memory_context_snapshot_ref,
    memory_recall_snapshot_has_items,
    plan_memory_recall,
)
from .prediction_attention import (
    PredictionOutcomeAdmissionResult,
    plan_prediction_outcome,
)
from .production_lifecycle import TrustedRuntimeClock
from .response_guidance import (
    ResponseGuidanceEnvelope,
    build_response_guidance,
)
from .self_state import PersistentSelfState, SelfStateStore
from .session_bootstrap import (
    RuntimeSessionContext,
    SessionBootstrapReceipt,
    active_person_binding_from_registry,
    bootstrap_runtime_session,
)
from .supervisor import CognitionEvent, SupervisorPlan
from .supervisor_lifecycle import (
    ProductionSupervisorBridge,
    SupervisorBridgeStep,
)
from .wake_followup import build_wake_followup_event
from .world_reducer import (
    WorldEvidenceEvent,
    WorldTransitionReceipt,
    reduce_world_evidence,
    world_evidence_event_ref,
)


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
UnitInterval = Annotated[
    float,
    Field(ge=0.0, le=1.0, strict=True, allow_inf_nan=False),
]


class CognitiveSessionLifecycleError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class LiveCognitiveSessionState(StrictModel):
    schema: Literal["kaliv-consciousness-core/live-session-state/v1"]
    state: PersistentSelfState
    world: RuntimeWorldState
    workspace: CognitiveWorkspace
    personality_snapshot: PersonalitySnapshot
    bootstrap_receipt_ref: NonEmptyRef
    completed_cycles: Annotated[int, Field(ge=0, strict=True)]
    last_transition_receipt_ref: NonEmptyRef | None
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_bindings(self) -> "LiveCognitiveSessionState":
        if self.state.world_state_ref != world_state_ref(self.world):
            raise ValueError("live session SelfState/world binding mismatch")
        if self.state.workspace_ref != workspace_ref(self.workspace):
            raise ValueError("live session SelfState/workspace binding mismatch")
        if self.state.person_revision != self.personality_snapshot.person_revision:
            raise ValueError("live session Person Revision/personality mismatch")
        if (
            self.state.personality_state_ref
            != self.personality_snapshot.personality_state_ref
        ):
            raise ValueError("live session personality-state binding mismatch")
        return self


class WorldEvidenceAdmissionResult(StrictModel):
    schema: Literal["kaliv-consciousness-core/world-evidence-admission/v1"]
    evidence_ref: NonEmptyRef
    world_transition: WorldTransitionReceipt
    cognition_event: CognitionEvent | None
    cognition_event_queued: bool
    observed_sequence: Annotated[int, Field(ge=0, strict=True)]
    live_state: LiveCognitiveSessionState
    model_calls: Literal[0]
    self_state_store_write_applied: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def admission_shape(self) -> "WorldEvidenceAdmissionResult":
        if self.world_transition.idempotent_replay:
            if self.cognition_event is not None or self.cognition_event_queued:
                raise ValueError(
                    "idempotent world replay cannot queue cognition again"
                )
        else:
            if self.cognition_event is None or not self.cognition_event_queued:
                raise ValueError("new world evidence must queue one cognition event")
        return self


class CognitiveSessionStep(StrictModel):
    schema: Literal["kaliv-consciousness-core/session-step/v1"]
    supervisor_step: SupervisorBridgeStep
    live_state: LiveCognitiveSessionState
    context_updated: bool
    self_state_store_write_applied: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
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


def _ref(kind: str, value: Any) -> str:
    return f"{kind}:{hashlib.sha256(_canonical_json(value)).hexdigest()}"


def session_bootstrap_receipt_ref(receipt: SessionBootstrapReceipt) -> str:
    if not isinstance(receipt, SessionBootstrapReceipt):
        raise TypeError("receipt must be SessionBootstrapReceipt")
    return _ref("session-bootstrap-receipt", receipt)


def transition_receipt_ref(receipt: BaseModel) -> str:
    return _ref("cognitive-transition-receipt", receipt)


def _world_attention_event_id(evidence_ref: str, kind: str) -> str:
    return "cevt-" + hashlib.sha256(
        ("world-evidence-attention|" + kind + "|" + evidence_ref).encode("utf-8")
    ).hexdigest()[:32]


def _reported_user_turn_evidence_id(turn_id: str) -> str:
    return "wevt-" + hashlib.sha256(
        ("reported-user-turn|" + turn_id).encode("utf-8")
    ).hexdigest()[:32]


def live_state_from_bootstrap(
    context: RuntimeSessionContext,
) -> LiveCognitiveSessionState:
    if not isinstance(context, RuntimeSessionContext):
        raise TypeError("context must be RuntimeSessionContext")
    return LiveCognitiveSessionState(
        schema="kaliv-consciousness-core/live-session-state/v1",
        state=context.state,
        world=context.world,
        workspace=context.workspace,
        personality_snapshot=context.personality_snapshot,
        bootstrap_receipt_ref=session_bootstrap_receipt_ref(context.receipt),
        completed_cycles=0,
        last_transition_receipt_ref=None,
        production_activation=False,
    )


class ProductionCognitiveSession:
    """Own one live cognitive context for the current worker process."""

    def __init__(
        self,
        *,
        supervisor_bridge: ProductionSupervisorBridge,
        bootstrap_context: RuntimeSessionContext,
    ) -> None:
        if not isinstance(supervisor_bridge, ProductionSupervisorBridge):
            raise TypeError("supervisor_bridge must be ProductionSupervisorBridge")
        if not isinstance(bootstrap_context, RuntimeSessionContext):
            raise TypeError("bootstrap_context must be RuntimeSessionContext")
        self._bridge = supervisor_bridge
        self._live = live_state_from_bootstrap(bootstrap_context)
        self._closed = False
        # Bounded process-local replay ledger. Values are:
        # (observed_sequence, canonical evidence ref, observation id).
        self._user_turn_ledger: dict[str, tuple[int, str, str]] = {}
        self._next_user_turn_sequence = 1
        self._pending_response_guidance: ResponseGuidanceEnvelope | None = None
        # Bounded privacy-safe replay ledger. Plans contain only hashes/counts
        # and event metadata, never recalled memory text or item ids.
        self._memory_recall_ledger: dict[str, MemoryRecallPlan] = {}

    @property
    def live_state(self) -> LiveCognitiveSessionState:
        return self._live

    @property
    def supervisor_state(self):
        return self._bridge.state

    @property
    def trusted_clock(self) -> TrustedRuntimeClock:
        """Borrow C18's trusted runtime clock without creating a second epoch."""
        return self._bridge.trusted_clock

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def pending_response_guidance(self) -> ResponseGuidanceEnvelope | None:
        return self._pending_response_guidance

    def consume_response_guidance(
        self,
        *,
        user_turn_event_id: str,
    ) -> ResponseGuidanceEnvelope | None:
        """Consume one outward guidance envelope bound to one exact user turn."""
        self._require_open()
        if (
            not isinstance(user_turn_event_id, str)
            or not user_turn_event_id.startswith("cevt-")
            or len(user_turn_event_id) != len("cevt-") + 32
        ):
            raise CognitiveSessionLifecycleError(
                "invalid user-turn event id for response guidance"
            )
        guidance = self._pending_response_guidance
        if guidance is None:
            return None
        if guidance.user_turn_event_id != user_turn_event_id:
            raise CognitiveSessionLifecycleError(
                "response guidance belongs to another user turn"
            )
        self._pending_response_guidance = None
        return guidance

    def _require_open(self) -> None:
        if self._closed:
            raise CognitiveSessionLifecycleError("cognitive session is closed")

    def submit(self, event: CognitionEvent) -> None:
        self._require_open()
        self._bridge.submit(event)

    def plan(self) -> tuple[Any, SupervisorPlan]:
        self._require_open()
        return self._bridge.plan()

    def submit_embodiment_inference(
        self,
        *,
        state: EmbodimentState,
        inference: InferredEmbodimentState,
    ) -> EmbodimentAttentionAdmissionResult:
        """Admit one evidence-bound semantic embodiment inference."""
        self._require_open()
        if not isinstance(state, EmbodimentState):
            raise TypeError("state must be EmbodimentState")
        if not isinstance(inference, InferredEmbodimentState):
            raise TypeError("inference must be InferredEmbodimentState")
        if state.person_id != self._live.state.person_id:
            raise CognitiveSessionLifecycleError(
                "EmbodimentState belongs to another person"
            )
        if state.person_revision != self._live.state.person_revision:
            raise CognitiveSessionLifecycleError(
                "EmbodimentState belongs to another Person Revision"
            )

        plan = plan_embodiment_attention(
            state=state,
            inference=inference,
        )
        before_revision = self._bridge.state.revision
        if plan.cognition_event is not None:
            self._bridge.submit(plan.cognition_event)
        after_revision = self._bridge.state.revision

        return EmbodimentAttentionAdmissionResult(
            schema=(
                "kaliv-consciousness-core/"
                "embodiment-attention-admission/v1"
            ),
            plan=plan,
            cognition_event_admitted=plan.cognition_event is not None,
            supervisor_revision_before=before_revision,
            supervisor_revision_after=after_revision,
            model_calls=0,
            self_state_store_write_applied=False,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            body_mutation_authority=False,
            production_activation=False,
        )

    def submit_memory_recall(
        self,
        snapshot: MemoryContextSnapshot,
    ) -> MemoryRecallAdmissionResult:
        """Admit one verified Memory 4 recall as privacy-safe attention."""
        self._require_open()
        if not isinstance(snapshot, MemoryContextSnapshot):
            raise TypeError("snapshot must be MemoryContextSnapshot")

        snapshot_ref = memory_context_snapshot_ref(snapshot)
        before_revision = self._bridge.state.revision
        plan = self._memory_recall_ledger.get(snapshot_ref)

        if plan is None:
            if memory_recall_snapshot_has_items(snapshot):
                plan = plan_memory_recall(
                    snapshot=snapshot,
                    clock=self.trusted_clock.sample(),
                )
            else:
                plan = plan_memory_recall(snapshot=snapshot)

            if plan.cognition_event is not None:
                self._bridge.submit(plan.cognition_event)
                self._memory_recall_ledger[snapshot_ref] = plan
                if len(self._memory_recall_ledger) > 256:
                    oldest = next(iter(self._memory_recall_ledger))
                    del self._memory_recall_ledger[oldest]
        elif plan.cognition_event is not None:
            # Exact replay reuses the original event/clock binding. C18 exact
            # event admission is idempotent and will not advance revision.
            self._bridge.submit(plan.cognition_event)

        after_revision = self._bridge.state.revision
        return MemoryRecallAdmissionResult(
            schema="kaliv-consciousness-core/memory-recall-admission/v1",
            plan=plan,
            cognition_event_admitted=plan.cognition_event is not None,
            supervisor_revision_before=before_revision,
            supervisor_revision_after=after_revision,
            model_calls=0,
            self_state_store_write_applied=False,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            production_activation=False,
        )

    def submit_prediction_outcome(
        self,
        *,
        prediction: PredictionRecord,
        outcome: OutcomeObservation,
    ) -> PredictionOutcomeAdmissionResult:
        """Resolve one structured prediction outcome and admit mismatch attention."""
        self._require_open()
        if not isinstance(prediction, PredictionRecord):
            raise TypeError("prediction must be PredictionRecord")
        if not isinstance(outcome, OutcomeObservation):
            raise TypeError("outcome must be OutcomeObservation")

        plan = plan_prediction_outcome(
            prediction=prediction,
            outcome=outcome,
        )
        before_revision = self._bridge.state.revision
        if plan.cognition_event is not None:
            self._bridge.submit(plan.cognition_event)
        after_revision = self._bridge.state.revision

        return PredictionOutcomeAdmissionResult(
            schema=(
                "kaliv-consciousness-core/"
                "prediction-outcome-admission/v1"
            ),
            plan=plan,
            cognition_event_admitted=plan.cognition_event is not None,
            supervisor_revision_before=before_revision,
            supervisor_revision_after=after_revision,
            model_calls=0,
            self_state_store_write_applied=False,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            production_activation=False,
        )

    def _submit_world_evidence_with_kind(
        self,
        evidence: WorldEvidenceEvent,
        *,
        attention_salience: UnitInterval,
        cognition_kind: Literal["world_change", "user_turn"],
    ) -> WorldEvidenceAdmissionResult:
        """Atomically reduce evidence and queue exactly one typed attention event."""
        self._require_open()
        if not isinstance(evidence, WorldEvidenceEvent):
            raise TypeError("evidence must be WorldEvidenceEvent")

        before = self._live
        reduction = reduce_world_evidence(
            state=before.state,
            world=before.world,
            evidence=evidence,
        )
        evidence_ref = world_evidence_event_ref(evidence)

        if reduction.receipt.idempotent_replay:
            return WorldEvidenceAdmissionResult(
                schema="kaliv-consciousness-core/world-evidence-admission/v1",
                evidence_ref=evidence_ref,
                world_transition=reduction.receipt,
                cognition_event=None,
                cognition_event_queued=False,
                observed_sequence=evidence.observed_sequence,
                live_state=before,
                model_calls=0,
                self_state_store_write_applied=False,
                durable_memory_write_authority=False,
                execution_authority=False,
                scheduling_authority=False,
                production_activation=False,
            )

        event = CognitionEvent(
            schema="kaliv-consciousness-core/cognition-event/v1",
            event_id=_world_attention_event_id(evidence_ref, cognition_kind),
            kind=cognition_kind,
            source_ref=evidence_ref,
            summary=evidence.proposition,
            salience=attention_salience,
            observed_sequence=evidence.observed_sequence,
            production_activation=False,
        )
        prospective = LiveCognitiveSessionState(
            schema="kaliv-consciousness-core/live-session-state/v1",
            state=reduction.state,
            world=reduction.world,
            workspace=before.workspace,
            personality_snapshot=before.personality_snapshot,
            bootstrap_receipt_ref=before.bootstrap_receipt_ref,
            completed_cycles=before.completed_cycles,
            last_transition_receipt_ref=before.last_transition_receipt_ref,
            production_activation=False,
        )

        # Bridge admission is the only side effect. If it rejects (for example
        # because cognition is in flight), the live world is not adopted.
        self._bridge.submit(event)
        self._live = prospective
        return WorldEvidenceAdmissionResult(
            schema="kaliv-consciousness-core/world-evidence-admission/v1",
            evidence_ref=evidence_ref,
            world_transition=reduction.receipt,
            cognition_event=event,
            cognition_event_queued=True,
            observed_sequence=evidence.observed_sequence,
            live_state=self._live,
            model_calls=0,
            self_state_store_write_applied=False,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            production_activation=False,
        )

    def submit_world_evidence(
        self,
        evidence: WorldEvidenceEvent,
        *,
        attention_salience: UnitInterval,
    ) -> WorldEvidenceAdmissionResult:
        """Admit a generic world change as bounded epistemic attention."""
        return self._submit_world_evidence_with_kind(
            evidence,
            attention_salience=attention_salience,
            cognition_kind="world_change",
        )

    def submit_reported_user_turn(
        self,
        *,
        turn_id: str,
        user_text: str,
        source_ref: str,
    ) -> WorldEvidenceAdmissionResult:
        """Admit one canonical authenticated user turn as reported evidence.

        A stable process-local sequence is allocated only after successful
        admission. Replays of the same turn id reuse the original sequence.
        """
        self._require_open()
        if (
            not isinstance(turn_id, str)
            or not turn_id.strip()
            or len(turn_id) > 128
        ):
            raise CognitiveSessionLifecycleError("invalid user turn id")
        if (
            not isinstance(user_text, str)
            or not user_text.strip()
            or len(user_text) > 2048
        ):
            raise CognitiveSessionLifecycleError("invalid user turn text")
        if (
            not isinstance(source_ref, str)
            or not source_ref.strip()
            or len(source_ref) > 256
        ):
            raise CognitiveSessionLifecycleError("invalid user turn source ref")

        existing = self._user_turn_ledger.get(turn_id)
        observed_sequence = (
            existing[0]
            if existing is not None
            else self._next_user_turn_sequence
        )
        evidence = WorldEvidenceEvent(
            schema="kaliv-consciousness-core/world-evidence-event/v1",
            event_id=_reported_user_turn_evidence_id(turn_id),
            subject_ref="actor:user",
            proposition=user_text,
            confidence=1.0,
            epistemic_status="reported",
            source_refs=[source_ref],
            observed_sequence=observed_sequence,
            production_activation=False,
        )
        evidence_ref = world_evidence_event_ref(evidence)

        if existing is not None:
            existing_sequence, existing_ref, observation_id = existing
            if existing_ref != evidence_ref:
                raise CognitiveSessionLifecycleError(
                    "user turn id reused with conflicting payload"
                )
            current_world_ref = world_state_ref(self._live.world)
            current_self_ref = self_state_ref(self._live.state)
            replay_receipt = WorldTransitionReceipt(
                schema="kaliv-consciousness-core/world-transition-receipt/v1",
                event_id=evidence.event_id,
                observation_id=observation_id,
                previous_world_state_ref=current_world_ref,
                next_world_state_ref=current_world_ref,
                previous_self_state_ref=current_self_ref,
                next_self_state_ref=current_self_ref,
                world_revision_before=self._live.world.revision,
                world_revision_after=self._live.world.revision,
                self_revision_before=self._live.state.revision,
                self_revision_after=self._live.state.revision,
                world_changed=False,
                idempotent_replay=True,
                evicted_observation_ids=[],
                identity_unchanged=True,
                workspace_binding_unchanged=True,
                personality_binding_unchanged=True,
                goal_bindings_unchanged=True,
                intention_bindings_unchanged=True,
                affect_unchanged=True,
                durable_memory_binding_unchanged=True,
                model_calls=0,
                self_state_store_write_applied=False,
                durable_memory_write_authority=False,
                execution_authority=False,
                scheduling_authority=False,
                production_activation=False,
            )
            return WorldEvidenceAdmissionResult(
                schema="kaliv-consciousness-core/world-evidence-admission/v1",
                evidence_ref=existing_ref,
                world_transition=replay_receipt,
                cognition_event=None,
                cognition_event_queued=False,
                observed_sequence=existing_sequence,
                live_state=self._live,
                model_calls=0,
                self_state_store_write_applied=False,
                durable_memory_write_authority=False,
                execution_authority=False,
                scheduling_authority=False,
                production_activation=False,
            )

        result = self._submit_world_evidence_with_kind(
            evidence,
            attention_salience=1.0,
            cognition_kind="user_turn",
        )
        self._user_turn_ledger[turn_id] = (
            observed_sequence,
            evidence_ref,
            result.world_transition.observation_id,
        )
        self._next_user_turn_sequence = observed_sequence + 1
        if len(self._user_turn_ledger) > 1024:
            oldest = next(iter(self._user_turn_ledger))
            del self._user_turn_ledger[oldest]
        return result

    async def step(
        self,
        *,
        profile: CognitiveProfile,
        relevant_memory_refs: list[str] | None = None,
        embodiment_state_ref: str | None = None,
        required_event_id: str | None = None,
        allowed_event_ids: list[str] | None = None,
    ) -> CognitiveSessionStep:
        """Run at most one explicit supervisor step against owned live context."""
        self._require_open()
        if not isinstance(profile, CognitiveProfile):
            raise TypeError("profile must be CognitiveProfile")

        before = self._live
        pending_events_before = {
            event.event_id: event
            for event in self._bridge.state.pending_events
        }
        bridge_step = await self._bridge.step(
            current_state=before.state,
            current_world=before.world,
            current_workspace=before.workspace,
            personality_snapshot=before.personality_snapshot,
            profile=profile,
            relevant_memory_refs=relevant_memory_refs,
            embodiment_state_ref=embodiment_state_ref,
            required_event_id=required_event_id,
            allowed_event_ids=allowed_event_ids,
        )

        if bridge_step.cycle_result is None:
            return CognitiveSessionStep(
                schema="kaliv-consciousness-core/session-step/v1",
                supervisor_step=bridge_step,
                live_state=before,
                context_updated=False,
                self_state_store_write_applied=False,
                durable_memory_write_authority=False,
                execution_authority=False,
                scheduling_authority=False,
                production_activation=False,
            )

        cycle_result = bridge_step.cycle_result
        reduction = cycle_result.reduction
        next_state = reduction.next_self_state
        next_workspace = reduction.next_workspace

        selected_events: list[CognitionEvent] = []
        for event_id in cycle_result.receipt.selected_event_ids:
            event = pending_events_before.get(event_id)
            if event is None:
                raise CognitiveSessionLifecycleError(
                    "selected cognition event missing from pre-step state"
                )
            selected_events.append(event)

        next_guidance = build_response_guidance(
            proposal=cycle_result.cognitive_cycle.proposal,
            selected_events=selected_events,
            cycle_id=cycle_result.cognitive_cycle.request.cycle_id,
            cognitive_profile_ref=(
                cycle_result.cognitive_cycle.request.cognitive_profile_ref
            ),
            person_revision=next_state.person_revision,
            self_revision=next_state.revision,
        )

        # C18-A/C16 must preserve world/personality authority. C19-B refuses to
        # adopt a transition that claims otherwise.
        if next_state.world_state_ref != before.state.world_state_ref:
            raise CognitiveSessionLifecycleError(
                "supervisor transition changed live world binding"
            )
        if next_state.person_revision != before.state.person_revision:
            raise CognitiveSessionLifecycleError(
                "supervisor transition changed Person Revision"
            )
        if next_state.personality_state_ref != before.state.personality_state_ref:
            raise CognitiveSessionLifecycleError(
                "supervisor transition changed personality binding"
            )

        self._live = LiveCognitiveSessionState(
            schema="kaliv-consciousness-core/live-session-state/v1",
            state=next_state,
            world=before.world,
            workspace=next_workspace,
            personality_snapshot=before.personality_snapshot,
            bootstrap_receipt_ref=before.bootstrap_receipt_ref,
            completed_cycles=before.completed_cycles + 1,
            last_transition_receipt_ref=transition_receipt_ref(
                reduction.receipt
            ),
            production_activation=False,
        )
        # A successful RUN advances the cognitive moment. Any older
        # unconsumed guidance is replaced, including by None when this cycle has
        # no unambiguous outward response intent. WAIT/IDLE returned above and
        # therefore preserve the current mailbox.
        self._pending_response_guidance = next_guidance
        return CognitiveSessionStep(
            schema="kaliv-consciousness-core/session-step/v1",
            supervisor_step=bridge_step,
            live_state=self._live,
            context_updated=True,
            self_state_store_write_applied=False,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            production_activation=False,
        )

    def close(self) -> None:
        # Response guidance and privacy-safe recall replay bindings are transient
        # and cannot cross the process/session lifecycle boundary.
        self._pending_response_guidance = None
        self._memory_recall_ledger.clear()
        # C18-B owns and closes the underlying bridge. C19-B only prevents
        # further use of this higher-level session view.
        self._closed = True


def production_cognitive_session_factory(
    app,
    *,
    self_store_factory=SelfStateStore,
    registry_path_fn=registry_path,
    registry_factory=PersonRegistry,
) -> ProductionCognitiveSession | None:
    """Build a live session only from already-authorized production sources."""
    bridge = getattr(app.state, "consciousness_supervisor", None)
    if bridge is None:
        # C18-B double opt-in was not satisfied. Do not touch persistence.
        return None
    if not isinstance(bridge, ProductionSupervisorBridge):
        raise CognitiveSessionLifecycleError(
            "production supervisor app state has unexpected type"
        )

    durable = self_store_factory().read()
    if durable is None:
        return None

    person_path = Path(registry_path_fn())
    if not person_path.exists():
        return None
    active = registry_factory(person_path).active_bindings()
    if active is None:
        return None

    binding = active_person_binding_from_registry(
        active,
        registry_source_ref="person-registry:active",
    )
    wake_receipt = getattr(
        app.state,
        "consciousness_sleep_wake_receipt",
        None,
    )
    context = bootstrap_runtime_session(
        persistent_state=durable,
        active_person=binding,
        bootstrap_source_ref=(
            "runtime-epoch:" + bridge.state.runtime_epoch_id
        ),
        wake_receipt=wake_receipt,
    )
    session = ProductionCognitiveSession(
        supervisor_bridge=bridge,
        bootstrap_context=context,
    )
    if wake_receipt is not None:
        session.submit(
            build_wake_followup_event(
                wake_receipt,
                expected_self_id=session.live_state.state.self_id,
                expected_person_revision=(
                    session.live_state.state.person_revision
                ),
            )
        )
    return session


def compose_cognitive_session_lifespan(
    inner_lifespan,
    session_factory=production_cognitive_session_factory,
):
    """Compose C19-B around C18-B without taking scheduler lifecycle ownership."""
    if not callable(inner_lifespan):
        raise TypeError("inner lifespan must be callable")
    if not callable(session_factory):
        raise TypeError("session_factory must be callable")

    authority_owner = getattr(inner_lifespan, "__wrapped__", inner_lifespan)

    @wraps(inner_lifespan)
    @asynccontextmanager
    async def composed(app):
        async with inner_lifespan(app):
            session = session_factory(app)
            if session is not None and not isinstance(
                session,
                ProductionCognitiveSession,
            ):
                raise TypeError(
                    "session_factory must return ProductionCognitiveSession or None"
                )
            if session is not None:
                app.state.consciousness_session = session
            try:
                yield
            finally:
                if session is not None:
                    session.close()
                    try:
                        delattr(app.state, "consciousness_session")
                    except AttributeError:
                        pass

    composed.__wrapped__ = authority_owner
    return composed
