#!/usr/bin/env python3
"""C19-A authoritative runtime session bootstrap tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_session_bootstrap.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    PersistentSelfState,
    SelfAffect,
    TemporalAnchor,
    prepare_sleep,
    wake_from_sleep,
)
from app.consciousness_core.session_bootstrap import (  # noqa: E402
    SessionBootstrapError,
    active_person_binding_from_registry,
    bootstrap_runtime_session,
)
from app.person_registry import PersonRegistry, REVIEW_CHECKS  # noqa: E402


class SessionBootstrapTests(unittest.TestCase):
    def active_person(self, root: Path):
        registry = PersonRegistry(root / "persons.json")
        person = registry.create_person("Kaliv")
        body = registry.add_body_revision(person.person_id, "body:kaliv:v1")
        voice = registry.add_voice_revision(person.person_id, "voice:kaliv:v1")
        personality = registry.add_personality_revision(
            person.person_id,
            system_instructions="Be Kaliv.",
            default_language="da",
            style_notes="warm, curious",
        )
        revision = registry.propose_person_revision(
            person.person_id,
            body=body.id,
            voice=voice.id,
            personality=personality.id,
            review={key: True for key in REVIEW_CHECKS},
            reviewer="test",
        )
        registry.activate(person.person_id, revision.id)
        registry.select(person.person_id)
        raw = registry.active_bindings()
        self.assertIsNotNone(raw)
        binding = active_person_binding_from_registry(
            raw,
            registry_source_ref="person-registry:test",
        )
        return registry, person, revision, body, voice, personality, binding

    def state(self, person_id: str, person_revision: str) -> PersistentSelfState:
        return PersistentSelfState(
            schema="kaliv-consciousness-core/self-state/v1",
            self_id="self-" + "a" * 32,
            revision=50,
            person_id=person_id,
            person_revision=person_revision,
            personality_state_ref="personality-state:durable:test",
            world_state_ref="world-state:prior-transient-ref",
            workspace_ref="workspace:prior-transient-ref",
            active_goal_refs=[
                "goal:consciousness-core",
                "goal:continue-after-restart",
            ],
            active_intention_refs=["intent:inspect-runtime-state"],
            affect=SelfAffect(
                labels=["focused"],
                valence=0.2,
                arousal=0.35,
                confidence=0.9,
                source_refs=["self-state:pre-restart"],
            ),
            known_uncertainties=[],
            last_experience_ref="memory4:experience:last",
            production_activation=False,
        )

    def anchor(
        self,
        marker: str,
        *,
        epoch: str,
        wall_ms: int,
        monotonic_ms: int,
        sequence: int,
    ) -> TemporalAnchor:
        return TemporalAnchor(
            schema="kaliv-consciousness-core/temporal-anchor/v1",
            anchor_id="tanch-" + marker * 32,
            event_ref=f"test:{marker}",
            wall_time_unix_ms=wall_ms,
            runtime_epoch_id="epoch-" + epoch * 32,
            monotonic_ms=monotonic_ms,
            sequence=sequence,
            source_refs=[f"clock:test:{marker}"],
            confidence=1.0,
            production_activation=False,
        )

    def planned_wake(self, state: PersistentSelfState):
        sleep = prepare_sleep(
            self_id=state.self_id,
            person_revision=state.person_revision,
            entry_anchor=self.anchor(
                "1",
                epoch="1",
                wall_ms=1_000_000,
                monotonic_ms=80_000,
                sequence=10,
            ),
            reason="app_closed",
            open_goal_refs=state.active_goal_refs,
            open_loop_refs=state.active_intention_refs,
        )
        return wake_from_sleep(
            wake_anchor=self.anchor(
                "2",
                epoch="2",
                wall_ms=1_600_000,
                monotonic_ms=2_000,
                sequence=11,
            ),
            sleep_record=sleep,
            expected_self_id=state.self_id,
            expected_person_revision=state.person_revision,
        )

    def unplanned_wake(self, state: PersistentSelfState):
        return wake_from_sleep(
            wake_anchor=self.anchor(
                "4",
                epoch="4",
                wall_ms=2_200_000,
                monotonic_ms=3_000,
                sequence=22,
            ),
            last_known_anchor=self.anchor(
                "3",
                epoch="3",
                wall_ms=2_000_000,
                monotonic_ms=90_000,
                sequence=21,
            ),
            expected_self_id=state.self_id,
            expected_person_revision=state.person_revision,
        )

    def test_registry_projection_uses_exact_active_revision(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            _, person, revision, body, voice, personality, binding = (
                self.active_person(Path(td))
            )
            self.assertEqual(binding.person_id, person.person_id)
            self.assertEqual(binding.person_revision, revision.id)
            self.assertEqual(binding.body_revision, body.id)
            self.assertEqual(binding.voice_revision, voice.id)
            self.assertEqual(binding.personality_revision, personality.id)
            self.assertEqual(binding.body_source_ref, "bodyrig:body:kaliv:v1")
            self.assertEqual(binding.voice_source_ref, "voicerig:voice:kaliv:v1")
            self.assertFalse(binding.production_activation)

    def test_runtime_start_creates_fresh_transient_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            _, person, revision, _, _, personality, binding = self.active_person(
                Path(td)
            )
            state = self.state(person.person_id, revision.id)
            result = bootstrap_runtime_session(
                persistent_state=state,
                active_person=binding,
                bootstrap_source_ref="runtime:startup:test",
            )

            self.assertEqual(result.state.revision, state.revision + 1)
            self.assertEqual(result.state.self_id, state.self_id)
            self.assertEqual(result.state.person_id, state.person_id)
            self.assertEqual(result.state.person_revision, state.person_revision)
            self.assertNotEqual(result.state.world_state_ref, state.world_state_ref)
            self.assertNotEqual(result.state.workspace_ref, state.workspace_ref)
            self.assertEqual(
                result.state.personality_state_ref,
                state.personality_state_ref,
            )
            self.assertEqual(result.state.active_goal_refs, state.active_goal_refs)
            self.assertEqual(
                result.state.active_intention_refs,
                state.active_intention_refs,
            )
            self.assertEqual(result.state.affect, state.affect)
            self.assertEqual(
                result.state.last_experience_ref,
                state.last_experience_ref,
            )

            self.assertEqual(result.receipt.bootstrap_kind, "RUNTIME_START")
            self.assertFalse(result.receipt.prior_world_restored)
            self.assertFalse(result.receipt.prior_workspace_restored)
            self.assertEqual(
                result.receipt.previous_world_state_ref,
                state.world_state_ref,
            )
            self.assertEqual(
                result.receipt.previous_workspace_ref,
                state.workspace_ref,
            )
            self.assertEqual(result.receipt.model_calls, 0)
            self.assertFalse(result.receipt.self_state_store_write_applied)
            self.assertFalse(result.receipt.execution_authority)
            self.assertFalse(result.receipt.scheduling_authority)

            runtime_sources = {
                item.source_ref for item in result.workspace.candidates
            }
            self.assertNotIn(state.world_state_ref, runtime_sources)
            self.assertNotIn(state.workspace_ref, runtime_sources)

            self.assertEqual(
                result.personality_snapshot.person_revision,
                revision.id,
            )
            self.assertEqual(
                result.personality_snapshot.personality_revision,
                personality.id,
            )
            self.assertEqual(
                result.personality_snapshot.personality_state_ref,
                state.personality_state_ref,
            )

    def test_same_exact_inputs_bootstrap_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            _, person, revision, *_rest, binding = self.active_person(Path(td))
            state = self.state(person.person_id, revision.id)
            first = bootstrap_runtime_session(
                persistent_state=state,
                active_person=binding,
                bootstrap_source_ref="runtime:startup:test",
            )
            second = bootstrap_runtime_session(
                persistent_state=state,
                active_person=binding,
                bootstrap_source_ref="runtime:startup:test",
            )
            self.assertEqual(
                first.model_dump(mode="json"),
                second.model_dump(mode="json"),
            )

    def test_planned_wake_is_bounded_observed_context_not_offline_cognition(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            _, person, revision, *_rest, binding = self.active_person(Path(td))
            state = self.state(person.person_id, revision.id)
            wake = self.planned_wake(state)
            result = bootstrap_runtime_session(
                persistent_state=state,
                active_person=binding,
                bootstrap_source_ref="runtime:wake:test",
                wake_receipt=wake,
            )
            self.assertEqual(
                result.receipt.bootstrap_kind,
                "WAKE_REORIENTATION",
            )
            self.assertFalse(result.receipt.cognition_during_gap)
            self.assertIsNotNone(result.receipt.wake_receipt_ref)
            propositions = " ".join(
                item.proposition for item in result.world.observations
            )
            self.assertIn("cognition did not continue", propositions)
            self.assertIn("600000 ms", propositions)

    def test_unplanned_dormancy_is_accepted_when_identity_matches(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            _, person, revision, *_rest, binding = self.active_person(Path(td))
            state = self.state(person.person_id, revision.id)
            wake = self.unplanned_wake(state)
            result = bootstrap_runtime_session(
                persistent_state=state,
                active_person=binding,
                bootstrap_source_ref="runtime:unplanned-wake:test",
                wake_receipt=wake,
            )
            self.assertEqual(wake.dormancy_kind, "UNPLANNED_DORMANCY")
            self.assertFalse(result.receipt.cognition_during_gap)
            self.assertFalse(result.receipt.prior_workspace_restored)

    def test_active_person_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            _, person, revision, *_rest, binding = self.active_person(Path(td))
            state = self.state(person.person_id, revision.id)
            wrong = binding.model_copy(
                update={"person_revision": "person-r9999"}
            )
            with self.assertRaises(SessionBootstrapError):
                bootstrap_runtime_session(
                    persistent_state=state,
                    active_person=wrong,
                    bootstrap_source_ref="runtime:startup:test",
                )

    def test_wake_identity_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            _, person, revision, *_rest, binding = self.active_person(Path(td))
            state = self.state(person.person_id, revision.id)
            wake = self.planned_wake(state).model_copy(
                update={"self_id": "self-" + "9" * 32}
            )
            with self.assertRaises(SessionBootstrapError):
                bootstrap_runtime_session(
                    persistent_state=state,
                    active_person=binding,
                    bootstrap_source_ref="runtime:wake:test",
                    wake_receipt=wake,
                )

    def test_invalid_active_window_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            _, person, revision, *_rest, binding = self.active_person(Path(td))
            state = self.state(person.person_id, revision.id)
            with self.assertRaises(SessionBootstrapError):
                bootstrap_runtime_session(
                    persistent_state=state,
                    active_person=binding,
                    bootstrap_source_ref="runtime:startup:test",
                    max_active=17,
                )


if __name__ == "__main__":
    unittest.main()
