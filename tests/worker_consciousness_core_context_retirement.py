#!/usr/bin/env python3
"""C29-M post-recovery wake-artifact model-context retirement tests."""
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
    ActivePersonBindingSnapshot,
    ClockSample,
    CognitiveProfile,
    CognitionEvent,
    ConsciousnessCoreRuntime,
    ContinuityContextRetirementError,
    ProductionCognitiveSession,
    SelfAffect,
    SelfBootstrapAuthority,
    TrustedRuntimeClock,
    anchor_from_clock,
    bootstrap_runtime_session,
    bootstrap_self_state,
    build_runtime_liveness_witness,
    retire_wake_artifacts_from_model_context,
    wake_from_unplanned_restart,
)
from app.consciousness_core.supervisor_lifecycle import (  # noqa: E402
    ProductionSupervisorBridge,
)

FIXTURES = json.loads(
    (ROOT / "contracts" / "consciousness-core" / "fixtures-v1.json").read_text(
        encoding="utf-8"
    )
)

SELF = "self-" + "a" * 32
PERSON = "person-" + "b" * 32
PERSON_REV = "person-r0007"
EPOCH_A = "epoch-" + "1" * 32
EPOCH_B = "epoch-" + "2" * 32


def run(coro):
    return asyncio.run(coro)


def sample(marker, wall, mono, seq, epoch):
    return ClockSample(
        schema="kaliv-consciousness-core/clock-sample/v1",
        sample_id="clock-" + marker * 32,
        wall_time_unix_ms=wall,
        timezone_name="Europe/Copenhagen",
        utc_offset_minutes=120,
        local_hour=10,
        monotonic_ms=mono,
        runtime_epoch_id=epoch,
        sampled_sequence=seq,
        source_ref="trusted:c29m:" + marker,
        confidence=1.0,
        production_activation=False,
    )


def anchor(marker, wall, mono, seq, epoch):
    return anchor_from_clock(
        sample(marker, wall, mono, seq, epoch),
        event_ref="c29m:" + marker,
    )


def deterministic_clock():
    wall = iter(
        1_700_000_000_000_000_000 + i * 1_000_000_000
        for i in range(1, 128)
    )
    mono = iter(i * 1_000_000_000 for i in range(1, 128))
    return TrustedRuntimeClock(
        wall_time_ns=lambda: next(wall),
        monotonic_ns=lambda: next(mono),
    )


class CaptureEngine:
    def __init__(self):
        self.calls = 0
        self.contexts = []

    async def think(self, request, cognitive_profile, *, context=None):
        self.calls += 1
        self.contexts.append(copy.deepcopy(context))
        payload = copy.deepcopy(FIXTURES["thought_proposal"])
        payload["request_id"] = request.request_id
        payload["proposal_id"] = (
            "thinkprop-" + f"{self.calls:x}"[-1] * 32
        )
        payload["interpretation"] = "C29-M context retirement."
        payload["attention_suggestions"] = []
        payload["uncertainty"] = 0.1
        return payload


class ContextRetirementTests(unittest.TestCase):
    def durable(self):
        authority = SelfBootstrapAuthority(
            schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
            self_id=SELF,
            person_id=PERSON,
            person_revision=PERSON_REV,
            authority="operator_review",
            authority_ref="operator:test:c29m",
            source_refs=["registry:test:c29m"],
            production_activation=False,
        )
        return bootstrap_self_state(
            authority,
            personality_state_ref="personality-state:c29m",
            world_state_ref="world-state:c29m",
            workspace_ref="workspace:c29m",
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["affect:c29m"],
            ),
        )

    def person(self, state):
        return ActivePersonBindingSnapshot(
            schema="kaliv-consciousness-core/active-person-binding/v1",
            person_id=state.person_id,
            person_revision=state.person_revision,
            body_revision="body-r0001",
            voice_revision="voice-r0001",
            personality_revision="personality-r0001",
            body_source_ref="body:c29m",
            voice_source_ref="voice:c29m",
            registry_source_ref="registry:c29m",
            production_activation=False,
        )

    def wake(self, state):
        witness = build_runtime_liveness_witness(
            state=state,
            anchor=anchor("1", 111_000, 50_000, 8, EPOCH_A),
            source_ref="self-state-checkpoint-receipt:" + "c" * 64,
        )
        return wake_from_unplanned_restart(
            wake_anchor=anchor("2", 121_000, 200, 1, EPOCH_B),
            self_id=state.self_id,
            person_revision=state.person_revision,
            source_ref="sleep-wake-ack:" + "d" * 64,
            liveness_witness=witness,
        )

    def context(self, state):
        return bootstrap_runtime_session(
            persistent_state=state,
            active_person=self.person(state),
            bootstrap_source_ref="runtime:c29m",
            wake_receipt=self.wake(state),
        )

    def profile(self):
        return CognitiveProfile(
            schema="kaliv-consciousness-core/cognitive-profile/v1",
            profile_id="cog-" + "7" * 32,
            engine_instance_id="engine:test:c29m",
            provider="mock",
            model="c29m-model",
            reasoning_depth=0.8,
            planning_capacity=0.8,
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

    def event(self, marker, sequence):
        return CognitionEvent(
            schema="kaliv-consciousness-core/cognition-event/v1",
            event_id="cevt-" + marker * 32,
            kind="operator_signal",
            source_ref="operator:c29m:" + marker,
            summary="C29-M explicit cognition event.",
            salience=1.0,
            observed_sequence=sequence,
            production_activation=False,
        )

    def session(self, state):
        engine = CaptureEngine()
        session = ProductionCognitiveSession(
            supervisor_bridge=ProductionSupervisorBridge(
                runtime=ConsciousnessCoreRuntime(engine),
                clock=deterministic_clock(),
            ),
            bootstrap_context=self.context(state),
            durable_anchor_state=state,
        )
        return session, engine

    def wake_refs(self, session):
        continuity = session.continuity_state
        return {
            continuity.wake_receipt_ref,
            session.continuity_status.continuity_state_ref,
        }

    def model_has_wake_artifacts(self, payload, refs):
        for obs in payload["world_state"]["observations"]:
            if refs.intersection(obs["source_refs"]):
                return True
        for candidate in payload["workspace"]["candidates"]:
            if candidate["source_ref"] in refs:
                return True
        return False

    def test_retirement_rejects_reorienting_phase(self):
        state = self.durable()
        session, _engine = self.session(state)
        packet = {
            "world_state": {
                "observations": [],
            },
            "workspace": {
                "candidates": [],
                "selected_candidate_ids": [],
            },
        }
        with self.assertRaisesRegex(
            ContinuityContextRetirementError,
            "only after ORIENTED",
        ):
            retire_wake_artifacts_from_model_context(
                packet,
                continuity_state=session.continuity_state,
                orientation=session.continuity_orientation,
            )

    def test_first_run_sees_wake_context_second_run_does_not(self):
        state = self.durable()
        session, engine = self.session(state)
        refs = self.wake_refs(session)

        session.submit(self.event("7", 1))
        first = run(session.step(profile=self.profile()))

        self.assertEqual(first.supervisor_step.plan.decision, "RUN")
        self.assertEqual(engine.calls, 1)
        self.assertIn("continuity", engine.contexts[0])
        self.assertTrue(
            self.model_has_wake_artifacts(engine.contexts[0], refs)
        )
        self.assertEqual(
            session.continuity_status.status,
            "ORIENTED",
        )

        session.submit(self.event("8", 2))
        second = run(session.step(profile=self.profile()))

        self.assertEqual(second.supervisor_step.plan.decision, "RUN")
        self.assertEqual(engine.calls, 2)
        self.assertNotIn("continuity", engine.contexts[1])
        self.assertFalse(
            self.model_has_wake_artifacts(engine.contexts[1], refs)
        )

    def test_authoritative_core_world_keeps_wake_evidence(self):
        state = self.durable()
        session, _engine = self.session(state)
        refs = self.wake_refs(session)

        session.submit(self.event("7", 1))
        run(session.step(profile=self.profile()))
        session.submit(self.event("8", 2))
        run(session.step(profile=self.profile()))

        authoritative_matches = [
            obs
            for obs in session.live_state.world.observations
            if refs.intersection(obs.source_refs)
        ]
        self.assertGreaterEqual(len(authoritative_matches), 1)
        self.assertIsNotNone(session.continuity_state)
        self.assertEqual(
            session.continuity_orientation.phase,
            "ORIENTED",
        )
        self.assertIsNotNone(session.recovery_completion)

    def test_retirement_removes_selected_id_when_candidate_is_removed(self):
        state = self.durable()
        session, engine = self.session(state)
        refs = self.wake_refs(session)

        session.submit(self.event("7", 1))
        run(session.step(profile=self.profile()))
        session.submit(self.event("8", 2))
        run(session.step(profile=self.profile()))

        payload = engine.contexts[1]
        candidate_ids = {
            item["candidate_id"]
            for item in payload["workspace"]["candidates"]
        }
        self.assertTrue(
            set(payload["workspace"]["selected_candidate_ids"])
            .issubset(candidate_ids)
        )
        self.assertFalse(
            any(
                item["source_ref"] in refs
                for item in payload["workspace"]["candidates"]
            )
        )


if __name__ == "__main__":
    unittest.main()
