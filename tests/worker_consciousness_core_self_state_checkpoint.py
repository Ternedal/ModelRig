#!/usr/bin/env python3
"""C27-A atomic SelfState transition-chain checkpoint tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_self_state_checkpoint.py
"""
from __future__ import annotations

import tempfile
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core.cycle import self_state_ref  # noqa: E402
from app.consciousness_core.self_state import (  # noqa: E402
    SelfAffect,
    SelfBootstrapAuthority,
    SelfStateCheckpointReceipt,
    SelfStateError,
    SelfStateStore,
    advance_self_state,
    bootstrap_self_state,
)


class CountingStore(SelfStateStore):
    def __init__(self, path):
        super().__init__(path)
        self.atomic_writes = 0

    def _write_atomic(self, state):
        self.atomic_writes += 1
        return super()._write_atomic(state)


class SelfStateCheckpointTests(unittest.TestCase):
    def authority(self):
        return SelfBootstrapAuthority(
            schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
            self_id="self-" + "a" * 32,
            person_id="person-" + "b" * 32,
            person_revision="person-r0007",
            authority="operator_review",
            authority_ref="operator:test:c27a",
            source_refs=["person-registry:test:c27a"],
            production_activation=False,
        )

    def initial(self):
        auth = self.authority()
        state = bootstrap_self_state(
            auth,
            personality_state_ref="personality-state:c27a",
            world_state_ref="world-state:c27a:0",
            workspace_ref="workspace:c27a:0",
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["affect:c27a"],
            ),
        )
        return auth, state

    def chain(self, state):
        n2 = advance_self_state(
            state,
            workspace_ref="workspace:c27a:1",
        )
        n3 = advance_self_state(
            n2,
            world_state_ref="world-state:c27a:1",
        )
        n4 = advance_self_state(
            n3,
            workspace_ref="workspace:c27a:2",
        )
        return n2, n3, n4

    def store(self, root):
        auth, state = self.initial()
        store = CountingStore(root / "self.json")
        store.bootstrap(state, auth)
        store.atomic_writes = 0
        return store, state

    def test_complete_chain_writes_only_final_state_once(self):
        with tempfile.TemporaryDirectory() as td:
            store, state = self.store(Path(td))
            n2, n3, n4 = self.chain(state)

            receipt = store.write_chain([n2, n3, n4])

            self.assertIsInstance(receipt, SelfStateCheckpointReceipt)
            self.assertEqual(store.atomic_writes, 1)
            self.assertEqual(store.read(), n4)
            self.assertEqual(receipt.revision_before, 1)
            self.assertEqual(receipt.revision_after, 4)
            self.assertEqual(receipt.transition_count, 3)
            self.assertEqual(
                receipt.previous_self_state_ref,
                self_state_ref(state),
            )
            self.assertEqual(
                receipt.final_self_state_ref,
                self_state_ref(n4),
            )
            self.assertEqual(
                receipt.transition_state_refs,
                [
                    self_state_ref(n2),
                    self_state_ref(n3),
                    self_state_ref(n4),
                ],
            )
            self.assertTrue(receipt.atomic_replace_applied)
            self.assertTrue(receipt.self_state_store_write_applied)
            self.assertFalse(receipt.intermediate_history_persisted)
            self.assertEqual(receipt.model_calls, 0)
            self.assertFalse(receipt.execution_authority)
            self.assertFalse(receipt.scheduling_authority)
            self.assertFalse(receipt.durable_memory_write_authority)
            self.assertFalse(receipt.production_activation)

    def test_revision_gap_fails_before_any_store_write(self):
        with tempfile.TemporaryDirectory() as td:
            store, state = self.store(Path(td))
            n2, _n3, n4 = self.chain(state)

            with self.assertRaises(SelfStateError):
                store.write_chain([n2, n4])

            self.assertEqual(store.atomic_writes, 0)
            self.assertEqual(store.read(), state)

    def test_stale_or_duplicate_revision_fails_before_write(self):
        with tempfile.TemporaryDirectory() as td:
            store, state = self.store(Path(td))
            n2, n3, _n4 = self.chain(state)
            store.write_next(n2)
            store.atomic_writes = 0

            with self.assertRaises(SelfStateError):
                store.write_chain([n2, n3])

            self.assertEqual(store.atomic_writes, 0)
            self.assertEqual(store.read(), n2)

    def test_identity_or_person_revision_change_is_forbidden(self):
        mutations = (
            {"self_id": "self-" + "9" * 32},
            {"person_id": "person-" + "8" * 32},
            {"person_revision": "person-r9999"},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                with tempfile.TemporaryDirectory() as td:
                    store, state = self.store(Path(td))
                    n2, _n3, _n4 = self.chain(state)
                    bad = n2.model_copy(update=mutation)

                    with self.assertRaises(SelfStateError):
                        store.write_chain([bad])

                    self.assertEqual(store.atomic_writes, 0)
                    self.assertEqual(store.read(), state)

    def test_empty_nonlist_and_overbound_chain_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            store, state = self.store(Path(td))

            with self.assertRaises(SelfStateError):
                store.write_chain([])
            with self.assertRaises(SelfStateError):
                store.write_chain(tuple())  # type: ignore[arg-type]

            chain = []
            current = state
            for index in range(129):
                current = advance_self_state(
                    current,
                    workspace_ref=f"workspace:c27a:{index + 1}",
                )
                chain.append(current)
            with self.assertRaises(SelfStateError):
                store.write_chain(chain)

            self.assertEqual(store.atomic_writes, 0)
            self.assertEqual(store.read(), state)

    def test_mapping_chain_is_validated_and_written(self):
        with tempfile.TemporaryDirectory() as td:
            store, state = self.store(Path(td))
            n2, n3, _n4 = self.chain(state)

            receipt = store.write_chain(
                [
                    n2.model_dump(mode="json"),
                    n3.model_dump(mode="json"),
                ]
            )

            self.assertEqual(store.atomic_writes, 1)
            self.assertEqual(store.read(), n3)
            self.assertEqual(receipt.transition_count, 2)

    def test_existing_write_next_semantics_remain_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            store, state = self.store(Path(td))
            n2, n3, _n4 = self.chain(state)

            store.write_next(n2)
            self.assertEqual(store.read(), n2)

            with self.assertRaises(SelfStateError):
                store.write_next(n3.model_copy(update={"revision": 4}))

            self.assertEqual(store.read(), n2)


if __name__ == "__main__":
    unittest.main()
