#!/usr/bin/env python3
"""C18-B production supervisor lifecycle regression tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_supervisor_lifecycle.py
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    ClockSample,
    CognitiveProfile,
    ConsciousnessCoreRuntime,
    PersistentSelfState,
    PersonalitySnapshot,
    RuntimeWorldState,
    SelfAffect,
    WorkspaceCandidate,
    WorldObservation,
    build_workspace,
    workspace_ref,
    world_state_ref,
)
from app.consciousness_core.supervisor import (  # noqa: E402
    CognitionEvent,
    SupervisorPolicy,
)
from app.consciousness_core.supervisor_lifecycle import (  # noqa: E402
    SUPERVISOR_LIFECYCLE_FLAG,
    ProductionSupervisorBridge,
    compose_supervisor_lifecycle_lifespan,
    production_supervisor_bridge_factory,
    supervisor_lifecycle_enabled,
)
from app.consciousness_core.production_lifecycle import TrustedRuntimeClock  # noqa: E402


FIXTURES = json.loads(
    (ROOT / "contracts" / "consciousness-core" / "fixtures-v1.json").read_text(
        encoding="utf-8"
    )
)

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


def run(coro):
    return asyncio.run(coro)


class Engine:
    def __init__(self):
        self.calls = 0

    async def think(self, request, cognitive_profile, *, context=None):
        self.calls += 1
        payload = copy.deepcopy(FIXTURES["thought_proposal"])
        payload["request_id"] = request.request_id
        payload["proposal_id"] = "thinkprop-" + "7" * 32
        payload["interpretation"] = "Process one explicitly submitted event."
        payload["attention_suggestions"] = []
        payload["uncertainty"] = 0.2
        return payload


class BlockingEngine(Engine):
    def __init__(self):
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def think(self, request, cognitive_profile, *, context=None):
        self.calls += 1
        self.entered.set()
        await self.release.wait()
        payload = copy.deepcopy(FIXTURES["thought_proposal"])
        payload["request_id"] = request.request_id
        payload["proposal_id"] = "thinkprop-" + "6" * 32
        payload["interpretation"] = "Single-flight supervisor step completed."
        payload["attention_suggestions"] = []
        payload["uncertainty"] = 0.15
        return payload


def clock_factory():
    wall_values = iter(
        [
            1_700_000_000_000_000_000,
            1_700_000_001_000_000_000,
            1_700_000_002_000_000_000,
            1_700_000_003_000_000_000,
            1_700_000_004_000_000_000,
        ]
    )
    mono_values = iter(
        [
            10_000_000_000,
            11_000_000_000,
            12_000_000_000,
            13_000_000_000,
            14_000_000_000,
        ]
    )
    return TrustedRuntimeClock(
        wall_time_ns=lambda: next(wall_values),
        monotonic_ns=lambda: next(mono_values),
    )


def contexts():
    world = RuntimeWorldState(
        schema="kaliv-consciousness-core/world-state/v1",
        world_id="world-" + "c" * 32,
        revision=11,
        observations=[
            WorldObservation(
                observation_id="obs-" + "d" * 32,
                subject_ref="project:modelrig",
                proposition="C18-B bridge received an explicit event.",
                confidence=1.0,
                epistemic_status="observed",
                source_refs=["runtime:test"],
            )
        ],
        production_activation=False,
    )
    workspace = build_workspace(
        cycle_id="cycle-" + "e" * 32,
        max_active=8,
        candidates=[
            WorkspaceCandidate(
                candidate_id="wc-" + "1" * 32,
                kind="memory",
                salience=0.7,
                summary="Supervisor lifecycle remains explicit-call only.",
                source_ref="docs:c18b",
            )
        ],
    )
    personality = PersonalitySnapshot(
        person_revision="person-r0007",
        personality_revision="personality-r0005",
        personality_state_ref="personality-state:pstate-" + "7" * 32,
        source_refs=["person-profile:person-r0007"],
    )
    profile = CognitiveProfile(
        schema="kaliv-consciousness-core/cognitive-profile/v1",
        profile_id="cog-" + "f" * 32,
        engine_instance_id="engine:test:c18b",
        provider="mock",
        model="replaceable-c18b",
        reasoning_depth=0.7,
        planning_capacity=0.7,
        context_capacity_tokens=8192,
        multimodal_capacity=0.0,
        tool_reasoning=0.0,
        uncertainty_calibration=0.9,
        ephemeral=True,
        identity_authority=False,
        persistent_state_authority=False,
        action_authority=False,
        production_activation=False,
    )
    state = PersistentSelfState(
        schema="kaliv-consciousness-core/self-state/v1",
        self_id="self-" + "a" * 32,
        revision=40,
        person_id="person-" + "b" * 32,
        person_revision=personality.person_revision,
        personality_state_ref=personality.personality_state_ref,
        world_state_ref=world_state_ref(world),
        workspace_ref=workspace_ref(workspace),
        active_goal_refs=["goal:consciousness-core"],
        active_intention_refs=["intent:continue-core"],
        affect=SelfAffect(
            labels=["focused"],
            valence=0.1,
            arousal=0.3,
            confidence=0.9,
            source_refs=["runtime:test"],
        ),
        known_uncertainties=[],
        last_experience_ref="memory4:experience:last",
        production_activation=False,
    )
    return state, world, workspace, personality, profile


old_env = {
    SUPERVISOR_LIFECYCLE_FLAG: os.environ.get(SUPERVISOR_LIFECYCLE_FLAG),
    "KALIV_CONSCIOUSNESS_CORE_ENABLED": os.environ.get(
        "KALIV_CONSCIOUSNESS_CORE_ENABLED"
    ),
}

try:
    # --- exact flag contract ---------------------------------------------------
    check(
        not supervisor_lifecycle_enabled({}),
        "C18-B supervisor lifecycle is disabled by default",
    )
    check(
        supervisor_lifecycle_enabled({SUPERVISOR_LIFECYCLE_FLAG: "1"}),
        "exact supervisor value 1 enables the lifecycle gate",
    )
    for value in ("true", "on", "yes", "01", " 1 "):
        check(
            not supervisor_lifecycle_enabled(
                {SUPERVISOR_LIFECYCLE_FLAG: value}
            ),
            f"non-exact supervisor opt-in {value!r} remains disabled",
        )

    # --- supervisor OFF: runtime factory is not touched -----------------------
    calls = {"runtime": 0}

    def counted_runtime_factory():
        calls["runtime"] += 1
        raise AssertionError("runtime factory must not be called")

    os.environ.pop(SUPERVISOR_LIFECYCLE_FLAG, None)
    os.environ["KALIV_CONSCIOUSNESS_CORE_ENABLED"] = "1"
    bridge = production_supervisor_bridge_factory(
        object(),
        runtime_factory=counted_runtime_factory,
        clock_factory=clock_factory,
    )
    check(bridge is None, "supervisor OFF produces no production bridge")
    check(
        calls["runtime"] == 0,
        "supervisor OFF does not compose/import the ThoughtEngine runtime",
    )

    # --- supervisor ON but Core OFF: still inert ------------------------------
    os.environ[SUPERVISOR_LIFECYCLE_FLAG] = "1"
    os.environ.pop("KALIV_CONSCIOUSNESS_CORE_ENABLED", None)
    bridge = production_supervisor_bridge_factory(
        object(),
        runtime_factory=counted_runtime_factory,
        clock_factory=clock_factory,
    )
    check(bridge is None, "supervisor ON + Core OFF produces no bridge")
    check(
        calls["runtime"] == 0,
        "Core OFF blocks provider/runtime composition before factory call",
    )

    # --- double opt-in builds one in-memory explicit-call bridge --------------
    os.environ[SUPERVISOR_LIFECYCLE_FLAG] = "1"
    os.environ["KALIV_CONSCIOUSNESS_CORE_ENABLED"] = "1"
    engine = Engine()
    bridge = production_supervisor_bridge_factory(
        object(),
        runtime_factory=lambda: ConsciousnessCoreRuntime(engine),
        clock_factory=clock_factory,
    )
    check(
        isinstance(bridge, ProductionSupervisorBridge),
        "exact double opt-in creates the in-process supervisor bridge",
    )
    check(
        bridge is not None and bridge.state.pending_events == [],
        "bridge starts with no fabricated cognition events",
    )
    check(engine.calls == 0, "bridge construction invokes no ThoughtEngine call")

    # IDLE planning/step never invokes model.
    state, world, workspace, personality, profile = contexts()
    idle = run(
        bridge.step(
            current_state=state,
            current_world=world,
            current_workspace=workspace,
            personality_snapshot=personality,
            profile=profile,
        )
    )
    check(idle.plan.decision == "IDLE", "empty bridge step is deterministically IDLE")
    check(not idle.thought_engine_invoked, "IDLE bridge step invokes no model")
    check(engine.calls == 0, "IDLE leaves ThoughtEngine call count at zero")
    check(
        idle.cycle_result is None,
        "IDLE bridge step creates no fake cognitive-cycle result",
    )

    # Explicit submit + explicit step => exactly one C18-A cycle.
    bridge.submit(
        CognitionEvent(
            schema="kaliv-consciousness-core/cognition-event/v1",
            event_id="cevt-" + "1" * 32,
            kind="user_turn",
            source_ref="event:user-turn:test",
            summary="User explicitly asked the Consciousness Core to continue.",
            salience=1.0,
            observed_sequence=1,
            production_activation=False,
        )
    )
    active = run(
        bridge.step(
            current_state=state,
            current_world=world,
            current_workspace=workspace,
            personality_snapshot=personality,
            profile=profile,
        )
    )
    check(active.plan.decision == "RUN", "submitted event produces a RUN plan")
    check(active.thought_engine_invoked, "RUN step records one model invocation")
    check(engine.calls == 1, "one explicit RUN causes exactly one ThoughtEngine call")
    check(
        active.cycle_result is not None
        and active.cycle_result.receipt.automatic_repeat is False,
        "C18-B preserves C18-A no-auto-repeat receipt",
    )
    check(
        active.cycle_result is not None
        and active.cycle_result.receipt.execution_authority is False,
        "C18-B grants no execution authority",
    )

    # A fresh bridge with a larger pacing interval returns WAIT with zero model calls.
    wait_engine = Engine()
    wait_bridge = ProductionSupervisorBridge(
        runtime=ConsciousnessCoreRuntime(wait_engine),
        clock=clock_factory(),
        policy=SupervisorPolicy(
            schema="kaliv-consciousness-core/supervisor-policy/v1",
            min_cycle_interval_ms=1500,
            max_events_per_cycle=4,
            production_activation=False,
        ),
    )
    wait_bridge.submit(
        CognitionEvent(
            schema="kaliv-consciousness-core/cognition-event/v1",
            event_id="cevt-" + "3" * 32,
            kind="world_change",
            source_ref="event:wait-test",
            summary="Event should wait for the minimum cycle interval.",
            salience=0.8,
            observed_sequence=3,
            production_activation=False,
        )
    )
    wait_step = run(
        wait_bridge.step(
            current_state=state,
            current_world=world,
            current_workspace=workspace,
            personality_snapshot=personality,
            profile=profile,
        )
    )
    check(wait_step.plan.decision == "WAIT", "pacing can return WAIT")
    check(not wait_step.thought_engine_invoked, "WAIT invokes no ThoughtEngine")
    check(wait_engine.calls == 0, "WAIT leaves model call count at zero")

    # Concurrent submit during an awaited model call fails closed instead of
    # silently losing the newly queued event.
    async def exercise_single_flight():
        blocking_engine = BlockingEngine()
        concurrent_bridge = ProductionSupervisorBridge(
            runtime=ConsciousnessCoreRuntime(blocking_engine),
            clock=clock_factory(),
        )
        concurrent_bridge.submit(
            CognitionEvent(
                schema="kaliv-consciousness-core/cognition-event/v1",
                event_id="cevt-" + "4" * 32,
                kind="user_turn",
                source_ref="event:single-flight",
                summary="Start one explicit cognitive step.",
                salience=1.0,
                observed_sequence=4,
                production_activation=False,
            )
        )
        task = asyncio.create_task(
            concurrent_bridge.step(
                current_state=state,
                current_world=world,
                current_workspace=workspace,
                personality_snapshot=personality,
                profile=profile,
            )
        )
        await blocking_engine.entered.wait()
        submit_rejected = False
        try:
            concurrent_bridge.submit(
                CognitionEvent(
                    schema="kaliv-consciousness-core/cognition-event/v1",
                    event_id="cevt-" + "5" * 32,
                    kind="world_change",
                    source_ref="event:during-step",
                    summary="Must not race the in-flight cognitive transition.",
                    salience=0.6,
                    observed_sequence=5,
                    production_activation=False,
                )
            )
        except Exception:
            submit_rejected = True

        second_step_rejected = False
        try:
            await concurrent_bridge.step(
                current_state=state,
                current_world=world,
                current_workspace=workspace,
                personality_snapshot=personality,
                profile=profile,
            )
        except Exception:
            second_step_rejected = True

        blocking_engine.release.set()
        result = await task
        return submit_rejected, second_step_rejected, result, blocking_engine.calls

    submit_rejected, second_rejected, concurrent_result, concurrent_calls = run(
        exercise_single_flight()
    )
    check(
        submit_rejected,
        "submit during in-flight cognition fails closed instead of losing an event",
    )
    check(second_rejected, "a second concurrent step is rejected")
    check(
        concurrent_result.thought_engine_invoked and concurrent_calls == 1,
        "single-flight path still completes exactly one model call",
    )

    bridge.close()
    check(bridge.closed, "bridge close marks in-process seam closed")
    try:
        bridge.submit(
            CognitionEvent(
                schema="kaliv-consciousness-core/cognition-event/v1",
                event_id="cevt-" + "2" * 32,
                kind="world_change",
                source_ref="event:after-close",
                summary="This event must be rejected after close.",
                salience=0.5,
                observed_sequence=2,
                production_activation=False,
            )
        )
        closed_rejected = False
    except Exception:
        closed_rejected = True
    check(closed_rejected, "closed bridge rejects further event admission")

    # --- lifecycle composition: attach only while active; preserve owner -------
    @asynccontextmanager
    async def inner(app):
        app.state.inner_active = True
        try:
            yield
        finally:
            app.state.inner_active = False

    def scheduler_owner():
        pass

    inner.__wrapped__ = scheduler_owner

    class FakeBridge:
        # Deliberately wrong type for the type-check test below.
        pass

    app = SimpleNamespace(state=SimpleNamespace())
    inactive = compose_supervisor_lifecycle_lifespan(
        inner,
        bridge_factory=lambda _app: None,
    )

    async def exercise_inactive():
        async with inactive(app):
            check(
                not hasattr(app.state, "consciousness_supervisor"),
                "inactive lifecycle exposes no supervisor bridge on app.state",
            )

    run(exercise_inactive())
    check(
        getattr(inactive, "__wrapped__", None) is scheduler_owner,
        "C18-B wrapper preserves the existing scheduler authority owner",
    )

    lifecycle_engine = Engine()
    lifecycle_bridge = ProductionSupervisorBridge(
        runtime=ConsciousnessCoreRuntime(lifecycle_engine),
        clock=clock_factory(),
    )
    active_lifespan = compose_supervisor_lifecycle_lifespan(
        inner,
        bridge_factory=lambda _app: lifecycle_bridge,
    )

    async def exercise_active():
        async with active_lifespan(app):
            check(
                app.state.consciousness_supervisor is lifecycle_bridge,
                "enabled lifecycle exposes exactly the in-process bridge",
            )
            check(
                lifecycle_engine.calls == 0,
                "lifespan startup itself invokes no ThoughtEngine call",
            )
        check(
            not hasattr(app.state, "consciousness_supervisor"),
            "lifespan shutdown removes the app.state supervisor seam",
        )
        check(lifecycle_bridge.closed, "lifespan shutdown closes the bridge")

    run(exercise_active())

    # Wrong factory result fails closed rather than mounting arbitrary object.
    wrong = compose_supervisor_lifecycle_lifespan(
        inner,
        bridge_factory=lambda _app: FakeBridge(),
    )

    async def exercise_wrong():
        try:
            async with wrong(app):
                pass
            return False
        except TypeError:
            return True

    check(run(exercise_wrong()), "invalid lifecycle bridge factory fails closed")

    # Real production composition remains rooted in scheduler ownership.
    os.environ.pop(SUPERVISOR_LIFECYCLE_FLAG, None)
    os.environ.pop("KALIV_CONSCIOUSNESS_CORE_ENABLED", None)
    from app import entrypoint  # noqa: E402
    from app.schedule_runtime import scheduler_lifespan  # noqa: E402

    production_lifespan = entrypoint.fastapi_app.router.lifespan_context
    check(
        getattr(production_lifespan, "__wrapped__", None) is scheduler_lifespan,
        "C18-B production wrapper preserves scheduler as lifespan authority owner",
    )

finally:
    for key, value in old_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

print(f"\n===== CONSCIOUSNESS C18-B: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
