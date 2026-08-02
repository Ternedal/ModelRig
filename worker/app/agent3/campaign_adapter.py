"""Real, dormant Agent 3 adapter for ADR-A4-008 campaign handoffs.

The adapter uses the existing AgentRunStore SQLite connection and lock as its
only persistence boundary.  Importing this module does nothing; constructing an
adapter creates only the effect registry in the already-selected Agent 3 DB.
There is no HTTP client, provider SDK, retry loop, background worker, route
registration, Agent 4 activation, or fallback executor.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import sqlite3
import time
from typing import Callable, Iterator

from .core import (
    Agent3Orchestrator,
    AgentRun,
    AgentRunStore,
    AgentStep,
    CapabilitySnapshot,
    RouteKind,
    RunState,
    StepState,
    TurnRequest,
)
from ..agent4.handoff import (
    CampaignDispatchAcknowledgement,
    CampaignDispatchOutcome,
    CampaignDispatchRequest,
    CampaignSignalAcknowledgement,
    CampaignSignalRequest,
    CampaignSignalType,
    DispatchOutcomeKind,
    campaign_dispatch_id,
)


_EFFECT_COLUMNS = (
    "effect_id,effect_kind,request_hash,request_payload,disposition,"
    "campaign_id,attempt,run_id,runtime_reference,outcome,evidence_pointer,"
    "error,resources_released,created_at,updated_at"
)


class Agent3CampaignAdapterError(RuntimeError):
    """Base class for fail-closed adapter errors."""


class Agent3CampaignDispatchConflictError(Agent3CampaignAdapterError):
    """The same deterministic identity was presented with different facts."""


class Agent3CampaignDispatchTombstonedError(Agent3CampaignAdapterError):
    """The dispatch identity was permanently tombstoned before acceptance."""


class Agent3CampaignSignalUncertainError(Agent3CampaignAdapterError):
    """A signal was durably requested but cannot safely be delivered again."""


class Agent3CampaignSignalUnsupportedError(Agent3CampaignAdapterError):
    """Agent 3 has no safe implementation for the requested signal."""


@dataclass(frozen=True, slots=True)
class Agent3CampaignLaunch:
    """One server-authored Agent 3 run definition for a campaign workflow."""

    request: TurnRequest
    capabilities: CapabilitySnapshot
    steps: tuple[AgentStep, ...]
    proactive: bool = False
    allow_private_cloud: bool = False


CampaignLaunchResolver = Callable[[CampaignDispatchRequest], Agent3CampaignLaunch]


@dataclass(frozen=True, slots=True)
class _Effect:
    effect_id: str
    effect_kind: str
    request_hash: str | None
    request_payload: str | None
    disposition: str
    campaign_id: str | None
    attempt: int | None
    run_id: str | None
    runtime_reference: str | None
    outcome: str | None
    evidence_pointer: str | None
    error: str | None
    resources_released: int | None
    created_at: float
    updated_at: float

    @classmethod
    def from_row(cls, row: tuple[object, ...]) -> "_Effect":
        return cls(*row)  # type: ignore[arg-type]


class Agent3CampaignHandoffAdapter:
    """CampaignHandoffExecutor backed by the real Agent 3 run/store boundary.

    A dispatch identity is either atomically bound to exactly one AgentRun or
    permanently tombstoned.  The registry row, run row, and run_created event
    share one BEGIN IMMEDIATE transaction on AgentRunStore's connection.

    Signal rows use requested-before-call and acknowledged-after-call.  An
    unresolved requested signal is never replayed automatically because the
    current ADR has no signal-outcome lookup.
    """

    def __init__(
        self,
        orchestrator: Agent3Orchestrator,
        resolve_launch: CampaignLaunchResolver,
    ) -> None:
        if not isinstance(orchestrator.store, AgentRunStore):
            raise TypeError("Agent 3 campaign adapter requires AgentRunStore")
        if not callable(resolve_launch):
            raise TypeError("resolve_launch must be callable")
        self._orchestrator = orchestrator
        self._store = orchestrator.store
        self._resolve_launch = resolve_launch
        self._ensure_schema()

    def dispatch(
        self,
        request: CampaignDispatchRequest,
    ) -> CampaignDispatchAcknowledgement:
        if not isinstance(request, CampaignDispatchRequest):
            raise TypeError("request must be CampaignDispatchRequest")
        existing = self._existing_dispatch_acknowledgement(request)
        if existing is not None:
            return existing
        launch = self._resolve_launch(request)
        if not isinstance(launch, Agent3CampaignLaunch):
            raise TypeError("campaign launch resolver returned an invalid value")
        run = self._prepare_run(launch)
        acknowledgement, created = self._bind_dispatch(request, run)
        if created:
            # External execution is deliberately outside the registry
            # transaction.  A crash here leaves a durable accepted run that is
            # resolved through query_outcome; a duplicate dispatch never calls
            # advance again.
            self._advance_preserving_late_cancel(run.id)
        return acknowledgement

    def signal(
        self,
        request: CampaignSignalRequest,
    ) -> CampaignSignalAcknowledgement:
        if not isinstance(request, CampaignSignalRequest):
            raise TypeError("request must be CampaignSignalRequest")
        if request.signal_type is CampaignSignalType.PAUSE:
            # Agent 3 has no general pause primitive that can stop or preserve
            # an in-flight synchronous side effect.  A false acknowledgement
            # would be worse than an explicit fail-closed limitation.
            raise Agent3CampaignSignalUnsupportedError(
                "Agent 3 does not support a safe generic pause signal"
            )

        request_payload = self._canonical(request.to_dict())
        request_hash = hashlib.sha256(request_payload.encode("utf-8")).hexdigest()
        dispatch_id = campaign_dispatch_id(request.campaign_id, request.attempt)

        with self._transaction() as connection:
            dispatch_effect = self._select_effect(connection, dispatch_id)
            if (
                dispatch_effect is None
                or dispatch_effect.effect_kind != "dispatch"
                or dispatch_effect.disposition == "tombstoned"
                or not dispatch_effect.run_id
                or not dispatch_effect.runtime_reference
            ):
                raise Agent3CampaignAdapterError(
                    "signal has no accepted Agent 3 dispatch to target"
                )

            existing = self._select_effect(connection, request.signal_id)
            if existing is not None:
                self._require_same_request(existing, "signal", request_hash)
                if existing.disposition == "signal_acknowledged":
                    return CampaignSignalAcknowledgement(
                        signal_id=request.signal_id,
                        evidence_pointer=existing.evidence_pointer,
                    )
                raise Agent3CampaignSignalUncertainError(
                    "signal outcome is unresolved and will not be replayed"
                )

            now = time.time()
            connection.execute(
                "INSERT INTO agent_campaign_effects("
                + _EFFECT_COLUMNS
                + ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    request.signal_id,
                    "signal",
                    request_hash,
                    request_payload,
                    "signal_requested",
                    request.campaign_id,
                    request.attempt,
                    dispatch_effect.run_id,
                    dispatch_effect.runtime_reference,
                    None,
                    None,
                    None,
                    None,
                    now,
                    now,
                ),
            )
            run_id = dispatch_effect.run_id

        # Requested is durable before the operation.  Any exception leaves the
        # row unresolved; a retry sees signal_requested and refuses redelivery.
        if request.signal_type is CampaignSignalType.RESUME:
            self._advance_preserving_late_cancel(run_id)
        elif request.signal_type is CampaignSignalType.CANCEL:
            self._orchestrator.cancel(run_id)
        else:  # defensive against a future enum value
            raise Agent3CampaignSignalUnsupportedError(
                f"unsupported Agent 3 signal {request.signal_type.value!r}"
            )

        evidence_pointer = f"agent3-signal:{request.signal_id}"
        with self._transaction() as connection:
            changed = connection.execute(
                "UPDATE agent_campaign_effects SET disposition=?,"
                "evidence_pointer=?,updated_at=? "
                "WHERE effect_id=? AND disposition=?",
                (
                    "signal_acknowledged",
                    evidence_pointer,
                    time.time(),
                    request.signal_id,
                    "signal_requested",
                ),
            ).rowcount
            if changed != 1:
                raise Agent3CampaignSignalUncertainError(
                    "signal acknowledgement could not be committed"
                )
        return CampaignSignalAcknowledgement(
            signal_id=request.signal_id,
            evidence_pointer=evidence_pointer,
        )

    def _advance_preserving_late_cancel(self, run_id: str) -> AgentRun:
        run = self._orchestrator.advance(run_id)
        if (
            run.state is not RunState.CANCELLED
            and any(
                step.state is StepState.COMPLETED_AFTER_CANCEL
                for step in run.steps
            )
        ):
            # Agent3Orchestrator._execute persists the correct late-cancel
            # marker, but its outer advance loop can continue and finalize the
            # stale in-memory run as COMPLETED.  This adapter is a real caller
            # of that full path, so it must preserve the existing Agent 3
            # invariant rather than expose a resurrected cancellation.
            run.state = RunState.CANCELLED
            run.error = run.error or "Cancelled by user"
            self._store.save_with_event(
                run,
                "campaign_late_cancel_reconciled",
                {"run_id": run.id},
            )
        return run

    def query_outcome(self, dispatch_id: str) -> CampaignDispatchOutcome:
        dispatch_id = self._require_identity(dispatch_id, "dispatch_id")
        with self._transaction() as connection:
            effect = self._select_effect(connection, dispatch_id)
            if effect is None:
                return self._tombstone(connection, dispatch_id)
            if effect.effect_kind != "dispatch":
                return CampaignDispatchOutcome(
                    dispatch_id=dispatch_id,
                    kind=DispatchOutcomeKind.UNKNOWN,
                    evidence_pointer=f"agent3-effect:{dispatch_id}:kind-conflict",
                )
            if effect.disposition == "tombstoned":
                return CampaignDispatchOutcome(
                    dispatch_id=dispatch_id,
                    kind=DispatchOutcomeKind.NOT_DISPATCHED,
                    evidence_pointer=effect.evidence_pointer,
                    resources_released=True,
                )

            committed = self._committed_terminal(effect)
            if committed is not None:
                return committed

            if not effect.run_id or not effect.runtime_reference:
                return self._persist_unknown(
                    connection,
                    effect,
                    "accepted effect has no bound Agent 3 run",
                )
            row = connection.execute(
                "SELECT payload FROM agent_runs WHERE id=?",
                (effect.run_id,),
            ).fetchone()
            if row is None:
                return self._persist_unknown(
                    connection,
                    effect,
                    "bound Agent 3 run is missing",
                )
            try:
                run = AgentRun.from_json(row[0])
            except Exception:
                return self._persist_unknown(
                    connection,
                    effect,
                    "bound Agent 3 run cannot be decoded",
                )

            outcome = self._map_run(effect, run)
            disposition = (
                "terminal"
                if outcome.kind in {
                    DispatchOutcomeKind.COMPLETED,
                    DispatchOutcomeKind.FAILED,
                }
                else "accepted"
            )
            connection.execute(
                "UPDATE agent_campaign_effects SET disposition=?,outcome=?,"
                "evidence_pointer=?,error=?,resources_released=?,updated_at=? "
                "WHERE effect_id=?",
                (
                    disposition,
                    outcome.kind.value,
                    outcome.evidence_pointer,
                    outcome.error,
                    (
                        None
                        if outcome.resources_released is None
                        else int(outcome.resources_released)
                    ),
                    time.time(),
                    dispatch_id,
                ),
            )
            return outcome

    def _existing_dispatch_acknowledgement(
        self,
        request: CampaignDispatchRequest,
    ) -> CampaignDispatchAcknowledgement | None:
        payload = self._canonical(request.to_dict())
        request_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        with self._transaction() as connection:
            existing = self._select_effect(connection, request.dispatch_id)
            if existing is None:
                return None
            if existing.disposition == "tombstoned":
                raise Agent3CampaignDispatchTombstonedError(
                    "dispatch identity is permanently tombstoned"
                )
            self._require_same_request(existing, "dispatch", request_hash)
            if not existing.run_id or not existing.runtime_reference:
                raise Agent3CampaignAdapterError(
                    "dispatch identity is accepted without a bound run"
                )
            return CampaignDispatchAcknowledgement(
                dispatch_id=request.dispatch_id,
                runtime_reference=existing.runtime_reference,
                evidence_pointer=existing.evidence_pointer,
            )

    def _prepare_run(self, launch: Agent3CampaignLaunch) -> AgentRun:
        if not isinstance(launch.request, TurnRequest):
            raise TypeError("launch.request must be TurnRequest")
        if not isinstance(launch.capabilities, CapabilitySnapshot):
            raise TypeError("launch.capabilities must be CapabilitySnapshot")
        if not all(isinstance(step, AgentStep) for step in launch.steps):
            raise TypeError("launch.steps must contain AgentStep values")
        steps = [step.cloned_for_retry() for step in launch.steps]
        if len(steps) > self._orchestrator.max_steps:
            raise Agent3CampaignAdapterError(
                f"campaign plan exceeds max_steps ({self._orchestrator.max_steps})"
            )
        route = self._orchestrator.router.route(
            launch.request,
            launch.capabilities,
        )
        if route.kind in {RouteKind.UNAVAILABLE, RouteKind.ASK_BEFORE_DOWNGRADE}:
            raise Agent3CampaignAdapterError(
                f"campaign launch is not runnable: {route.reason}"
            )
        return AgentRun(
            request=launch.request,
            route=route,
            steps=steps,
            proactive=launch.proactive,
            allow_private_cloud=launch.allow_private_cloud,
        )

    def _bind_dispatch(
        self,
        request: CampaignDispatchRequest,
        run: AgentRun,
    ) -> tuple[CampaignDispatchAcknowledgement, bool]:
        payload = self._canonical(request.to_dict())
        request_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        runtime_reference = f"agent3-run:{run.id}"
        evidence_pointer = f"agent3-effect:{request.dispatch_id}:accepted"

        with self._transaction() as connection:
            existing = self._select_effect(connection, request.dispatch_id)
            if existing is not None:
                if existing.disposition == "tombstoned":
                    raise Agent3CampaignDispatchTombstonedError(
                        "dispatch identity is permanently tombstoned"
                    )
                self._require_same_request(existing, "dispatch", request_hash)
                if not existing.run_id or not existing.runtime_reference:
                    raise Agent3CampaignAdapterError(
                        "dispatch identity is accepted without a bound run"
                    )
                return (
                    CampaignDispatchAcknowledgement(
                        dispatch_id=request.dispatch_id,
                        runtime_reference=existing.runtime_reference,
                        evidence_pointer=existing.evidence_pointer,
                    ),
                    False,
                )

            now = time.time()
            run.updated_at = now
            connection.execute(
                "INSERT INTO agent_runs VALUES (?,?,?,?)",
                (run.id, run.state.value, run.to_json(), run.updated_at),
            )
            connection.execute(
                "INSERT INTO agent_events(run_id,ts,kind,payload) VALUES(?,?,?,?)",
                (
                    run.id,
                    now,
                    "run_created",
                    self._canonical(
                        {
                            "route": run.route.kind.value,
                            "steps": len(run.steps),
                            "campaign_id": request.campaign_id,
                            "dispatch_id": request.dispatch_id,
                        }
                    )[:8000],
                ),
            )
            connection.execute(
                "INSERT INTO agent_campaign_effects("
                + _EFFECT_COLUMNS
                + ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    request.dispatch_id,
                    "dispatch",
                    request_hash,
                    payload,
                    "accepted",
                    request.campaign_id,
                    request.attempt,
                    run.id,
                    runtime_reference,
                    DispatchOutcomeKind.ACCEPTED.value,
                    evidence_pointer,
                    None,
                    None,
                    now,
                    now,
                ),
            )
        return (
            CampaignDispatchAcknowledgement(
                dispatch_id=request.dispatch_id,
                runtime_reference=runtime_reference,
                evidence_pointer=evidence_pointer,
            ),
            True,
        )

    def _map_run(
        self,
        effect: _Effect,
        run: AgentRun,
    ) -> CampaignDispatchOutcome:
        assert effect.runtime_reference is not None
        evidence_pointer = f"agent3-run:{run.id}"
        executing = any(step.state is StepState.EXECUTING for step in run.steps)

        if run.state is RunState.COMPLETED and not executing:
            return CampaignDispatchOutcome(
                dispatch_id=effect.effect_id,
                kind=DispatchOutcomeKind.COMPLETED,
                runtime_reference=effect.runtime_reference,
                evidence_pointer=evidence_pointer,
                resources_released=True,
            )
        if run.state is RunState.FAILED and not executing:
            return CampaignDispatchOutcome(
                dispatch_id=effect.effect_id,
                kind=DispatchOutcomeKind.FAILED,
                runtime_reference=effect.runtime_reference,
                evidence_pointer=evidence_pointer,
                error=run.error or "Agent 3 run failed",
                resources_released=True,
            )
        if run.state is RunState.CANCELLED:
            if executing:
                return CampaignDispatchOutcome(
                    dispatch_id=effect.effect_id,
                    kind=DispatchOutcomeKind.UNKNOWN,
                    evidence_pointer=evidence_pointer,
                )
            return CampaignDispatchOutcome(
                dispatch_id=effect.effect_id,
                kind=DispatchOutcomeKind.FAILED,
                runtime_reference=effect.runtime_reference,
                evidence_pointer=evidence_pointer,
                error=run.error or "Agent 3 run cancelled",
                resources_released=True,
            )
        if executing:
            return CampaignDispatchOutcome(
                dispatch_id=effect.effect_id,
                kind=DispatchOutcomeKind.RUNNING,
                runtime_reference=effect.runtime_reference,
                evidence_pointer=evidence_pointer,
            )
        if run.state in {
            RunState.RUNNING,
            RunState.WAITING_CONFIRMATION,
            RunState.BLOCKED,
        }:
            return CampaignDispatchOutcome(
                dispatch_id=effect.effect_id,
                kind=DispatchOutcomeKind.ACCEPTED,
                runtime_reference=effect.runtime_reference,
                evidence_pointer=evidence_pointer,
            )
        return CampaignDispatchOutcome(
            dispatch_id=effect.effect_id,
            kind=DispatchOutcomeKind.UNKNOWN,
            evidence_pointer=evidence_pointer,
        )

    def _committed_terminal(
        self,
        effect: _Effect,
    ) -> CampaignDispatchOutcome | None:
        if effect.disposition != "terminal" or effect.outcome not in {
            DispatchOutcomeKind.COMPLETED.value,
            DispatchOutcomeKind.FAILED.value,
        }:
            return None
        if not effect.runtime_reference or effect.resources_released != 1:
            return None
        kind = DispatchOutcomeKind(effect.outcome)
        if kind is DispatchOutcomeKind.FAILED and not effect.error:
            return None
        return CampaignDispatchOutcome(
            dispatch_id=effect.effect_id,
            kind=kind,
            runtime_reference=effect.runtime_reference,
            evidence_pointer=effect.evidence_pointer,
            error=effect.error,
            resources_released=True,
        )

    def _persist_unknown(
        self,
        connection: sqlite3.Connection,
        effect: _Effect,
        reason: str,
    ) -> CampaignDispatchOutcome:
        evidence_pointer = f"agent3-effect:{effect.effect_id}:unknown"
        connection.execute(
            "UPDATE agent_campaign_effects SET outcome=?,evidence_pointer=?,"
            "error=?,resources_released=NULL,updated_at=? WHERE effect_id=?",
            (
                DispatchOutcomeKind.UNKNOWN.value,
                evidence_pointer,
                reason,
                time.time(),
                effect.effect_id,
            ),
        )
        return CampaignDispatchOutcome(
            dispatch_id=effect.effect_id,
            kind=DispatchOutcomeKind.UNKNOWN,
            evidence_pointer=evidence_pointer,
            error=reason,
        )

    def _tombstone(
        self,
        connection: sqlite3.Connection,
        dispatch_id: str,
    ) -> CampaignDispatchOutcome:
        now = time.time()
        evidence_pointer = f"agent3-effect:{dispatch_id}:tombstone"
        connection.execute(
            "INSERT INTO agent_campaign_effects("
            + _EFFECT_COLUMNS
            + ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                dispatch_id,
                "dispatch",
                None,
                None,
                "tombstoned",
                None,
                None,
                None,
                None,
                DispatchOutcomeKind.NOT_DISPATCHED.value,
                evidence_pointer,
                None,
                1,
                now,
                now,
            ),
        )
        return CampaignDispatchOutcome(
            dispatch_id=dispatch_id,
            kind=DispatchOutcomeKind.NOT_DISPATCHED,
            evidence_pointer=evidence_pointer,
            resources_released=True,
        )

    def _ensure_schema(self) -> None:
        with self._transaction() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS agent_campaign_effects ("
                "effect_id TEXT PRIMARY KEY,"
                "effect_kind TEXT NOT NULL,"
                "request_hash TEXT,"
                "request_payload TEXT,"
                "disposition TEXT NOT NULL,"
                "campaign_id TEXT,"
                "attempt INTEGER,"
                "run_id TEXT,"
                "runtime_reference TEXT,"
                "outcome TEXT,"
                "evidence_pointer TEXT,"
                "error TEXT,"
                "resources_released INTEGER,"
                "created_at REAL NOT NULL,"
                "updated_at REAL NOT NULL)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS agent_campaign_effect_campaign "
                "ON agent_campaign_effects(campaign_id,attempt,effect_kind)"
            )

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        # AgentRunStore deliberately opens SQLite with check_same_thread=False.
        # The Python RLock serializes users of this exact store, while BEGIN
        # IMMEDIATE also serializes separate store instances sharing the DB.
        with self._store._lock:
            connection = self._store._conn
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _select_effect(
        connection: sqlite3.Connection,
        effect_id: str,
    ) -> _Effect | None:
        row = connection.execute(
            "SELECT " + _EFFECT_COLUMNS + " FROM agent_campaign_effects "
            "WHERE effect_id=?",
            (effect_id,),
        ).fetchone()
        return _Effect.from_row(row) if row is not None else None

    @staticmethod
    def _require_same_request(
        effect: _Effect,
        expected_kind: str,
        request_hash: str,
    ) -> None:
        if effect.effect_kind != expected_kind or effect.request_hash != request_hash:
            raise Agent3CampaignDispatchConflictError(
                "deterministic effect identity conflicts with existing request"
            )

    @staticmethod
    def _require_identity(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise Agent3CampaignAdapterError(f"{field_name} must be non-empty")
        return value.strip()

    @staticmethod
    def _canonical(value: object) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
