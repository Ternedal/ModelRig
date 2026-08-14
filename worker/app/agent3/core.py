from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import dataclasses
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable


class StrEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class RouteKind(StrEnum):
    DIRECT_RIG = "direct_rig"
    DIRECT_CLOUD = "direct_cloud"
    RIG_TOOLS_LOCAL = "rig_tools_local"
    RIG_TOOLS_CLOUD = "rig_tools_cloud"
    LOCAL_RAG = "local_rag"
    CLOUD_RAG_VIA_RIG = "cloud_rag_via_rig"
    ASK_BEFORE_DOWNGRADE = "ask_before_downgrade"
    UNAVAILABLE = "unavailable"


class RunState(StrEnum):
    RUNNING = "running"
    WAITING_CONFIRMATION = "waiting_confirmation"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepState(StrEnum):
    PENDING = "pending"
    # The step finished AFTER the run was cancelled. Not a success (nobody
    # wanted it any more) and not a failure (it worked). You cannot un-append a
    # note or un-delete a model, so the honest record is that the side effect
    # happened and the cancellation was late. Saying "cancelled" and nothing
    # else would be a lie about the rig's actual state.
    COMPLETED_AFTER_CANCEL = "completed_after_cancel"
    WAITING_CONFIRMATION = "waiting_confirmation"
    APPROVED = "approved"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    DENIED = "denied"
    BLOCKED = "blocked"
    FAILED = "failed"


class RiskClass(StrEnum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"
    ADMIN = "admin"
    # Added when this branch merged into a main that had grown a desktop class
    # (1.58.52). Without it, integration.py's fallback -- "WRITE if the V2 tool
    # says write, else READ" -- turned a screenshot/click into a READ: no
    # confirmation card, and allowed inside a proactive background run. The most
    # dangerous class in the system became the safest one. Latent only because
    # no tool declares desktop yet.
    DESKTOP = "desktop"


class Sensitivity(StrEnum):
    PUBLIC = "public"
    OPERATIONAL = "operational"
    PRIVATE = "private"
    SECRET = "secret"


class EgressClass(StrEnum):
    NONE = "none"
    LOCAL = "local"
    CLOUD = "cloud"


@dataclass(frozen=True)
class CapabilitySnapshot:
    rig_reachable: bool = False
    worker_ready: bool = False
    tools_ready: bool = False
    cloud_ready: bool = False
    rag_ready: bool = False
    voice_ready: bool = False


@dataclass(frozen=True)
class TurnRequest:
    message: str
    mode: str = "rig"
    tools: bool = False
    rag: bool = False
    has_image: bool = False
    voice: bool = False
    allow_rag_cloud: bool = False
    auto_cloud_fallback: bool = False
    retry_of_run_id: str | None = None
    original_route: RouteKind | None = None
    conversation_id: str | None = None


@dataclass(frozen=True)
class RoutePlan:
    kind: RouteKind
    reason: str
    uses_cloud: bool
    uses_rig: bool
    uses_tools: bool
    uses_rag: bool
    requires_user_choice: bool = False


@dataclass
class AgentStep:
    tool: str
    args: dict[str, Any]
    risk: RiskClass
    sensitivity: Sensitivity = Sensitivity.OPERATIONAL
    egress: EgressClass = EgressClass.LOCAL
    origin: str = "local"
    # Whether running this again is the same as running it once (F-614). Stamped
    # from the registry when the step is built, exactly as risk and sensitivity
    # are: the step is the decision's snapshot, and recovery must not have to go
    # and ask a registry that may have changed since.
    #
    # False by default. A step that arrived without an answer is a step we do
    # not replay.
    idempotent: bool = False
    conversation_id: str | None = None
    summary: str = ""
    state: StepState = StepState.PENDING
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    result: Any = None
    error: str | None = None
    confirmation_digest: str | None = None
    confirmation_expires_at: float | None = None

    def cloned_for_retry(self) -> "AgentStep":
        """A fresh copy of this step's PLAN, carrying every declared property.

        Retry rebuilt steps by hand-listing fields to copy, in two identical
        functions (F-715). I added `idempotent` to this dataclass and updated
        the builder and forgot both cloners, so a replayable read came back from
        retry as non-idempotent and blocked itself after an interruption --
        undoing the recovery feature two commits after shipping it.

        The bug is hand-listing. A copy that names the fields it keeps forgets
        the next field added. So this copies EVERYTHING via replace, then resets
        only what a retry must reset: a new id, no result or error, back to
        PENDING, and no stale confirmation. Properties that describe what the
        action IS -- risk, sensitivity, egress, idempotent, and whatever axis is
        added next -- travel automatically, because forgetting them is the
        failure and the default should not be the failure.
        """
        return dataclasses.replace(
            self,
            id=str(uuid.uuid4()),
            state=StepState.PENDING,
            result=None,
            error=None,
            confirmation_digest=None,
            confirmation_expires_at=None,
        )


@dataclass
class AgentRun:
    request: TurnRequest
    route: RoutePlan
    steps: list[AgentStep]
    state: RunState = RunState.RUNNING
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    current_step: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    answer: str | None = None
    error: str | None = None
    proactive: bool = False
    allow_private_cloud: bool = False
    schema_version: int = 1

    def to_json(self) -> str:
        payload = asdict(self)
        payload["state"] = self.state.value
        payload["route"]["kind"] = self.route.kind.value
        if self.request.original_route is not None:
            payload["request"]["original_route"] = self.request.original_route.value
        for step in payload["steps"]:
            for key in ("risk", "sensitivity", "egress", "state"):
                value = step[key]
                step[key] = value.value if isinstance(value, Enum) else value
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def from_json(raw: str) -> "AgentRun":
        data = json.loads(raw)
        request_data = data.pop("request")
        if request_data.get("original_route"):
            request_data["original_route"] = RouteKind(request_data["original_route"])
        route_data = data.pop("route")
        route_data["kind"] = RouteKind(route_data["kind"])
        steps = []
        for step in data.pop("steps"):
            step["risk"] = RiskClass(step["risk"])
            step["sensitivity"] = Sensitivity(step["sensitivity"])
            step["egress"] = EgressClass(step["egress"])
            step["state"] = StepState(step["state"])
            steps.append(AgentStep(**step))
        data["state"] = RunState(data["state"])
        return AgentRun(TurnRequest(**request_data), RoutePlan(**route_data), steps, **data)


class TurnRouter:
    """Pure route decision reused by first send, retry and future voice turns."""

    def route(self, req: TurnRequest, caps: CapabilitySnapshot) -> RoutePlan:
        if req.retry_of_run_id and req.original_route:
            return self._reuse(req.original_route, caps)

        cloud = req.mode == "cloud"
        if req.rag:
            if not caps.rig_reachable or not caps.rag_ready:
                return self._unavailable("RAG requires a reachable, ready rig")
            if cloud:
                if not req.allow_rag_cloud:
                    return self._unavailable("RAG content needs explicit cloud consent")
                if not caps.cloud_ready:
                    return self._unavailable("Cloud is unavailable")
                return RoutePlan(
                    RouteKind.CLOUD_RAG_VIA_RIG,
                    "Local retrieval, cloud synthesis with consent",
                    True,
                    True,
                    req.tools,
                    True,
                )
            return RoutePlan(RouteKind.LOCAL_RAG, "RAG stays local", False, True, req.tools, True)

        if req.tools:
            if caps.rig_reachable and caps.worker_ready and caps.tools_ready:
                if cloud:
                    if not caps.cloud_ready:
                        return self._unavailable("Cloud is unavailable")
                    return RoutePlan(
                        RouteKind.RIG_TOOLS_CLOUD,
                        "Cloud model through the rig gate",
                        True,
                        True,
                        True,
                        False,
                    )
                return RoutePlan(
                    RouteKind.RIG_TOOLS_LOCAL,
                    "Local model through the rig gate",
                    False,
                    True,
                    True,
                    False,
                )
            if cloud and caps.cloud_ready:
                return RoutePlan(
                    RouteKind.ASK_BEFORE_DOWNGRADE,
                    "Tools are unavailable; plain cloud chat needs user choice",
                    True,
                    False,
                    False,
                    False,
                    True,
                )
            return self._unavailable("Tools require a ready rig")

        if cloud:
            if caps.cloud_ready:
                return RoutePlan(RouteKind.DIRECT_CLOUD, "Explicit cloud mode", True, False, False, False)
            return self._unavailable("Cloud is unavailable")

        if caps.rig_reachable and caps.worker_ready:
            return RoutePlan(RouteKind.DIRECT_RIG, "Explicit local rig mode", False, True, False, False)

        if req.auto_cloud_fallback and not req.has_image and caps.cloud_ready:
            return RoutePlan(
                RouteKind.ASK_BEFORE_DOWNGRADE,
                "Cloud fallback requires user choice",
                True,
                False,
                False,
                False,
                True,
            )
        return self._unavailable("No approved route is available")

    @classmethod
    def _reuse(cls, kind: RouteKind, caps: CapabilitySnapshot) -> RoutePlan:
        requirements = {
            RouteKind.DIRECT_RIG: (False, True, False, False),
            RouteKind.DIRECT_CLOUD: (True, False, False, False),
            RouteKind.RIG_TOOLS_LOCAL: (False, True, True, False),
            RouteKind.RIG_TOOLS_CLOUD: (True, True, True, False),
            RouteKind.LOCAL_RAG: (False, True, False, True),
            RouteKind.CLOUD_RAG_VIA_RIG: (True, True, False, True),
        }
        values = requirements.get(kind)
        if values is None:
            return cls._unavailable("Original route cannot be retried automatically")
        cloud, rig, tools, rag = values
        if cloud and not caps.cloud_ready:
            return cls._unavailable("Original cloud route is no longer available")
        if rig and (not caps.rig_reachable or not caps.worker_ready):
            return cls._unavailable("Original rig route is no longer available")
        if tools and not caps.tools_ready:
            return cls._unavailable("Original tools route is no longer available")
        if rag and not caps.rag_ready:
            return cls._unavailable("Original RAG route is no longer available")
        return RoutePlan(kind, "Retry reuses the original route", cloud, rig, tools, rag)

    @staticmethod
    def _unavailable(reason: str) -> RoutePlan:
        return RoutePlan(RouteKind.UNAVAILABLE, reason, False, False, False, False)


@dataclass(frozen=True)
class PolicyDecision:
    action: str
    reason: str


class PolicyEngine:
    """Deterministic policy. Models never decide confirmation or egress rules."""

    def evaluate(
        self,
        step: AgentStep,
        *,
        proactive: bool = False,
        allow_private_cloud: bool = False,
    ) -> PolicyDecision:
        if proactive and step.risk != RiskClass.READ:
            return PolicyDecision("block", "Proactive runs are read-only")
        if step.egress == EgressClass.CLOUD:
            if step.sensitivity == Sensitivity.SECRET:
                return PolicyDecision("block", "Secret data may never leave the rig")
            if step.sensitivity == Sensitivity.PRIVATE and not allow_private_cloud:
                return PolicyDecision("block", "Private data needs explicit cloud consent")
        if step.risk in {RiskClass.WRITE, RiskClass.DESTRUCTIVE, RiskClass.ADMIN,
                         RiskClass.DESKTOP}:
            return PolicyDecision("confirm", f"{step.risk.value} requires a fresh confirmation")
        return PolicyDecision("execute", "Read-only step allowed")


class AgentRunStore:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS agent_runs ("
            "id TEXT PRIMARY KEY, state TEXT NOT NULL, payload TEXT NOT NULL, updated_at REAL NOT NULL)"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS agent_events ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, ts REAL NOT NULL, "
            "kind TEXT NOT NULL, payload TEXT NOT NULL)"
        )
        self._conn.commit()

    def save(self, run: AgentRun) -> None:
        run.updated_at = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT INTO agent_runs VALUES (?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET state=excluded.state,payload=excluded.payload,updated_at=excluded.updated_at",
                (run.id, run.state.value, run.to_json(), run.updated_at),
            )
            self._conn.commit()

    def load(self, run_id: str) -> AgentRun | None:
        with self._lock:
            row = self._conn.execute("SELECT payload FROM agent_runs WHERE id=?", (run_id,)).fetchone()
        return AgentRun.from_json(row[0]) if row else None

    def recent(self, limit: int = 50) -> list[AgentRun]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload FROM agent_runs ORDER BY updated_at DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [AgentRun.from_json(row[0]) for row in rows]

    def save_with_event(self, run: AgentRun, kind: str, payload: Any) -> None:
        """Write the state and the event that explains it in ONE transaction.

        They were two commits (F-309). A crash in the gap leaves a rig whose
        state nothing accounts for -- a run sitting in CANCELLED with no
        run_cancelled event, or an event saying a step started against a state
        that never moved. Both are worse than a crash: the machine has a
        history that disagrees with itself, and every later question ("who
        cancelled this?", "did the tool run?") gets an answer built on that
        disagreement.

        SQLite gives this for free on one connection -- the two INSERTs simply
        have to share a commit. It was never a hard problem; it was an unasked
        question.
        """
        run.updated_at = time.time()
        encoded = payload if isinstance(payload, str) else json.dumps(
            payload, ensure_ascii=False, sort_keys=True)
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO agent_runs VALUES (?,?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET state=excluded.state,"
                    "payload=excluded.payload,updated_at=excluded.updated_at",
                    (run.id, run.state.value, run.to_json(), run.updated_at),
                )
                self._conn.execute(
                    "INSERT INTO agent_events(run_id,ts,kind,payload) VALUES(?,?,?,?)",
                    (run.id, time.time(), kind, encoded[:8000]),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def save_with_event_if_unchanged(
        self,
        run: AgentRun,
        *,
        expected_state: RunState,
        expected_payload: str,
        kind: str,
        payload: Any,
    ) -> bool:
        """Atomically write state+event only if nobody changed the run first."""
        run.updated_at = time.time()
        encoded = payload if isinstance(payload, str) else json.dumps(
            payload, ensure_ascii=False, sort_keys=True)
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                changed = self._conn.execute(
                    "UPDATE agent_runs SET state=?,payload=?,updated_at=? "
                    "WHERE id=? AND state=? AND payload=?",
                    (
                        run.state.value,
                        run.to_json(),
                        run.updated_at,
                        run.id,
                        expected_state.value,
                        expected_payload,
                    ),
                ).rowcount
                if changed != 1:
                    self._conn.rollback()
                    return False
                self._conn.execute(
                    "INSERT INTO agent_events(run_id,ts,kind,payload) VALUES(?,?,?,?)",
                    (run.id, time.time(), kind, encoded[:8000]),
                )
                self._conn.commit()
                return True
            except Exception:
                self._conn.rollback()
                raise

    def save_if_unchanged(
        self,
        run: AgentRun,
        *,
        expected_state: RunState,
        expected_payload: str,
    ) -> bool:
        """Compare-and-swap a run when the transition has no journal event.

        Step-index progression is state, not a new event. It still must not
        overwrite a cancellation that lands after the preceding step outcome.
        """
        run.updated_at = time.time()
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                changed = self._conn.execute(
                    "UPDATE agent_runs SET state=?,payload=?,updated_at=? "
                    "WHERE id=? AND state=? AND payload=?",
                    (
                        run.state.value,
                        run.to_json(),
                        run.updated_at,
                        run.id,
                        expected_state.value,
                        expected_payload,
                    ),
                ).rowcount
                if changed != 1:
                    self._conn.rollback()
                    return False
                self._conn.commit()
                return True
            except Exception:
                self._conn.rollback()
                raise

    def event(self, run_id: str, kind: str, payload: Any) -> None:
        encoded = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self._lock:
            self._conn.execute(
                "INSERT INTO agent_events(run_id,ts,kind,payload) VALUES(?,?,?,?)",
                (run_id, time.time(), kind, encoded[:8000]),
            )
            self._conn.commit()

    def events(self, run_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts,kind,payload FROM agent_events WHERE run_id=? ORDER BY id ASC LIMIT ?",
                (run_id, max(1, min(limit, 1000))),
            ).fetchall()
        result = []
        for ts, kind, payload in rows:
            try:
                value = json.loads(payload)
            except json.JSONDecodeError:
                value = payload
            result.append({"ts": ts, "kind": kind, "payload": value})
        return result


class ConfirmationError(RuntimeError):
    pass


class RunConflict(RuntimeError):
    pass


Planner = Callable[[TurnRequest, RouteKind], list[AgentStep]]
Executor = Callable[[AgentStep], Any]


class Agent3Orchestrator:
    """Persistent Agent 3.0 execution substrate.

    It deliberately does not replace Agent v2's LLM loop yet. A validated plan can
    be supplied explicitly, while the V2 adapter remains the executor/security
    boundary. The production `/tools/chat` path is untouched.
    """

    def __init__(
        self,
        store: AgentRunStore,
        executor: Executor,
        planner: Planner | None = None,
        answerer: Callable[[AgentRun], str] | None = None,
        max_steps: int = 12,
        confirmation_ttl_seconds: int = 60,
    ):
        self.store = store
        self.planner = planner
        self.executor = executor
        self.answerer = answerer or (lambda _: "Færdig.")
        self.router = TurnRouter()
        self.policy = PolicyEngine()
        self.max_steps = max(1, max_steps)
        self.confirmation_ttl_seconds = max(5, confirmation_ttl_seconds)

    def start(
        self,
        request: TurnRequest,
        caps: CapabilitySnapshot,
        *,
        proactive: bool = False,
        allow_private_cloud: bool = False,
    ) -> AgentRun:
        if self.planner is None:
            raise RunConflict("no planner configured; use start_with_steps for the experimental draft")
        route = self.router.route(request, caps)
        if route.kind in {RouteKind.UNAVAILABLE, RouteKind.ASK_BEFORE_DOWNGRADE}:
            return self._blocked_run(request, route, route.reason, proactive, allow_private_cloud)
        steps = self.planner(request, route.kind)
        return self._start_routed(request, route, steps, proactive, allow_private_cloud)

    def start_with_steps(
        self,
        request: TurnRequest,
        caps: CapabilitySnapshot,
        steps: Iterable[AgentStep],
        *,
        proactive: bool = False,
        allow_private_cloud: bool = False,
    ) -> AgentRun:
        route = self.router.route(request, caps)
        if route.kind in {RouteKind.UNAVAILABLE, RouteKind.ASK_BEFORE_DOWNGRADE}:
            return self._blocked_run(request, route, route.reason, proactive, allow_private_cloud)
        return self._start_routed(request, route, list(steps), proactive, allow_private_cloud)

    def _start_routed(
        self,
        request: TurnRequest,
        route: RoutePlan,
        steps: list[AgentStep],
        proactive: bool,
        allow_private_cloud: bool,
    ) -> AgentRun:
        if len(steps) > self.max_steps:
            return self._blocked_run(
                request,
                route,
                f"Plan exceeds max_steps ({self.max_steps})",
                proactive,
                allow_private_cloud,
                steps[: self.max_steps],
            )
        run = AgentRun(
            request=request,
            route=route,
            steps=steps,
            proactive=proactive,
            allow_private_cloud=allow_private_cloud,
        )
        self.store.save_with_event(
            run, "run_created", {"route": route.kind.value, "steps": len(steps)})
        return self.advance(run.id)

    def _blocked_run(
        self,
        request: TurnRequest,
        route: RoutePlan,
        reason: str,
        proactive: bool,
        allow_private_cloud: bool,
        steps: list[AgentStep] | None = None,
    ) -> AgentRun:
        run = AgentRun(
            request=request,
            route=route,
            steps=steps or [],
            state=RunState.BLOCKED,
            error=reason,
            proactive=proactive,
            allow_private_cloud=allow_private_cloud,
        )
        self.store.save_with_event(run, "run_blocked", {"reason": reason})
        return run

    def advance(self, run_id: str) -> AgentRun:
        run = self._require(run_id)
        if run.state in {RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED}:
            return run
        if run.state == RunState.WAITING_CONFIRMATION:
            return run

        while run.current_step < len(run.steps):
            step = run.steps[run.current_step]

            if step.state == StepState.SUCCEEDED:
                conflict = self._advance_succeeded_step(run)
                if conflict is not None:
                    return conflict
                continue
            if step.state == StepState.EXECUTING:
                if step.idempotent:
                    step.state = StepState.PENDING
                    step.error = None
                    self.store.save_with_event(
                        run, "interrupted_execution_replayable",
                        {"step_id": step.id, "tool": step.tool})
                    continue
                step.state = StepState.BLOCKED
                step.error = "Execution was interrupted; verify the side effect manually before resuming"
                run.state = RunState.BLOCKED
                run.error = step.error
                self.store.save_with_event(
                    run, "interrupted_execution", {"step_id": step.id, "tool": step.tool})
                return run
            if step.state == StepState.WAITING_CONFIRMATION:
                run.state = RunState.WAITING_CONFIRMATION
                self.store.save(run)
                return run
            if step.state in {StepState.DENIED, StepState.BLOCKED, StepState.FAILED}:
                run.state = RunState.BLOCKED if step.state == StepState.BLOCKED else RunState.FAILED
                run.error = step.error or f"Step {step.state.value}"
                self.store.save(run)
                return run

            decision = self.policy.evaluate(
                step,
                proactive=run.proactive,
                allow_private_cloud=run.allow_private_cloud,
            )
            if decision.action == "block":
                step.state = StepState.BLOCKED
                step.error = decision.reason
                run.state = RunState.BLOCKED
                run.error = decision.reason
                self.store.save_with_event(
                    run,
                    "policy_decision",
                    {"step_id": step.id, "tool": step.tool,
                     "action": decision.action, "reason": decision.reason},
                )
                return run
            self.store.event(
                run.id,
                "policy_decision",
                {"step_id": step.id, "tool": step.tool, "action": decision.action, "reason": decision.reason},
            )
            if decision.action == "confirm" and step.state != StepState.APPROVED:
                step.state = StepState.WAITING_CONFIRMATION
                step.confirmation_digest = self._digest(step)
                step.confirmation_expires_at = time.time() + self.confirmation_ttl_seconds
                run.state = RunState.WAITING_CONFIRMATION
                self.store.save_with_event(
                    run,
                    "confirmation_required",
                    {
                        "step_id": step.id,
                        "tool": step.tool,
                        "summary": step.summary,
                        "expires_at": step.confirmation_expires_at,
                    },
                )
                return run

            self._execute(run, step)
            if run.state in {RunState.FAILED, RunState.CANCELLED, RunState.BLOCKED}:
                return run
            conflict = self._advance_succeeded_step(run)
            if conflict is not None:
                return conflict

        expected_payload = run.to_json()
        answer = self.answerer(run)
        run.state = RunState.COMPLETED
        run.answer = answer
        if not self.store.save_with_event_if_unchanged(
            run,
            expected_state=RunState.RUNNING,
            expected_payload=expected_payload,
            kind="run_completed",
            payload={"steps": len(run.steps)},
        ):
            fresh = self._require(run.id)
            if fresh.state == RunState.CANCELLED:
                return fresh
            raise RunConflict("run changed while final completion was being committed")
        return run

    def confirm(self, run_id: str, step_id: str, decision: str, digest: str) -> AgentRun:
        run = self._require(run_id)
        if run.state != RunState.WAITING_CONFIRMATION:
            raise ConfirmationError("run is not waiting for confirmation")
        if run.current_step >= len(run.steps):
            raise ConfirmationError("run has no current step")
        step = run.steps[run.current_step]
        expected = self._digest(step)
        if step.id != step_id or digest != expected or step.confirmation_digest != expected:
            raise ConfirmationError("confirmation no longer matches the immutable step")
        expected_payload = run.to_json()
        if step.confirmation_expires_at is None or time.time() > step.confirmation_expires_at:
            step.state = StepState.DENIED
            step.error = "Confirmation expired"
            run.state = RunState.CANCELLED
            run.error = step.error
            if not self.store.save_with_event_if_unchanged(
                run,
                expected_state=RunState.WAITING_CONFIRMATION,
                expected_payload=expected_payload,
                kind="confirmation_expired",
                payload={"step_id": step.id},
            ):
                raise ConfirmationError("run changed while confirmation was being decided")
            raise ConfirmationError("confirmation expired")
        if decision not in {"approve", "deny"}:
            raise ConfirmationError("decision must be approve or deny")
        if decision == "deny":
            step.state = StepState.DENIED
            step.error = "Denied by user"
            run.state = RunState.CANCELLED
            run.error = step.error
            step.confirmation_digest = None
            if not self.store.save_with_event_if_unchanged(
                run,
                expected_state=RunState.WAITING_CONFIRMATION,
                expected_payload=expected_payload,
                kind="confirmation_denied",
                payload={"step_id": step.id},
            ):
                raise ConfirmationError("run changed while confirmation was being decided")
            return run

        step.state = StepState.APPROVED
        step.confirmation_digest = None
        run.state = RunState.RUNNING
        if not self.store.save_with_event_if_unchanged(
            run,
            expected_state=RunState.WAITING_CONFIRMATION,
            expected_payload=expected_payload,
            kind="confirmation_approved",
            payload={"step_id": step.id, "tool": step.tool},
        ):
            raise ConfirmationError("run changed while confirmation was being decided")
        return self.advance(run.id)

    def cancel(self, run_id: str) -> AgentRun:
        run = self._require(run_id)
        if run.state not in {RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED}:
            run.state = RunState.CANCELLED
            run.error = "Cancelled by user"
            self.store.save_with_event(run, "run_cancelled", {})
        return run

    def _execute(self, run: AgentRun, step: AgentStep) -> None:
        expected_payload = run.to_json()
        step.state = StepState.EXECUTING
        if not self.store.save_with_event_if_unchanged(
            run,
            expected_state=RunState.RUNNING,
            expected_payload=expected_payload,
            kind="step_started",
            payload={"step_id": step.id, "tool": step.tool},
        ):
            fresh = self.store.load(run.id)
            if fresh is not None and fresh.state == RunState.CANCELLED:
                run.state = RunState.CANCELLED
                run.error = fresh.error or "Cancelled by user"
                step.state = StepState.APPROVED
                return
            run.state = RunState.BLOCKED
            run.error = "Run changed before execution could start"
            step.state = StepState.BLOCKED
            step.error = run.error
            return

        # This is the exact persisted EXECUTING snapshot. Every outcome below
        # must CAS against it; a read-then-save cancellation check has another
        # race between the read and the save.
        execution_payload = run.to_json()
        try:
            result = self.executor(step)
        except Exception as exc:
            step.state = StepState.FAILED
            step.error = str(exc)
            run.state = RunState.FAILED
            run.error = f"{step.tool} failed: {exc}"
            if self.store.save_with_event_if_unchanged(
                run,
                expected_state=RunState.RUNNING,
                expected_payload=execution_payload,
                kind="step_failed",
                payload={"step_id": step.id, "tool": step.tool, "error": str(exc)},
            ):
                return
            if self._merge_cancelled_step_outcome(
                run,
                step,
                state=StepState.FAILED,
                result=None,
                error=str(exc),
                kind="step_failed_after_cancel",
                payload={"step_id": step.id, "tool": step.tool, "error": str(exc)},
            ):
                return
            raise RunConflict("run changed while executor failure was being committed")

        step.result = result
        step.state = StepState.SUCCEEDED
        step.error = None
        if self.store.save_with_event_if_unchanged(
            run,
            expected_state=RunState.RUNNING,
            expected_payload=execution_payload,
            kind="step_succeeded",
            payload={"step_id": step.id, "tool": step.tool},
        ):
            return
        if self._merge_cancelled_step_outcome(
            run,
            step,
            state=StepState.COMPLETED_AFTER_CANCEL,
            result=result,
            error=None,
            kind="step_completed_after_cancel",
            payload={"step_id": step.id, "tool": step.tool},
        ):
            return
        raise RunConflict("run changed while executor result was being committed")

    def _advance_succeeded_step(self, run: AgentRun) -> AgentRun | None:
        """Advance current_step without overwriting a concurrent cancellation."""
        expected_payload = run.to_json()
        run.current_step += 1
        run.state = RunState.RUNNING
        if self.store.save_if_unchanged(
            run,
            expected_state=RunState.RUNNING,
            expected_payload=expected_payload,
        ):
            return None
        fresh = self._require(run.id)
        if fresh.state == RunState.CANCELLED:
            return fresh
        raise RunConflict("run changed while step progression was being committed")

    def _merge_cancelled_step_outcome(
        self,
        run: AgentRun,
        step: AgentStep,
        *,
        state: StepState,
        result: Any,
        error: str | None,
        kind: str,
        payload: Any,
    ) -> bool:
        """Record an already-real executor outcome without resurrecting stop.

        If the outcome CAS lost specifically because cancel committed first,
        take the CANCELLED payload as authority and merge only the current
        step's observed outcome into it. The second CAS prevents this repair
        from overwriting any later mutation.
        """
        fresh = self.store.load(run.id)
        if fresh is None or fresh.state != RunState.CANCELLED:
            return False
        if fresh.current_step >= len(fresh.steps):
            return False
        fresh_step = fresh.steps[fresh.current_step]
        if fresh_step.id != step.id:
            return False
        expected_payload = fresh.to_json()
        fresh_step.state = state
        fresh_step.result = result
        fresh_step.error = error
        if not self.store.save_with_event_if_unchanged(
            fresh,
            expected_state=RunState.CANCELLED,
            expected_payload=expected_payload,
            kind=kind,
            payload=payload,
        ):
            return False
        run.state = RunState.CANCELLED
        run.error = fresh.error or "Cancelled by user"
        run.current_step = fresh.current_step
        run.updated_at = fresh.updated_at
        step.state = state
        step.result = result
        step.error = error
        return True

    def _require(self, run_id: str) -> AgentRun:
        run = self.store.load(run_id)
        if run is None:
            raise KeyError(run_id)
        return run

    @staticmethod
    def _digest(step: AgentStep) -> str:
        raw = json.dumps(
            {
                "id": step.id,
                "tool": step.tool,
                "args": step.args,
                "risk": step.risk.value,
                "sensitivity": step.sensitivity.value,
                "egress": step.egress.value,
                "origin": step.origin,
                "idempotent": step.idempotent,
                "conversation_id": step.conversation_id,
                "summary": step.summary,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode()).hexdigest()
