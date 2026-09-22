#!/usr/bin/env python3
"""C19 locked CAS SelfState committer tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_state_commit.py
"""
from __future__ import annotations

import asyncio
import copy
import json
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    CognitiveCycleCoordinator,
    CognitiveProfile,
    ConsciousnessCoreRuntime,
    LockedSelfStateCommitter,
    PersistentSelfState,
    PersonalitySnapshot,
    RuntimeWorldState,
    SelfAffect,
    SelfBootstrapAuthority,
    SelfStateStore,
    StateCommitError,
    StateCommitJournalRecord,
    WorkspaceCandidate,
    WorldObservation,
    adjudicate_cycle,
    build_workspace,
    initial_metacognitive_state,
    initial_supervisor_progress,
    plan_supervisor_step,
    self_state_ref,
    workspace_ref,
    world_state_ref,
)


FIXTURES = json.loads(
    (ROOT / "contracts" / "consciousness-core" / "fixtures-v1.json").read_text(
        encoding="utf-8"
    )
)


def run(coro):
    return asyncio.run(coro)


class StaticEngine:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    async def think(self, request, cognitive_profile, *, context=None):
        payload = copy.deepcopy(self.payload)
        payload["request_id"] = request.request_id
        return payload


class StateCommitTests(unittest.TestCase):
    def world(self) -> RuntimeWorldState:
        return RuntimeWorldState(
            schema="kaliv-consciousness-core/world-state/v1",
            world_id="world-" + "c" * 32,
            revision=11,
            observations=[
                WorldObservation(
                    observation_id="obs-" + "d" * 32,
                    subject_ref="project:modelrig",
                    proposition="C19 is testing production SelfState CAS semantics.",
                    confidence=1.0,
                    epistemic_status="observed",
                    source_refs=["github:branch:c19"],
                )
            ],
            production_activation=False,
        )

    def workspace(self):
        return build_workspace(
            cycle_id="cycle-" + "e" * 32,
            max_active=3,
            candidates=[
                WorkspaceCandidate(
                    candidate_id="wc-" + "1" * 32,
                    kind="perception",
                    salience=0.95,
                    summary="The Core requires a durable state transition.",
                    source_ref="event:test",
                ),
                WorkspaceCandidate(
                    candidate_id="wc-" + "2" * 32,
                    kind="goal",
                    salience=0.85,
                    summary="Preserve exact CAS and crash recovery semantics.",
                    source_ref="goal:c19",
                ),
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
            engine_instance_id="engine:test:c19",
            provider="mock",
            model="c19-fixture",
            reasoning_depth=0.9,
            planning_capacity=0.9,
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

    def state(self, world, workspace, personality) -> PersistentSelfState:
        return PersistentSelfState(
            schema="kaliv-consciousness-core/self-state/v1",
            self_id="self-" + "a" * 32,
            revision=30,
            person_id="person-" + "b" * 32,
            person_revision=personality.person_revision,
            personality_state_ref=personality.personality_state_ref,
            world_state_ref=world_state_ref(world),
            workspace_ref=workspace_ref(workspace),
            active_goal_refs=["goal:c19"],
            active_intention_refs=[],
            affect=SelfAffect(
                labels=["focused"],
                valence=0.1,
                arousal=0.35,
                confidence=0.9,
                source_refs=["event:test"],
            ),
            known_uncertainties=[],
            last_experience_ref=None,
            production_activation=False,
        )

    def proposal(self) -> dict[str, Any]:
        payload = copy.deepcopy(FIXTURES["thought_proposal"])
        payload["proposal_id"] = "thinkprop-" + "4" * 32
        payload["uncertainty"] = 0.05
        payload["interpretation"] = "The next state transition must be exact and bounded."
        payload["attention_suggestions"] = ["wc-" + "1" * 32]
        payload["hypotheses"] = []
        payload["candidate_intentions"] = []
        payload["predicted_outcomes"] = []
        payload["memory_queries"] = []
        payload["response_intent"] = None
        payload["body_intent"] = None
        return payload

    def transition_pair(self):
        world = self.world()
        workspace = self.workspace()
        personality = self.personality()
        state = self.state(world, workspace, personality)
        cycle = run(
            CognitiveCycleCoordinator(
                ConsciousnessCoreRuntime(StaticEngine(self.proposal()))
            ).run(
                state=state,
                world=world,
                workspace=workspace,
                personality_snapshot=personality,
                profile=self.profile(),
            )
        )
        base_meta = initial_metacognitive_state(self_ref=self_state_ref(state))

        verify_exec = adjudicate_cycle(
            cycle,
            workspace=workspace,
            metacognition=base_meta.model_copy(
                update={"verification_required": True}
            ),
        )
        verify = plan_supervisor_step(
            verify_exec,
            cycle=cycle,
            current_state=state,
            workspace=workspace,
            progress=initial_supervisor_progress(cycle_id=cycle.request.cycle_id),
        )
        self.assertEqual(verify.action, "NEXT_CYCLE")
        assert verify.transition is not None

        decompose_exec = adjudicate_cycle(
            cycle,
            workspace=workspace,
            metacognition=base_meta.model_copy(
                update={"decomposition_required": True}
            ),
        )
        decompose = plan_supervisor_step(
            decompose_exec,
            cycle=cycle,
            current_state=state,
            workspace=workspace,
            progress=initial_supervisor_progress(cycle_id=cycle.request.cycle_id),
        )
        self.assertEqual(decompose.action, "NEXT_CYCLE")
        assert decompose.transition is not None
        self.assertNotEqual(
            verify.transition.transition_id,
            decompose.transition.transition_id,
        )
        return state, verify.transition, decompose.transition

    def bootstrapped_store(self, root: Path, state: PersistentSelfState):
        path = root / "self-state.json"
        store = SelfStateStore(path)
        authority = SelfBootstrapAuthority(
            schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
            self_id=state.self_id,
            person_id=state.person_id,
            person_revision=state.person_revision,
            authority="operator_review",
            authority_ref="test:c19-bootstrap",
            source_refs=["test:c19"],
            production_activation=False,
        )
        store.bootstrap(state, authority)
        return store

    def test_successful_exact_cas_commit(self):
        state, transition, _ = self.transition_pair()
        with tempfile.TemporaryDirectory() as td:
            store = self.bootstrapped_store(Path(td), state)
            committer = LockedSelfStateCommitter(store)
            receipt = committer.commit(transition)

            persisted = store.read()
            self.assertIsNotNone(persisted)
            assert persisted is not None
            self.assertEqual(persisted, transition.next_self_state)
            self.assertEqual(
                receipt.committed_self_state_ref,
                self_state_ref(transition.next_self_state),
            )
            self.assertEqual(receipt.committed_revision, state.revision + 1)
            self.assertTrue(receipt.persisted)

            journal = committer._read_journal()
            self.assertIsInstance(journal, StateCommitJournalRecord)
            assert journal is not None
            self.assertEqual(journal.state, "committed")
            self.assertEqual(journal.transition_id, transition.transition_id)

    def test_same_transition_is_idempotent(self):
        state, transition, _ = self.transition_pair()
        with tempfile.TemporaryDirectory() as td:
            store = self.bootstrapped_store(Path(td), state)
            committer = LockedSelfStateCommitter(store)
            first = committer.commit(transition)
            second = committer.commit(transition)
            self.assertEqual(first, second)
            persisted = store.read()
            assert persisted is not None
            self.assertEqual(persisted.revision, state.revision + 1)

    def test_stale_divergent_transition_fails_closed(self):
        state, first_transition, second_transition = self.transition_pair()
        with tempfile.TemporaryDirectory() as td:
            store = self.bootstrapped_store(Path(td), state)
            committer = LockedSelfStateCommitter(store)
            committer.commit(first_transition)
            with self.assertRaises(StateCommitError):
                committer.commit(second_transition)
            persisted = store.read()
            self.assertEqual(persisted, first_transition.next_self_state)

    def test_prepared_before_state_recovers_aborted(self):
        state, transition, _ = self.transition_pair()
        with tempfile.TemporaryDirectory() as td:
            store = self.bootstrapped_store(Path(td), state)
            committer = LockedSelfStateCommitter(store)
            prepared = committer._record(transition, state, state="prepared")
            committer._write_journal(prepared)

            recovery = committer.recover()
            self.assertEqual(recovery.outcome, "aborted")
            journal = committer._read_journal()
            assert journal is not None
            self.assertEqual(journal.state, "aborted")
            self.assertEqual(store.read(), state)

    def test_prepared_after_state_recovers_committed(self):
        state, transition, _ = self.transition_pair()
        with tempfile.TemporaryDirectory() as td:
            store = self.bootstrapped_store(Path(td), state)
            committer = LockedSelfStateCommitter(store)
            prepared = committer._record(transition, state, state="prepared")
            committer._write_journal(prepared)
            store.write_next(transition.next_self_state)

            recovery = committer.recover()
            self.assertEqual(recovery.outcome, "committed")
            journal = committer._read_journal()
            assert journal is not None
            self.assertEqual(journal.state, "committed")
            self.assertEqual(store.read(), transition.next_self_state)

    def test_prepared_unrelated_state_recovers_conflict(self):
        state, transition, _ = self.transition_pair()
        with tempfile.TemporaryDirectory() as td:
            store = self.bootstrapped_store(Path(td), state)
            committer = LockedSelfStateCommitter(store)
            prepared = committer._record(transition, state, state="prepared")
            committer._write_journal(prepared)

            unrelated = state.model_copy(
                update={
                    "revision": state.revision + 1,
                    "workspace_ref": "workspace:unrelated-c19",
                }
            )
            store.write_next(unrelated)
            recovery = committer.recover()
            self.assertEqual(recovery.outcome, "conflict")
            journal = committer._read_journal()
            assert journal is not None
            self.assertEqual(journal.state, "conflict")
            with self.assertRaises(StateCommitError):
                committer.commit(transition)

    def test_tampered_transition_integrity_fails_before_write(self):
        state, transition, _ = self.transition_pair()
        with tempfile.TemporaryDirectory() as td:
            store = self.bootstrapped_store(Path(td), state)
            committer = LockedSelfStateCommitter(store)
            tampered_state = transition.next_self_state.model_copy(
                update={"active_goal_refs": ["goal:tampered"]}
            )
            tampered = transition.model_copy(
                update={"next_self_state": tampered_state}
            )
            with self.assertRaises(StateCommitError):
                committer.commit(tampered)
            self.assertEqual(store.read(), state)
            self.assertFalse(committer.journal_path.exists())

    def test_malformed_or_tampered_journal_fails_closed(self):
        state, transition, _ = self.transition_pair()
        with tempfile.TemporaryDirectory() as td:
            store = self.bootstrapped_store(Path(td), state)
            committer = LockedSelfStateCommitter(store)
            committer.journal_path.write_text("{ broken", encoding="utf-8")
            with self.assertRaises(StateCommitError):
                committer.recover()

            committer.journal_path.write_text(
                json.dumps(
                    {
                        "schema": "wrong",
                        "transaction_id": "stx-" + "1" * 32,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(StateCommitError):
                committer.commit(transition)
            self.assertEqual(store.read(), state)

    def test_concurrent_divergent_writers_cannot_both_commit_source_revision(self):
        state, first_transition, second_transition = self.transition_pair()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "self-state.json"
            self.bootstrapped_store(Path(td), state)
            barrier = threading.Barrier(2)

            def attempt(transition):
                committer = LockedSelfStateCommitter(state_path=path)
                barrier.wait()
                try:
                    receipt = committer.commit(transition)
                    return ("committed", receipt.transition_id)
                except StateCommitError:
                    return ("rejected", transition.transition_id)

            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(
                    pool.map(attempt, [first_transition, second_transition])
                )

            self.assertEqual(
                sorted(item[0] for item in outcomes),
                ["committed", "rejected"],
            )
            persisted = SelfStateStore(path).read()
            assert persisted is not None
            self.assertEqual(persisted.revision, state.revision + 1)
            self.assertIn(
                self_state_ref(persisted),
                {
                    self_state_ref(first_transition.next_self_state),
                    self_state_ref(second_transition.next_self_state),
                },
            )

    def test_lock_contract_has_no_polling_or_msvcrt_locking(self):
        source = (
            ROOT / "worker" / "app" / "consciousness_core" / "state_commit.py"
        ).read_text(encoding="utf-8")
        self.assertIn("fcntl.flock(descriptor, fcntl.LOCK_EX)", source)
        self.assertIn("LockFileEx", source)
        self.assertIn("UnlockFileEx", source)
        for forbidden in (
            "LOCK_NB",
            "msvcrt.locking",
            "time.sleep",
            "while True",
            "asyncio.create_task",
            "threading.Thread",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
