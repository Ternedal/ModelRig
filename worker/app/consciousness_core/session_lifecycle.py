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
from .cycle import CognitiveWorkspace, RuntimeWorldState, workspace_ref, world_state_ref
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


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]


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

    @property
    def live_state(self) -> LiveCognitiveSessionState:
        return self._live

    @property
    def supervisor_state(self):
        return self._bridge.state

    @property
    def closed(self) -> bool:
        return self._closed

    def _require_open(self) -> None:
        if self._closed:
            raise CognitiveSessionLifecycleError("cognitive session is closed")

    def submit(self, event: CognitionEvent) -> None:
        self._require_open()
        self._bridge.submit(event)

    def plan(self) -> tuple[Any, SupervisorPlan]:
        self._require_open()
        return self._bridge.plan()

    async def step(
        self,
        *,
        profile: CognitiveProfile,
        relevant_memory_refs: list[str] | None = None,
        embodiment_state_ref: str | None = None,
    ) -> CognitiveSessionStep:
        """Run at most one explicit supervisor step against owned live context."""
        self._require_open()
        if not isinstance(profile, CognitiveProfile):
            raise TypeError("profile must be CognitiveProfile")

        before = self._live
        bridge_step = await self._bridge.step(
            current_state=before.state,
            current_world=before.world,
            current_workspace=before.workspace,
            personality_snapshot=before.personality_snapshot,
            profile=profile,
            relevant_memory_refs=relevant_memory_refs,
            embodiment_state_ref=embodiment_state_ref,
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

        reduction = bridge_step.cycle_result.reduction
        next_state = reduction.next_self_state
        next_workspace = reduction.next_workspace

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
    return ProductionCognitiveSession(
        supervisor_bridge=bridge,
        bootstrap_context=context,
    )


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
