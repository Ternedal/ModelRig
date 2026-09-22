#!/usr/bin/env python3
"""C18-A event-driven cognition supervisor kernel tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_supervisor.py
"""
from __future__ import annotations

import asyncio
import copy
import json
import sys
import unittest
from pathlib import Path

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
    CognitionSupervisorKernel,
    SupervisorContractError,
    SupervisorPolicy,
    bootstrap_supervisor,
    plan_supervisor_step,
    queue_cognition_event,
)


FIXTURES = json.loads(
    (ROOT / "contracts" / "consciousness-core" / "fixtures-v1.json").read_text(
        encoding="utf-8"
    )
)


def run(coro):
    return asyncio.run(coro)


class SupervisorEngine:
    def __init__(self) -> None:
        self.calls = 0

    async def think(self, request, cognitive_profile, *, context=None):
        self.calls += 1
        payload = copy.deepcopy(FIXTURES["thought_proposal"])
        payload["request_id"] = request.request_id
        payload["proposal_id"] = "thinkprop-" + "5" * 32
        payload["interpretation"] = (
            "Process the bounded event set and preserve continuity."
        )
        payload["attention_suggestions"] = []
        payload["uncertainty"] = 0.18
        return payload


class SupervisorTests(unittest.TestCase):
    def clock(
        self,
        *,
        marker: str,
        monotonic_ms: int,
        sequence: int,
        epoch: str = "1",
    ) -> ClockSample:
        return ClockSample(
            schema="kaliv-consciousness-core/clock-sample/v1",
            sample_id="clock-" + marker * 32,
            wall_time_unix_ms=10_000_000 + monotonic_ms,
            timezone_name="Europe/Copenhagen",
            utc_offset_minutes=120,
            local_hour=13,
            monotonic_ms=monotonic_ms,
            runtime_epoch_id="epoch-" + epoch * 32,
            sampled_sequence=sequence,
            source_ref=f"runtime-clock:{marker}",
            confidence=1.0,
            production_activation=False,
        )

    def event(
        self,
        marker: str,
        *,
        salience: float,
        sequence: int,
        kind: str = "world_change",
    ) -> CognitionEvent:
        return CognitionEvent(
            schema="kaliv-consciousness-core/cognition-event/v1",
            event_id="cevt-" + marker * 32,
            kind=kind,
            source_ref=f"event-source:{marker}",
            summary=f"Bounded event {marker} requires cognitive attention.",
            salience=salience,
            observed_sequence=sequence,
            production_activation=False,
        )

    def policy(
        self,
        *,
        min_interval: int = 500,
        max_events: int = 2,
    ) -> SupervisorPolicy:
        return SupervisorPolicy(
            schema="kaliv-consciousness-core/supervisor-policy/v1",
            min_cycle_interval_ms=min_interval,
            max_events_per_cycle=max_events,
            production_activation=False,
        )

    def world(self) -> RuntimeWorldState:
        return RuntimeWorldState(
            schema="kaliv-consciousness-core/world-state/v1",
            world_id="world-" + "c" * 32,
            revision=10,
            observations=[
                WorldObservation(
                    observation_id="obs-" + "d" * 32,
                    subject_ref="project:modelrig",
                    proposition="C18-A is isolated from production scheduling.",
                    confidence=1.0,
                    epistemic_status="observed",
                    source_refs=["github:issue:1651"],
                )
            ],
            production_activation=False,
        )

    def workspace(self):
        return build_workspace(
            cycle_id="cycle-" + "e" * 32,
            max_active=8,
            candidates=[
                WorkspaceCandidate(
                    candidate_id="wc-" + "1" * 32,
                    kind="memory",
                    salience=0.7,
                    summary="Identity persists while cognition is replaceable.",
                    source_ref="memory4:continuity-invariant",
                )
            ],
        )

    def personality(self) -> PersonalitySnapshot:
        return PersonalitySnapshot(
            person_revision="person-r0007",
            personality_revision="personality-r0005",
            personality_state_ref="personality-state:pstate-" + "7" * 32,
            source_refs=["person-profile:person-r0007"],
        )

    def profile(self) -> CognitiveProfile:
        return CognitiveProfile(
            schema="kaliv-consciousness-core/cognitive-profile/v1",
            profile_id="cog-" + "f" * 32,
            engine_instance_id="engine:test:supervisor",
            provider="mock",
            model="replaceable-supervisor-cognition",
            reasoning_depth=0.75,
            planning_capacity=0.75,
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

    def self_state(self, world, workspace, personality) -> PersistentSelfState:
        return PersistentSelfState(
            schema="kaliv-consciousness-core/self-state/v1",
            self_id="self-" + "a" * 32,
            revision=30,
            person_id="person-" + "b" * 32,
            person_revision=personality.person_revision,
            personality_state_ref=personality.personality_state_ref,
            world_state_ref=world_state_ref(world),
            workspace_ref=workspace_ref(workspace),
            active_goal_refs=["goal:consciousness-core"],
            active_intention_refs=["intent:continue-core"],
            affect=SelfAffect(
                labels=["focused"],
                valence=0.15,
                arousal=0.4,
                confidence=0.9,
                source_refs=["self-state:supervisor"],
            ),
            known_uncertainties=[],
            last_experience_ref="memory4:experience:last",
            production_activation=False,
        )

    def context(self):
        world = self.world()
        workspace = self.workspace()
        personality = self.personality()
        state = self.self_state(world, workspace, personality)
        return state, world, workspace, personality

    def supervisor(self):
        return bootstrap_supervisor(
            supervisor_id="csup-" + "9" * 32,
            clock_sample=self.clock(marker="1", monotonic_ms=1000, sequence=1),
        )

    def test_idle_plan_authorizes_no_model_call(self) -> None:
        plan = plan_supervisor_step(
            state=self.supervisor(),
            clock_sample=self.clock(marker="2", monotonic_ms=1200, sequence=2),
            policy=self.policy(),
        )
        self.assertEqual(plan.decision, "IDLE")
        self.assertEqual(plan.selected_event_ids, [])
        self.assertEqual(plan.thought_engine_calls_authorized, 0)
        self.assertFalse(plan.scheduling_authority)

    def test_event_admission_is_idempotent_and_conflicts_fail_closed(self) -> None:
        sup = self.supervisor()
        event = self.event("a", salience=0.8, sequence=1)
        queued = queue_cognition_event(sup, event)
        repeated = queue_cognition_event(queued, event)
        self.assertEqual(repeated, queued)

        conflict = event.model_copy(update={"summary": "Conflicting content."})
        with self.assertRaises(SupervisorContractError):
            queue_cognition_event(queued, conflict)

    def test_run_plan_orders_events_deterministically(self) -> None:
        sup = self.supervisor()
        sup = queue_cognition_event(
            sup,
            self.event("a", salience=0.7, sequence=2),
        )
        sup = queue_cognition_event(
            sup,
            self.event("b", salience=0.95, sequence=3),
        )
        sup = queue_cognition_event(
            sup,
            self.event("c", salience=0.7, sequence=1),
        )
        plan = plan_supervisor_step(
            state=sup,
            clock_sample=self.clock(marker="2", monotonic_ms=1600, sequence=2),
            policy=self.policy(max_events=2),
        )
        self.assertEqual(plan.decision, "RUN")
        self.assertEqual(
            plan.selected_event_ids,
            ["cevt-" + "b" * 32, "cevt-" + "c" * 32],
        )
        self.assertEqual(plan.thought_engine_calls_authorized, 1)

    def test_run_once_calls_engine_once_and_consumes_only_selected_events(self) -> None:
        state, world, workspace, personality = self.context()
        sup = self.supervisor()
        sup = queue_cognition_event(
            sup,
            self.event("a", salience=0.95, sequence=1, kind="user_turn"),
        )
        sup = queue_cognition_event(
            sup,
            self.event("b", salience=0.85, sequence=2),
        )
        sup = queue_cognition_event(
            sup,
            self.event("c", salience=0.4, sequence=3),
        )
        clock = self.clock(marker="2", monotonic_ms=1800, sequence=2)
        policy = self.policy(max_events=2)
        plan = plan_supervisor_step(
            state=sup,
            clock_sample=clock,
            policy=policy,
        )
        engine = SupervisorEngine()
        result = run(
            CognitionSupervisorKernel(
                ConsciousnessCoreRuntime(engine)
            ).run_once(
                supervisor_state=sup,
                plan=plan,
                clock_sample=clock,
                policy=policy,
                current_state=state,
                current_world=world,
                current_workspace=workspace,
                personality_snapshot=personality,
                profile=self.profile(),
            )
        )

        self.assertEqual(engine.calls, 1)
        self.assertEqual(result.receipt.thought_engine_calls, 1)
        self.assertEqual(
            result.oriented_self_state.revision,
            state.revision + 1,
        )
        self.assertEqual(
            result.reduction.next_self_state.revision,
            state.revision + 2,
        )
        self.assertEqual(
            [item.event_id for item in result.next_supervisor_state.pending_events],
            ["cevt-" + "c" * 32],
        )
        self.assertEqual(
            result.next_supervisor_state.revision,
            sup.revision + 1,
        )
        self.assertEqual(
            result.reduction.next_self_state.self_id,
            state.self_id,
        )
        self.assertFalse(result.receipt.internal_thread_created)
        self.assertFalse(result.receipt.internal_timer_created)
        self.assertFalse(result.receipt.automatic_repeat)
        self.assertFalse(result.receipt.execution_authority)
        self.assertFalse(result.receipt.scheduling_authority)
        self.assertFalse(result.receipt.durable_memory_write_authority)

    def test_pacing_returns_wait_after_recent_cycle(self) -> None:
        state, world, workspace, personality = self.context()
        sup = self.supervisor()
        sup = queue_cognition_event(
            sup,
            self.event("a", salience=0.9, sequence=1),
        )
        first_clock = self.clock(marker="2", monotonic_ms=2000, sequence=2)
        policy = self.policy(min_interval=500, max_events=1)
        first_plan = plan_supervisor_step(
            state=sup,
            clock_sample=first_clock,
            policy=policy,
        )
        engine = SupervisorEngine()
        first = run(
            CognitionSupervisorKernel(
                ConsciousnessCoreRuntime(engine)
            ).run_once(
                supervisor_state=sup,
                plan=first_plan,
                clock_sample=first_clock,
                policy=policy,
                current_state=state,
                current_world=world,
                current_workspace=workspace,
                personality_snapshot=personality,
                profile=self.profile(),
            )
        )
        next_sup = queue_cognition_event(
            first.next_supervisor_state,
            self.event("b", salience=0.9, sequence=2),
        )
        wait = plan_supervisor_step(
            state=next_sup,
            clock_sample=self.clock(
                marker="3",
                monotonic_ms=2200,
                sequence=3,
            ),
            policy=policy,
        )
        self.assertEqual(wait.decision, "WAIT")
        self.assertEqual(wait.wait_remaining_ms, 300)
        self.assertEqual(wait.thought_engine_calls_authorized, 0)

    def test_pre_first_cycle_clock_cannot_predate_bootstrap(self) -> None:
        sup = self.supervisor()
        sup = queue_cognition_event(
            sup,
            self.event("a", salience=0.9, sequence=1),
        )
        with self.assertRaises(SupervisorContractError):
            plan_supervisor_step(
                state=sup,
                clock_sample=self.clock(
                    marker="0",
                    monotonic_ms=900,
                    sequence=1,
                ),
                policy=self.policy(),
            )

    def test_stale_clock_and_epoch_change_fail_closed(self) -> None:
        state, world, workspace, personality = self.context()
        sup = self.supervisor()
        sup = queue_cognition_event(
            sup,
            self.event("a", salience=0.9, sequence=1),
        )
        clock = self.clock(marker="2", monotonic_ms=2000, sequence=2)
        policy = self.policy(max_events=1)
        plan = plan_supervisor_step(
            state=sup,
            clock_sample=clock,
            policy=policy,
        )
        result = run(
            CognitionSupervisorKernel(
                ConsciousnessCoreRuntime(SupervisorEngine())
            ).run_once(
                supervisor_state=sup,
                plan=plan,
                clock_sample=clock,
                policy=policy,
                current_state=state,
                current_world=world,
                current_workspace=workspace,
                personality_snapshot=personality,
                profile=self.profile(),
            )
        )
        again = queue_cognition_event(
            result.next_supervisor_state,
            self.event("b", salience=0.9, sequence=2),
        )
        with self.assertRaises(SupervisorContractError):
            plan_supervisor_step(
                state=again,
                clock_sample=clock,
                policy=policy,
            )
        with self.assertRaises(SupervisorContractError):
            plan_supervisor_step(
                state=again,
                clock_sample=self.clock(
                    marker="4",
                    monotonic_ms=3000,
                    sequence=4,
                    epoch="2",
                ),
                policy=policy,
            )

    def test_wait_or_idle_plan_cannot_be_run(self) -> None:
        state, world, workspace, personality = self.context()
        sup = self.supervisor()
        clock = self.clock(marker="2", monotonic_ms=1500, sequence=2)
        policy = self.policy()
        idle = plan_supervisor_step(
            state=sup,
            clock_sample=clock,
            policy=policy,
        )
        engine = SupervisorEngine()
        with self.assertRaises(SupervisorContractError):
            run(
                CognitionSupervisorKernel(
                    ConsciousnessCoreRuntime(engine)
                ).run_once(
                    supervisor_state=sup,
                    plan=idle,
                    clock_sample=clock,
                    policy=policy,
                    current_state=state,
                    current_world=world,
                    current_workspace=workspace,
                    personality_snapshot=personality,
                    profile=self.profile(),
                )
            )
        self.assertEqual(engine.calls, 0)


if __name__ == "__main__":
    unittest.main()
