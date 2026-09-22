#!/usr/bin/env python3
"""M1-A live ThoughtEngine model-swap continuity proof.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_live_model_swap.py
"""
from __future__ import annotations

import asyncio
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    ActivePersonBindingSnapshot,
    ConsciousnessCoreRuntime,
    OllamaThoughtEngine,
    PersistentSelfState,
    ProductionCognitiveSession,
    SelfAffect,
    bootstrap_runtime_session,
)
from app.consciousness_core.cycle import cognitive_profile_ref  # noqa: E402
from app.consciousness_core.profile_source import load_cognitive_profile  # noqa: E402
from app.consciousness_core.production_lifecycle import TrustedRuntimeClock  # noqa: E402
from app.consciousness_core.supervisor import CognitionEvent, SupervisorPolicy  # noqa: E402
from app.consciousness_core.supervisor_lifecycle import ProductionSupervisorBridge  # noqa: E402


FIXTURES = json.loads(
    (ROOT / "contracts" / "consciousness-core" / "fixtures-v1.json").read_text(
        encoding="utf-8"
    )
)


def run(coro):
    return asyncio.run(coro)


def deterministic_clock():
    wall = [1_700_000_000_000_000_000]
    mono = [10_000_000_000]

    def next_wall():
        value = wall[0]
        wall[0] += 1_000_000_000
        return value

    def next_mono():
        value = mono[0]
        mono[0] += 1_000_000_000
        return value

    return TrustedRuntimeClock(
        wall_time_ns=next_wall,
        monotonic_ns=next_mono,
    )


class ProfileAwareOllamaChat:
    """Test double at the real OllamaThoughtEngine ChatFn boundary."""

    def __init__(self) -> None:
        self.models: list[str | None] = []
        self.request_ids: list[str] = []

    async def __call__(self, messages, model):
        self.models.append(model)
        payload = json.loads(messages[-1]["content"])
        request_id = payload["thought_request"]["request_id"]
        self.request_ids.append(request_id)

        proposal = copy.deepcopy(FIXTURES["thought_proposal"])
        proposal["request_id"] = request_id
        proposal["attention_suggestions"] = []
        proposal["hypotheses"] = []
        proposal["candidate_intentions"] = []
        proposal["predicted_outcomes"] = []
        proposal["questions"] = []
        proposal["memory_queries"] = []
        proposal["body_intent"] = None

        if model == "model-a:small":
            proposal["proposal_id"] = "thinkprop-" + "1" * 32
            proposal["interpretation"] = "MODEL-A-SHALLOW-INTERPRETATION"
            proposal["response_intent"] = "Svar enkelt og kort."
            proposal["uncertainty"] = 0.42
        elif model == "model-b:strong":
            proposal["proposal_id"] = "thinkprop-" + "2" * 32
            proposal["interpretation"] = "MODEL-B-DEEP-INTEGRATED-INTERPRETATION"
            proposal["response_intent"] = "Svar præcist, integreret og med tydelig kontekst."
            proposal["uncertainty"] = 0.08
        else:
            raise AssertionError(f"unexpected model selected by adapter: {model!r}")

        return json.dumps(proposal, ensure_ascii=False, sort_keys=True)


class LiveModelSwapContinuityProof(unittest.TestCase):
    def write_profile(
        self,
        path: Path,
        *,
        model: str,
        reasoning_depth: float,
        planning_capacity: float,
        context_capacity_tokens: int,
        uncertainty_calibration: float,
        calibration_ref: str,
    ) -> None:
        path.write_text(
            json.dumps(
                {
                    "schema": "kaliv-consciousness-core/cognitive-profile-config/v1",
                    "provider": "ollama",
                    "model": model,
                    "reasoning_depth": reasoning_depth,
                    "planning_capacity": planning_capacity,
                    "context_capacity_tokens": context_capacity_tokens,
                    "multimodal_capacity": 0.0,
                    "tool_reasoning": 0.0,
                    "uncertainty_calibration": uncertainty_calibration,
                    "calibration_refs": [calibration_ref],
                }
            ),
            encoding="utf-8",
        )

    def bootstrap_session(self, chat_fn: ProfileAwareOllamaChat):
        persistent = PersistentSelfState(
            schema="kaliv-consciousness-core/self-state/v1",
            self_id="self-" + "a" * 32,
            revision=300,
            person_id="person-" + "b" * 32,
            person_revision="person-r0042",
            personality_state_ref="personality-state:stable-c25",
            world_state_ref="world-state:pre-bootstrap",
            workspace_ref="workspace:pre-bootstrap",
            active_goal_refs=[
                "goal:continuity-proof",
                "goal:remain-same-self",
            ],
            active_intention_refs=["intent:continue-consciousness-core"],
            affect=SelfAffect(
                labels=["focused", "curious"],
                valence=0.2,
                arousal=0.35,
                confidence=0.95,
                source_refs=["affect:c25-proof"],
            ),
            known_uncertainties=[],
            last_experience_ref="memory4:experience:stable-history",
            production_activation=False,
        )
        person = ActivePersonBindingSnapshot(
            schema="kaliv-consciousness-core/active-person-binding/v1",
            person_id=persistent.person_id,
            person_revision=persistent.person_revision,
            body_revision="body-r0007",
            voice_revision="voice-r0009",
            personality_revision="personality-r0011",
            body_source_ref="bodyrig:active:c25",
            voice_source_ref="voicerig:active:c25",
            registry_source_ref="person-registry:active:c25",
            production_activation=False,
        )
        context = bootstrap_runtime_session(
            persistent_state=persistent,
            active_person=person,
            bootstrap_source_ref="runtime:c25:model-swap-proof",
        )

        runtime = ConsciousnessCoreRuntime(OllamaThoughtEngine(chat_fn))
        bridge = ProductionSupervisorBridge(
            runtime=runtime,
            clock=deterministic_clock(),
            policy=SupervisorPolicy(
                schema="kaliv-consciousness-core/supervisor-policy/v1",
                min_cycle_interval_ms=0,
                max_events_per_cycle=1,
                production_activation=False,
            ),
        )
        session = ProductionCognitiveSession(
            supervisor_bridge=bridge,
            bootstrap_context=context,
        )
        return session

    def event(self, marker: str, sequence: int) -> CognitionEvent:
        return CognitionEvent(
            schema="kaliv-consciousness-core/cognition-event/v1",
            event_id="cevt-" + marker * 32,
            kind="user_turn",
            source_ref=f"user-turn:c25:{marker}",
            summary=f"M1 model-swap proof turn {marker}",
            salience=1.0,
            observed_sequence=sequence,
            production_activation=False,
        )

    def continuity_projection(self, session: ProductionCognitiveSession) -> dict:
        live = session.live_state
        state = live.state
        return {
            "session_object_id": id(session),
            "self_id": state.self_id,
            "person_id": state.person_id,
            "person_revision": state.person_revision,
            "personality_state_ref": state.personality_state_ref,
            "personality_snapshot": live.personality_snapshot.model_dump(mode="json"),
            "last_experience_ref": state.last_experience_ref,
            "active_goal_refs": list(state.active_goal_refs),
            "active_intention_refs": list(state.active_intention_refs),
            "bootstrap_receipt_ref": live.bootstrap_receipt_ref,
            "supervisor_id": session.supervisor_state.supervisor_id,
            "runtime_epoch_id": session.supervisor_state.runtime_epoch_id,
        }

    def test_live_model_swap_changes_cognition_without_replacing_self(self):
        chat = ProfileAwareOllamaChat()
        session = self.bootstrap_session(chat)
        baseline = self.continuity_projection(session)

        with tempfile.TemporaryDirectory() as td:
            profile_path = Path(td) / "kaliv-consciousness-profile.json"

            # Model A: lower declared capability.
            self.write_profile(
                profile_path,
                model="model-a:small",
                reasoning_depth=0.25,
                planning_capacity=0.30,
                context_capacity_tokens=4096,
                uncertainty_calibration=0.45,
                calibration_ref="calibration:c25:model-a",
            )
            loaded_a = load_cognitive_profile(path=profile_path)
            self.assertIsNotNone(loaded_a)
            profile_a = loaded_a.profile
            event_a = self.event("1", 1)
            session.submit(event_a)
            step_a = run(
                session.step(
                    profile=profile_a,
                    required_event_id=event_a.event_id,
                )
            )
            after_a = self.continuity_projection(session)

            self.assertEqual(step_a.supervisor_step.plan.decision, "RUN")
            self.assertTrue(step_a.context_updated)
            self.assertEqual(step_a.supervisor_step.plan.selected_event_ids, [event_a.event_id])
            self.assertTrue(step_a.supervisor_step.thought_engine_invoked)
            self.assertFalse(step_a.self_state_store_write_applied)
            self.assertFalse(step_a.durable_memory_write_authority)
            self.assertFalse(step_a.execution_authority)
            self.assertFalse(step_a.scheduling_authority)

            cycle_a = step_a.supervisor_step.cycle_result
            self.assertIsNotNone(cycle_a)
            proposal_a = cycle_a.cognitive_cycle.proposal
            self.assertFalse(cycle_a.receipt.raw_chain_of_thought_persisted)
            self.assertEqual(
                cycle_a.cognitive_cycle.request.cognitive_profile_ref,
                cognitive_profile_ref(profile_a),
            )

            # Same local profile path, now pointing at model B. No session,
            # SelfState, Person or Personality re-bootstrap is allowed.
            self.write_profile(
                profile_path,
                model="model-b:strong",
                reasoning_depth=0.95,
                planning_capacity=0.95,
                context_capacity_tokens=32768,
                uncertainty_calibration=0.90,
                calibration_ref="calibration:c25:model-b",
            )
            loaded_b = load_cognitive_profile(path=profile_path)
            self.assertIsNotNone(loaded_b)
            profile_b = loaded_b.profile

            self.assertNotEqual(profile_a.profile_id, profile_b.profile_id)
            self.assertNotEqual(
                cognitive_profile_ref(profile_a),
                cognitive_profile_ref(profile_b),
            )
            self.assertNotEqual(loaded_a.receipt.config_sha256, loaded_b.receipt.config_sha256)
            for profile in (profile_a, profile_b):
                self.assertTrue(profile.ephemeral)
                self.assertFalse(profile.identity_authority)
                self.assertFalse(profile.persistent_state_authority)
                self.assertFalse(profile.action_authority)
                self.assertFalse(profile.production_activation)

            event_b = self.event("2", 2)
            session.submit(event_b)
            step_b = run(
                session.step(
                    profile=profile_b,
                    required_event_id=event_b.event_id,
                )
            )
            after_b = self.continuity_projection(session)

            self.assertEqual(step_b.supervisor_step.plan.decision, "RUN")
            self.assertTrue(step_b.context_updated)
            self.assertEqual(step_b.supervisor_step.plan.selected_event_ids, [event_b.event_id])
            self.assertTrue(step_b.supervisor_step.thought_engine_invoked)
            self.assertFalse(step_b.self_state_store_write_applied)
            self.assertFalse(step_b.durable_memory_write_authority)
            self.assertFalse(step_b.execution_authority)
            self.assertFalse(step_b.scheduling_authority)

            cycle_b = step_b.supervisor_step.cycle_result
            self.assertIsNotNone(cycle_b)
            proposal_b = cycle_b.cognitive_cycle.proposal
            self.assertFalse(cycle_b.receipt.raw_chain_of_thought_persisted)
            self.assertEqual(
                cycle_b.cognitive_cycle.request.cognitive_profile_ref,
                cognitive_profile_ref(profile_b),
            )

        # The real adapter boundary selected a different model on each call.
        self.assertEqual(chat.models, ["model-a:small", "model-b:strong"])
        self.assertEqual(len(chat.request_ids), 2)
        self.assertNotEqual(chat.request_ids[0], chat.request_ids[1])

        # Cognition/capability changed in bounded, validated output.
        self.assertNotEqual(proposal_a.proposal_id, proposal_b.proposal_id)
        self.assertNotEqual(proposal_a.interpretation, proposal_b.interpretation)
        self.assertNotEqual(proposal_a.response_intent, proposal_b.response_intent)
        self.assertGreater(proposal_a.uncertainty, proposal_b.uncertainty)
        self.assertLess(profile_a.reasoning_depth, profile_b.reasoning_depth)
        self.assertLess(profile_a.planning_capacity, profile_b.planning_capacity)
        self.assertLess(
            profile_a.context_capacity_tokens,
            profile_b.context_capacity_tokens,
        )

        # Identity/continuity did not change. State revision/workspace are
        # intentionally excluded: cognitive transitions are allowed to advance.
        self.assertEqual(baseline, after_a)
        self.assertEqual(baseline, after_b)
        self.assertIs(session, session)
        self.assertEqual(session.live_state.completed_cycles, 2)

        # The one-shot outward mailbox may change with cognition, but it stays
        # bound to the second exact user-turn and contains only response_intent.
        guidance = session.pending_response_guidance
        self.assertIsNotNone(guidance)
        self.assertEqual(guidance.user_turn_event_id, event_b.event_id)
        self.assertEqual(guidance.text, proposal_b.response_intent)
        self.assertTrue(guidance.contains_only_response_intent)
        self.assertFalse(guidance.raw_chain_of_thought_included)
        self.assertNotIn(proposal_b.interpretation, guidance.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
