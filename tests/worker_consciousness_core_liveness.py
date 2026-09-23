#!/usr/bin/env python3
"""C29-A durable runtime liveness witness tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_liveness.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core.liveness import (  # noqa: E402
    RuntimeLivenessError,
    RuntimeLivenessStore,
    build_runtime_liveness_witness,
    runtime_liveness_witness_ref,
)
from app.consciousness_core.self_state import (  # noqa: E402
    SelfAffect,
    SelfBootstrapAuthority,
    advance_self_state,
    bootstrap_self_state,
)
from app.consciousness_core.temporal import (  # noqa: E402
    ClockSample,
    anchor_from_clock,
)


class RuntimeLivenessTests(unittest.TestCase):
    def state(
        self,
        *,
        self_marker: str = "a",
        person_marker: str = "b",
        person_revision: str = "person-r0007",
    ):
        authority = SelfBootstrapAuthority(
            schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
            self_id="self-" + self_marker * 32,
            person_id="person-" + person_marker * 32,
            person_revision=person_revision,
            authority="operator_review",
            authority_ref="operator:test:c29a",
            source_refs=["registry:test:c29a"],
            production_activation=False,
        )
        return bootstrap_self_state(
            authority,
            personality_state_ref="personality-state:c29a",
            world_state_ref="world-state:c29a",
            workspace_ref="workspace:c29a",
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["affect:c29a"],
            ),
        )

    def anchor(
        self,
        marker: str,
        *,
        sequence: int,
        monotonic_ms: int,
        epoch_marker: str = "1",
        wall_ms: int | None = None,
        confidence: float = 1.0,
    ):
        wall = (
            1_700_000_000_000 + sequence * 1000
            if wall_ms is None
            else wall_ms
        )
        sample = ClockSample(
            schema="kaliv-consciousness-core/clock-sample/v1",
            sample_id="clock-" + marker * 32,
            wall_time_unix_ms=wall,
            timezone_name="Europe/Copenhagen",
            utc_offset_minutes=120,
            local_hour=12,
            monotonic_ms=monotonic_ms,
            runtime_epoch_id="epoch-" + epoch_marker * 32,
            sampled_sequence=sequence,
            source_ref="trusted:test:c29a:" + marker,
            confidence=confidence,
            production_activation=False,
        )
        return anchor_from_clock(
            sample,
            event_ref="runtime-liveness:test:" + marker,
        )

    def witness(
        self,
        state,
        marker: str,
        *,
        sequence: int,
        monotonic_ms: int,
        epoch_marker: str = "1",
    ):
        return build_runtime_liveness_witness(
            state=state,
            anchor=self.anchor(
                marker,
                sequence=sequence,
                monotonic_ms=monotonic_ms,
                epoch_marker=epoch_marker,
            ),
            source_ref="checkpoint:test:c29a:" + marker,
        )

    def test_builder_binds_exact_durable_state_and_trusted_anchor(self):
        state = self.state()
        witness = self.witness(
            state,
            "1",
            sequence=1,
            monotonic_ms=100,
        )

        self.assertEqual(witness.self_id, state.self_id)
        self.assertEqual(witness.person_id, state.person_id)
        self.assertEqual(
            witness.person_revision,
            state.person_revision,
        )
        self.assertEqual(
            witness.durable_self_state_revision,
            state.revision,
        )
        self.assertTrue(witness.runtime_alive_at_anchor)
        self.assertFalse(witness.cognition_after_anchor_claimed)
        self.assertFalse(witness.execution_authority)
        self.assertFalse(witness.scheduling_authority)
        self.assertFalse(witness.durable_memory_write_authority)
        self.assertTrue(
            runtime_liveness_witness_ref(witness).startswith(
                "runtime-liveness-witness:"
            )
        )

    def test_builder_rejects_non_trusted_temporal_confidence(self):
        state = self.state()
        with self.assertRaisesRegex(
            RuntimeLivenessError,
            "trusted temporal confidence",
        ):
            build_runtime_liveness_witness(
                state=state,
                anchor=self.anchor(
                    "2",
                    sequence=1,
                    monotonic_ms=100,
                    confidence=0.9,
                ),
                source_ref="checkpoint:test:c29a:untrusted",
            )

    def test_store_create_read_and_exact_idempotence(self):
        state = self.state()
        witness = self.witness(
            state,
            "3",
            sequence=1,
            monotonic_ms=100,
        )
        with tempfile.TemporaryDirectory() as td:
            store = RuntimeLivenessStore(
                Path(td) / "liveness.json"
            )

            created = store.write_next(witness)
            self.assertEqual(created.outcome, "CREATED")
            self.assertTrue(created.store_write_applied)
            self.assertIsNone(created.previous_witness_ref)
            self.assertEqual(store.read(), witness)

            idempotent = store.write_next(witness)
            self.assertEqual(idempotent.outcome, "IDEMPOTENT")
            self.assertFalse(idempotent.store_write_applied)
            self.assertEqual(
                idempotent.previous_witness_ref,
                idempotent.witness_ref,
            )
            self.assertEqual(store.read(), witness)

    def test_same_revision_can_move_forward_in_same_epoch(self):
        state = self.state()
        first = self.witness(
            state,
            "4",
            sequence=1,
            monotonic_ms=100,
        )
        second = self.witness(
            state,
            "5",
            sequence=2,
            monotonic_ms=150,
        )
        with tempfile.TemporaryDirectory() as td:
            store = RuntimeLivenessStore(
                Path(td) / "liveness.json"
            )
            store.write_next(first)
            receipt = store.write_next(second)

            self.assertEqual(receipt.outcome, "UPDATED")
            self.assertTrue(receipt.store_write_applied)
            self.assertEqual(
                receipt.durable_self_state_revision_before,
                state.revision,
            )
            self.assertEqual(
                receipt.durable_self_state_revision_after,
                state.revision,
            )
            self.assertEqual(store.read(), second)

    def test_same_revision_cannot_cross_runtime_epoch(self):
        state = self.state()
        first = self.witness(
            state,
            "6",
            sequence=1,
            monotonic_ms=100,
            epoch_marker="1",
        )
        cross_epoch = self.witness(
            state,
            "7",
            sequence=2,
            monotonic_ms=10,
            epoch_marker="2",
        )
        with tempfile.TemporaryDirectory() as td:
            store = RuntimeLivenessStore(
                Path(td) / "liveness.json"
            )
            store.write_next(first)
            with self.assertRaisesRegex(
                RuntimeLivenessError,
                "cannot cross runtime epochs",
            ):
                store.write_next(cross_epoch)
            self.assertEqual(store.read(), first)

    def test_same_revision_rejects_stale_sequence(self):
        state = self.state()
        first = self.witness(
            state,
            "8",
            sequence=2,
            monotonic_ms=200,
        )
        stale = self.witness(
            state,
            "9",
            sequence=1,
            monotonic_ms=250,
        )
        with tempfile.TemporaryDirectory() as td:
            store = RuntimeLivenessStore(
                Path(td) / "liveness.json"
            )
            store.write_next(first)
            with self.assertRaisesRegex(
                RuntimeLivenessError,
                "temporal sequence is stale",
            ):
                store.write_next(stale)

    def test_same_revision_rejects_monotonic_rollback(self):
        state = self.state()
        first = self.witness(
            state,
            "a",
            sequence=1,
            monotonic_ms=200,
        )
        rollback = self.witness(
            state,
            "b",
            sequence=2,
            monotonic_ms=150,
        )
        with tempfile.TemporaryDirectory() as td:
            store = RuntimeLivenessStore(
                Path(td) / "liveness.json"
            )
            store.write_next(first)
            with self.assertRaisesRegex(
                RuntimeLivenessError,
                "monotonic clock moved backwards",
            ):
                store.write_next(rollback)

    def test_same_revision_conflicting_state_ref_fails_closed(self):
        state = self.state()
        first = self.witness(
            state,
            "c",
            sequence=1,
            monotonic_ms=100,
        )
        conflicting_state = state.model_copy(
            update={"workspace_ref": "workspace:c29a:conflict"}
        )
        conflicting = self.witness(
            conflicting_state,
            "d",
            sequence=2,
            monotonic_ms=150,
        )
        self.assertEqual(
            conflicting.durable_self_state_revision,
            first.durable_self_state_revision,
        )
        self.assertNotEqual(
            conflicting.durable_self_state_ref,
            first.durable_self_state_ref,
        )

        with tempfile.TemporaryDirectory() as td:
            store = RuntimeLivenessStore(
                Path(td) / "liveness.json"
            )
            store.write_next(first)
            with self.assertRaisesRegex(
                RuntimeLivenessError,
                "conflicting ref",
            ):
                store.write_next(conflicting)
            self.assertEqual(store.read(), first)

    def test_lower_durable_revision_is_rejected(self):
        state = self.state()
        next_state = advance_self_state(
            state,
            workspace_ref="workspace:c29a:next",
        )
        newer = self.witness(
            next_state,
            "e",
            sequence=2,
            monotonic_ms=200,
        )
        older = self.witness(
            state,
            "f",
            sequence=3,
            monotonic_ms=250,
        )

        with tempfile.TemporaryDirectory() as td:
            store = RuntimeLivenessStore(
                Path(td) / "liveness.json"
            )
            store.write_next(newer)
            with self.assertRaisesRegex(
                RuntimeLivenessError,
                "revision moved backwards",
            ):
                store.write_next(older)
            self.assertEqual(store.read(), newer)

    def test_higher_durable_revision_may_cross_runtime_epoch(self):
        state = self.state()
        next_state = advance_self_state(
            state,
            workspace_ref="workspace:c29a:next-epoch",
        )
        first = self.witness(
            state,
            "1",
            sequence=10,
            monotonic_ms=500,
            epoch_marker="1",
        )
        restarted = self.witness(
            next_state,
            "2",
            sequence=1,
            monotonic_ms=10,
            epoch_marker="2",
        )

        with tempfile.TemporaryDirectory() as td:
            store = RuntimeLivenessStore(
                Path(td) / "liveness.json"
            )
            store.write_next(first)
            receipt = store.write_next(restarted)

            self.assertEqual(receipt.outcome, "UPDATED")
            self.assertEqual(
                receipt.durable_self_state_revision_before,
                state.revision,
            )
            self.assertEqual(
                receipt.durable_self_state_revision_after,
                next_state.revision,
            )
            self.assertEqual(store.read(), restarted)

    def test_identity_change_is_rejected(self):
        state = self.state()
        other = self.state(
            self_marker="f",
            person_marker="e",
            person_revision="person-r0008",
        )
        first = self.witness(
            state,
            "3",
            sequence=1,
            monotonic_ms=100,
        )
        changed = self.witness(
            other,
            "4",
            sequence=2,
            monotonic_ms=150,
        )

        with tempfile.TemporaryDirectory() as td:
            store = RuntimeLivenessStore(
                Path(td) / "liveness.json"
            )
            store.write_next(first)
            with self.assertRaisesRegex(
                RuntimeLivenessError,
                "identity binding changed",
            ):
                store.write_next(changed)

    def test_digest_tamper_fails_closed(self):
        state = self.state()
        witness = self.witness(
            state,
            "5",
            sequence=1,
            monotonic_ms=100,
        )
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "liveness.json"
            store = RuntimeLivenessStore(path)
            store.write_next(witness)

            envelope = json.loads(path.read_text(encoding="utf-8"))
            envelope["payload"]["source_ref"] = "tampered:c29a"
            path.write_text(
                json.dumps(envelope),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                RuntimeLivenessError,
                "digest mismatch",
            ):
                store.read()


if __name__ == "__main__":
    unittest.main()
