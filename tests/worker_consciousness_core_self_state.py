#!/usr/bin/env python3
"""C14 persistent SelfState authority tests."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT/"worker") not in sys.path:
    sys.path.insert(0,str(ROOT/"worker"))

from app.consciousness_core import (  # noqa: E402
    PersistentSelfState,
    PersonRevisionRebindAuthority,
    SelfAffect,
    SelfBootstrapAuthority,
    SelfStateError,
    SelfStateStore,
    advance_self_state,
    bootstrap_self_state,
    rebind_person_revision,
    verify_active_person,
)

SELF="self-"+"1"*32
PERSON="person-"+"2"*32
REV1="person-r0007"
REV2="person-r0008"


def authority():
    return SelfBootstrapAuthority(
        schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
        self_id=SELF,
        person_id=PERSON,
        person_revision=REV1,
        authority="operator_review",
        authority_ref="operator-review:self-bootstrap:1",
        source_refs=["person-profile:active:person-r0007"],
        production_activation=False,
    )


def affect():
    return SelfAffect(
        labels=["curious"],
        valence=0.2,
        arousal=0.3,
        confidence=0.9,
        source_refs=["event:bootstrap"],
    )


def initial():
    return bootstrap_self_state(
        authority(),
        personality_state_ref="personality-state:person-r0007:1",
        world_state_ref="world-state:1",
        workspace_ref="workspace:1",
        affect=affect(),
        active_goal_refs=["goal:1"],
    )


def rebind():
    return PersonRevisionRebindAuthority(
        schema="kaliv-consciousness-core/person-revision-rebind-authority/v1",
        self_id=SELF,
        person_id=PERSON,
        from_person_revision=REV1,
        to_person_revision=REV2,
        authority="person_revision_activation",
        authority_ref="person-registry:activation:person-r0008",
        source_refs=["person-profile:person-r0008"],
        production_activation=False,
    )


class PersistentSelfStateTests(unittest.TestCase):
    def test_bootstrap_is_explicit_and_model_independent(self):
        state=initial()
        self.assertEqual((state.self_id,state.person_id,state.person_revision),(SELF,PERSON,REV1))
        self.assertEqual(state.revision,1)
        for forbidden in ("model","provider","llm","thought_engine","engine_instance_id"):
            self.assertFalse(any(forbidden in name.lower() for name in PersistentSelfState.model_fields))

    def test_runtime_state_fields_match_c1_contract_exactly(self):
        schema=json.loads(
            (
                ROOT
                / "contracts"
                / "consciousness-core"
                / "self-state-v1.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            set(PersistentSelfState.model_fields),
            set(schema["properties"]),
        )
        self.assertEqual(
            set(schema["required"]),
            set(PersistentSelfState.model_fields),
        )

    def test_store_bootstrap_once_and_restart_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=SelfStateStore(Path(tmp)/"self.json")
            state=initial()
            store.bootstrap(state,authority())
            loaded=SelfStateStore(Path(tmp)/"self.json").read()
            self.assertEqual(loaded,state)
            with self.assertRaises(SelfStateError):
                store.bootstrap(state,authority())

    def test_normal_advance_preserves_identity_and_increments_revision(self):
        state=initial()
        next_state=advance_self_state(
            state,
            world_state_ref="world-state:2",
            workspace_ref="workspace:2",
            active_goal_refs=["goal:1","goal:2"],
        )
        self.assertEqual(next_state.revision,2)
        self.assertEqual((next_state.self_id,next_state.person_id,next_state.person_revision),(SELF,PERSON,REV1))
        self.assertEqual(next_state.world_state_ref,"world-state:2")

    def test_store_rejects_stale_skipped_or_changed_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=SelfStateStore(Path(tmp)/"self.json")
            state=initial()
            store.bootstrap(state,authority())
            skipped=advance_self_state(advance_self_state(state))
            with self.assertRaises(SelfStateError):
                store.write_next(skipped)
            changed=advance_self_state(state).model_copy(update={"self_id":"self-"+"f"*32})
            with self.assertRaises(SelfStateError):
                store.write_next(changed)

    def test_person_revision_change_requires_exact_rebind_authority(self):
        state=initial()
        next_state=rebind_person_revision(
            state,
            rebind(),
            personality_state_ref="personality-state:person-r0008:1",
        )
        self.assertEqual(next_state.person_revision,REV2)
        self.assertEqual(next_state.revision,2)
        with tempfile.TemporaryDirectory() as tmp:
            store=SelfStateStore(Path(tmp)/"self.json")
            store.bootstrap(state,authority())
            with self.assertRaises(SelfStateError):
                store.write_next(next_state)
            store.write_next(next_state,rebind_authority=rebind())
            self.assertEqual(store.read().person_revision,REV2)

    def test_stale_rebind_fails_closed(self):
        state=initial()
        bad=rebind().model_copy(update={"from_person_revision":"person-r0006"})
        with self.assertRaises(SelfStateError):
            rebind_person_revision(state,bad,personality_state_ref="personality-state:new")

    def test_active_person_profile_must_match_exactly(self):
        state=initial()
        self.assertEqual(
            verify_active_person(state,active_person_id=PERSON,active_person_revision=REV1),
            state,
        )
        with self.assertRaises(SelfStateError):
            verify_active_person(state,active_person_id=PERSON,active_person_revision=REV2)
        with self.assertRaises(SelfStateError):
            verify_active_person(state,active_person_id="person-"+"3"*32,active_person_revision=REV1)

    def test_tampered_store_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"self.json"
            store=SelfStateStore(path)
            store.bootstrap(initial(),authority())
            envelope=json.loads(path.read_text(encoding="utf-8"))
            envelope["payload"]["world_state_ref"]="world-state:tampered"
            path.write_text(json.dumps(envelope),encoding="utf-8")
            with self.assertRaises(SelfStateError):
                store.read()

    def test_source_has_no_model_memory_tool_scheduler_or_executor_authority(self):
        source=(ROOT/"worker/app/consciousness_core/self_state.py").read_text(encoding="utf-8")
        for forbidden in (
            "OllamaThoughtEngine","ThoughtEngine","MemoryStore","Agent3Orchestrator",
            "ToolGate","schedule_service","SchedulerRuntime","create_task(","threading.Thread",
        ):
            self.assertNotIn(forbidden,source)


if __name__=="__main__":
    unittest.main(verbosity=2)
