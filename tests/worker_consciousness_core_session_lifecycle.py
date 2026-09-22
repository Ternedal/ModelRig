#!/usr/bin/env python3
"""C19-B production in-memory cognitive session owner tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_session_lifecycle.py
"""
from __future__ import annotations

import asyncio
import copy
import json
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    CognitiveProfile,
    ConsciousnessCoreRuntime,
    SelfAffect,
    SelfBootstrapAuthority,
    SelfStateStore,
    bootstrap_self_state,
)
from app.consciousness_core.production_lifecycle import TrustedRuntimeClock  # noqa: E402
from app.consciousness_core.sleep import WakeReceipt  # noqa: E402
from app.consciousness_core.temporal import TemporalAnchor  # noqa: E402
from app.consciousness_core.wake_followup import (  # noqa: E402
    WAKE_FOLLOWUP_SALIENCE,
    WakeFollowupAdmissionError,
    build_wake_followup_event,
    wake_followup_event_id,
    wake_receipt_ref,
)
from app.consciousness_core.session_lifecycle import (  # noqa: E402
    CognitiveSessionLifecycleError,
    ProductionCognitiveSession,
    compose_cognitive_session_lifespan,
    production_cognitive_session_factory,
)
from app.consciousness_core.supervisor import CognitionEvent  # noqa: E402
from app.consciousness_core.supervisor_lifecycle import (  # noqa: E402
    ProductionSupervisorBridge,
)
from app.person_registry import PersonRegistry, REVIEW_CHECKS  # noqa: E402


FIXTURES = json.loads(
    (ROOT / "contracts" / "consciousness-core" / "fixtures-v1.json").read_text(
        encoding="utf-8"
    )
)


def run(coro):
    return asyncio.run(coro)


class Engine:
    def __init__(self):
        self.calls = 0
        self.models = []

    async def think(self, request, cognitive_profile, *, context=None):
        self.calls += 1
        self.models.append(cognitive_profile.model)
        payload = copy.deepcopy(FIXTURES["thought_proposal"])
        payload["request_id"] = request.request_id
        payload["proposal_id"] = "thinkprop-" + f"{self.calls:x}"[-1] * 32
        payload["interpretation"] = (
            "Advance one bounded live cognitive session cycle."
        )
        payload["attention_suggestions"] = []
        payload["uncertainty"] = 0.15
        return payload


def deterministic_clock():
    wall = iter(
        [
            1_700_000_000_000_000_000,
            1_700_000_001_000_000_000,
            1_700_000_002_000_000_000,
            1_700_000_003_000_000_000,
            1_700_000_004_000_000_000,
            1_700_000_005_000_000_000,
        ]
    )
    mono = iter(
        [
            10_000_000_000,
            11_000_000_000,
            12_000_000_000,
            13_000_000_000,
            14_000_000_000,
            15_000_000_000,
        ]
    )
    return TrustedRuntimeClock(
        wall_time_ns=lambda: next(wall),
        monotonic_ns=lambda: next(mono),
    )


class SessionLifecycleTests(unittest.TestCase):
    def person_fixture(self, root: Path):
        registry_path = root / "persons.json"
        registry = PersonRegistry(registry_path)
        person = registry.create_person("Kaliv")
        body = registry.add_body_revision(person.person_id, "body:kaliv:v1")
        voice = registry.add_voice_revision(person.person_id, "voice:kaliv:v1")
        personality = registry.add_personality_revision(
            person.person_id,
            system_instructions="Be Kaliv.",
            default_language="da",
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
        return registry_path, person, revision

    def durable_state(self, person_id: str, person_revision: str):
        authority = SelfBootstrapAuthority(
            schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
            self_id="self-" + "a" * 32,
            person_id=person_id,
            person_revision=person_revision,
            authority="operator_review",
            authority_ref="test:operator-review",
            source_refs=["person-registry:test"],
            production_activation=False,
        )
        state = bootstrap_self_state(
            authority,
            personality_state_ref="personality-state:durable:test",
            world_state_ref="world-state:prior-transient",
            workspace_ref="workspace:prior-transient",
            active_goal_refs=["goal:consciousness-core"],
            active_intention_refs=["intent:continue-core"],
            affect=SelfAffect(
                labels=["focused"],
                valence=0.1,
                arousal=0.3,
                confidence=0.9,
                source_refs=["test:affect"],
            ),
            last_experience_ref="memory4:experience:last",
        )
        return authority, state

    def wake_receipt(self, state):
        anchor = TemporalAnchor(
            schema="kaliv-consciousness-core/temporal-anchor/v1",
            anchor_id="tanch-" + "c" * 32,
            event_ref="runtime:wake:test",
            wall_time_unix_ms=1_700_000_100_000,
            runtime_epoch_id="epoch-" + "d" * 32,
            monotonic_ms=1_000,
            sequence=7,
            source_refs=["runtime:trusted-system-clock"],
            confidence=1.0,
            production_activation=False,
        )
        return WakeReceipt(
            schema="kaliv-consciousness-core/wake-receipt/v1",
            wake_id="wake-" + "e" * 32,
            self_id=state.self_id,
            person_revision=state.person_revision,
            sleep_id="sleep-" + "f" * 32,
            dormancy_kind="PLANNED_SLEEP",
            entry_anchor_ref="temporal-anchor:tanch-" + "a" * 32,
            wake_anchor=anchor,
            offline_duration_ms=60_000,
            duration_confidence=1.0,
            duration_known=True,
            continuity_preserved=True,
            cognition_during_gap=False,
            wake_state="WAKING",
            resume_goal_refs=list(state.active_goal_refs),
            resume_open_loop_refs=list(state.active_intention_refs),
            pending_review_refs=[],
            execution_authority=False,
            scheduling_authority=False,
            durable_memory_write_authority=False,
            production_activation=False,
        )

    def profile(self, model: str = "model-a") -> CognitiveProfile:
        marker = "1" if model == "model-a" else "2"
        return CognitiveProfile(
            schema="kaliv-consciousness-core/cognitive-profile/v1",
            profile_id="cog-" + marker * 32,
            engine_instance_id=f"engine:test:{model}",
            provider="mock",
            model=model,
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

    def bridge(self, engine: Engine):
        return ProductionSupervisorBridge(
            runtime=ConsciousnessCoreRuntime(engine),
            clock=deterministic_clock(),
        )

    def test_factory_does_not_touch_persistence_without_supervisor_bridge(self):
        touched = {"store": 0}

        def forbidden_store():
            touched["store"] += 1
            raise AssertionError("must not touch SelfState without C18-B bridge")

        app = SimpleNamespace(state=SimpleNamespace())
        result = production_cognitive_session_factory(
            app,
            self_store_factory=forbidden_store,
            registry_path_fn=lambda: "does-not-matter",
        )
        self.assertIsNone(result)
        self.assertEqual(touched["store"], 0)

    def test_factory_builds_live_session_from_real_store_and_registry(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            person_path, person, revision = self.person_fixture(root)
            authority, state = self.durable_state(person.person_id, revision.id)
            store = SelfStateStore(root / "self.json")
            store.bootstrap(state, authority)

            engine = Engine()
            bridge = self.bridge(engine)
            app = SimpleNamespace(
                state=SimpleNamespace(consciousness_supervisor=bridge)
            )
            session = production_cognitive_session_factory(
                app,
                self_store_factory=lambda: store,
                registry_path_fn=lambda: str(person_path),
            )
            self.assertIsInstance(session, ProductionCognitiveSession)
            self.assertEqual(engine.calls, 0)
            self.assertEqual(session.live_state.state.self_id, state.self_id)
            self.assertEqual(
                session.live_state.state.person_revision,
                state.person_revision,
            )
            self.assertEqual(
                session.live_state.state.revision,
                state.revision + 1,
            )
            self.assertNotEqual(
                session.live_state.state.world_state_ref,
                state.world_state_ref,
            )
            self.assertNotEqual(
                session.live_state.state.workspace_ref,
                state.workspace_ref,
            )
            self.assertEqual(session.live_state.completed_cycles, 0)

    def test_wake_followup_projection_is_deterministic_and_identity_bound(self):
        _, state = self.durable_state(
            "person-" + "1" * 32,
            "person-r0007",
        )
        wake = self.wake_receipt(state)
        first = build_wake_followup_event(
            wake,
            expected_self_id=state.self_id,
            expected_person_revision=state.person_revision,
        )
        second = build_wake_followup_event(
            wake.model_dump(mode="json"),
            expected_self_id=state.self_id,
            expected_person_revision=state.person_revision,
        )
        self.assertEqual(first, second)
        self.assertEqual(first.kind, "wake_followup")
        self.assertEqual(first.salience, WAKE_FOLLOWUP_SALIENCE)
        self.assertEqual(first.observed_sequence, wake.wake_anchor.sequence)
        self.assertEqual(first.source_ref, wake_receipt_ref(wake))
        self.assertEqual(first.event_id, wake_followup_event_id(wake))
        self.assertIn("PLANNED_SLEEP", first.summary)
        self.assertIn("60000 ms", first.summary)
        self.assertIn("did not continue", first.summary)
        with self.assertRaises(WakeFollowupAdmissionError):
            build_wake_followup_event(
                wake,
                expected_self_id="self-" + "9" * 32,
                expected_person_revision=state.person_revision,
            )

    def test_wake_receipt_queues_one_deterministic_followup_without_model_call(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            person_path, person, revision = self.person_fixture(root)
            authority, state = self.durable_state(person.person_id, revision.id)
            store = SelfStateStore(root / "self.json")
            store.bootstrap(state, authority)
            wake = self.wake_receipt(state)

            engine = Engine()
            bridge = self.bridge(engine)
            app = SimpleNamespace(
                state=SimpleNamespace(
                    consciousness_supervisor=bridge,
                    consciousness_sleep_wake_receipt=wake,
                )
            )
            session = production_cognitive_session_factory(
                app,
                self_store_factory=lambda: store,
                registry_path_fn=lambda: str(person_path),
            )
            self.assertIsInstance(session, ProductionCognitiveSession)
            self.assertEqual(engine.calls, 0)
            pending = session.supervisor_state.pending_events
            self.assertEqual(len(pending), 1)
            event = pending[0]
            self.assertEqual(event.kind, "wake_followup")
            self.assertEqual(event.event_id, wake_followup_event_id(wake))
            self.assertEqual(event.source_ref, wake_receipt_ref(wake))

            # Exact duplicate admission remains idempotent in C18.
            before_revision = session.supervisor_state.revision
            session.submit(event)
            self.assertEqual(len(session.supervisor_state.pending_events), 1)
            self.assertEqual(
                session.supervisor_state.revision,
                before_revision,
            )

    def test_missing_active_person_yields_no_session(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            person_path, person, revision = self.person_fixture(root)
            # Replace registry with one that has a person but no selected active binding.
            empty_registry_path = root / "empty-persons.json"
            empty_registry = PersonRegistry(empty_registry_path)
            empty_registry.create_person("Other")

            authority, state = self.durable_state(person.person_id, revision.id)
            store = SelfStateStore(root / "self.json")
            store.bootstrap(state, authority)

            app = SimpleNamespace(
                state=SimpleNamespace(
                    consciousness_supervisor=self.bridge(Engine())
                )
            )
            session = production_cognitive_session_factory(
                app,
                self_store_factory=lambda: store,
                registry_path_fn=lambda: str(empty_registry_path),
            )
            self.assertIsNone(session)

    def test_session_idle_step_does_not_change_live_context_or_call_model(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            person_path, person, revision = self.person_fixture(root)
            authority, state = self.durable_state(person.person_id, revision.id)
            store = SelfStateStore(root / "self.json")
            store.bootstrap(state, authority)
            engine = Engine()
            app = SimpleNamespace(
                state=SimpleNamespace(
                    consciousness_supervisor=self.bridge(engine)
                )
            )
            session = production_cognitive_session_factory(
                app,
                self_store_factory=lambda: store,
                registry_path_fn=lambda: str(person_path),
            )
            before = session.live_state
            result = run(session.step(profile=self.profile()))
            self.assertEqual(result.supervisor_step.plan.decision, "IDLE")
            self.assertFalse(result.context_updated)
            self.assertEqual(result.live_state, before)
            self.assertEqual(session.live_state, before)
            self.assertEqual(engine.calls, 0)

    def test_session_run_owns_and_advances_live_context(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            person_path, person, revision = self.person_fixture(root)
            authority, state = self.durable_state(person.person_id, revision.id)
            store = SelfStateStore(root / "self.json")
            store.bootstrap(state, authority)
            engine = Engine()
            app = SimpleNamespace(
                state=SimpleNamespace(
                    consciousness_supervisor=self.bridge(engine)
                )
            )
            session = production_cognitive_session_factory(
                app,
                self_store_factory=lambda: store,
                registry_path_fn=lambda: str(person_path),
            )
            boot = session.live_state

            session.submit(
                CognitionEvent(
                    schema="kaliv-consciousness-core/cognition-event/v1",
                    event_id="cevt-" + "1" * 32,
                    kind="user_turn",
                    source_ref="event:user-turn:1",
                    summary="User asked the Consciousness Core to continue.",
                    salience=1.0,
                    observed_sequence=1,
                    production_activation=False,
                )
            )
            first = run(session.step(profile=self.profile("model-a")))
            self.assertEqual(first.supervisor_step.plan.decision, "RUN")
            self.assertTrue(first.context_updated)
            self.assertEqual(engine.calls, 1)
            self.assertEqual(first.live_state.completed_cycles, 1)
            self.assertEqual(
                first.live_state.state.revision,
                boot.state.revision + 2,
            )
            self.assertEqual(first.live_state.state.self_id, boot.state.self_id)
            self.assertEqual(
                first.live_state.state.person_revision,
                boot.state.person_revision,
            )
            self.assertEqual(first.live_state.world, boot.world)
            self.assertEqual(
                first.live_state.personality_snapshot,
                boot.personality_snapshot,
            )
            self.assertNotEqual(
                first.live_state.workspace,
                boot.workspace,
            )
            self.assertIsNotNone(
                first.live_state.last_transition_receipt_ref
            )
            # C19-B is in-memory only; durable store still has the original revision.
            self.assertEqual(store.read().revision, state.revision)

    def test_model_swap_changes_profile_not_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            person_path, person, revision = self.person_fixture(root)
            authority, state = self.durable_state(person.person_id, revision.id)
            store = SelfStateStore(root / "self.json")
            store.bootstrap(state, authority)
            engine = Engine()
            app = SimpleNamespace(
                state=SimpleNamespace(
                    consciousness_supervisor=self.bridge(engine)
                )
            )
            session = production_cognitive_session_factory(
                app,
                self_store_factory=lambda: store,
                registry_path_fn=lambda: str(person_path),
            )
            identity = (
                session.live_state.state.self_id,
                session.live_state.state.person_id,
                session.live_state.state.person_revision,
            )

            session.submit(
                CognitionEvent(
                    schema="kaliv-consciousness-core/cognition-event/v1",
                    event_id="cevt-" + "2" * 32,
                    kind="world_change",
                    source_ref="event:model-a",
                    summary="First cognition uses model A.",
                    salience=0.9,
                    observed_sequence=2,
                    production_activation=False,
                )
            )
            first = run(session.step(profile=self.profile("model-a")))
            session.submit(
                CognitionEvent(
                    schema="kaliv-consciousness-core/cognition-event/v1",
                    event_id="cevt-" + "3" * 32,
                    kind="world_change",
                    source_ref="event:model-b",
                    summary="Second cognition swaps to model B.",
                    salience=0.9,
                    observed_sequence=3,
                    production_activation=False,
                )
            )
            second = run(session.step(profile=self.profile("model-b")))

            self.assertTrue(first.context_updated)
            self.assertTrue(second.context_updated)
            self.assertEqual(engine.models, ["model-a", "model-b"])
            self.assertEqual(
                (
                    session.live_state.state.self_id,
                    session.live_state.state.person_id,
                    session.live_state.state.person_revision,
                ),
                identity,
            )
            self.assertEqual(session.live_state.completed_cycles, 2)

    def test_factory_fails_closed_on_person_revision_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            person_path, person, revision = self.person_fixture(root)
            authority, state = self.durable_state(
                person.person_id,
                "person-r9999",
            )
            store = SelfStateStore(root / "self.json")
            store.bootstrap(state, authority)
            app = SimpleNamespace(
                state=SimpleNamespace(
                    consciousness_supervisor=self.bridge(Engine())
                )
            )
            with self.assertRaises(Exception):
                production_cognitive_session_factory(
                    app,
                    self_store_factory=lambda: store,
                    registry_path_fn=lambda: str(person_path),
                )

    def test_lifecycle_mounts_session_only_inside_inner_supervisor_lifespan(self):
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

        class FakeSession:
            pass

        app = SimpleNamespace(state=SimpleNamespace())
        inactive = compose_cognitive_session_lifespan(
            inner,
            session_factory=lambda _app: None,
        )

        async def exercise_inactive():
            async with inactive(app):
                self.assertFalse(
                    hasattr(app.state, "consciousness_session")
                )

        run(exercise_inactive())
        self.assertIs(
            getattr(inactive, "__wrapped__", None),
            scheduler_owner,
        )

        # A real session is exposed only during the lifecycle window.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            person_path, person, revision = self.person_fixture(root)
            authority, state = self.durable_state(person.person_id, revision.id)
            store = SelfStateStore(root / "self.json")
            store.bootstrap(state, authority)
            lifecycle_engine = Engine()
            bridge = self.bridge(lifecycle_engine)
            bootstrap_app = SimpleNamespace(
                state=SimpleNamespace(consciousness_supervisor=bridge)
            )
            real_session = production_cognitive_session_factory(
                bootstrap_app,
                self_store_factory=lambda: store,
                registry_path_fn=lambda: str(person_path),
            )
            active = compose_cognitive_session_lifespan(
                inner,
                session_factory=lambda _app: real_session,
            )

            async def exercise_active():
                async with active(app):
                    self.assertIs(
                        app.state.consciousness_session,
                        real_session,
                    )
                    self.assertEqual(lifecycle_engine.calls, 0)
                self.assertFalse(
                    hasattr(app.state, "consciousness_session")
                )
                self.assertTrue(real_session.closed)

            run(exercise_active())

        # A deliberately invalid session factory must fail closed.
        wrong = compose_cognitive_session_lifespan(
            inner,
            session_factory=lambda _app: FakeSession(),
        )

        async def exercise_wrong():
            with self.assertRaises(TypeError):
                async with wrong(app):
                    pass

        run(exercise_wrong())

        # The documented production composition still preserves scheduler as
        # the underlying process-lifecycle authority owner.
        from app import entrypoint  # noqa: E402
        from app.schedule_runtime import scheduler_lifespan  # noqa: E402

        production_lifespan = entrypoint.fastapi_app.router.lifespan_context
        self.assertIs(
            getattr(production_lifespan, "__wrapped__", None),
            scheduler_lifespan,
        )


if __name__ == "__main__":
    unittest.main()
