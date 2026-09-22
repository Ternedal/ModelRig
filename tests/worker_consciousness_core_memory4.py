#!/usr/bin/env python3
"""C7 ExperienceCandidate / Memory 4 bridge tests for Consciousness Core.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_memory4.py
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    ExperienceCandidate,
    ExperienceMemoryError,
    Memory4ExperienceBridge,
    MemoryContextSnapshot,
    MemoryDurableReceiptRef,
    plan_memory_handoff,
)
from app.memory.context_service import (  # noqa: E402
    CONTEXT_RECEIPT_SCHEMA,
    ContextForTurnReceipt,
    ContextForTurnResult,
)
from app.memory.extraction import CompletedMemoryTurn  # noqa: E402
from app.memory.write_service import (  # noqa: E402
    TURN_WRITE_RECEIPT_SCHEMA,
    CompletedTurnWriteReceipt,
)


def run(coro):
    return asyncio.run(coro)


class FakeContextService:
    def __init__(self, result: ContextForTurnResult) -> None:
        self.result = result
        self.calls = []

    async def context_for_turn(self, request):
        self.calls.append(request)
        return self.result


class FakeWriteService:
    def __init__(self, receipt: CompletedTurnWriteReceipt) -> None:
        self.receipt = receipt
        self.calls = []

    async def commit_completed_turn(self, turn):
        self.calls.append(turn)
        return self.receipt


class ConsciousnessCoreMemory4Tests(unittest.TestCase):
    def candidate(
        self,
        *,
        kind: str = "USER_STATED_FACT",
        provenance: str = "user_explicit",
        sensitivity: str = "private",
        source_ref: str | None = "chat-turn:1",
    ) -> ExperienceCandidate:
        return ExperienceCandidate(
            schema="kaliv-consciousness-core/experience-candidate/v1",
            experience_id="exp-" + "1" * 32,
            cycle_id="cycle-" + "2" * 32,
            self_id="self-" + "3" * 32,
            person_id="person-" + "4" * 32,
            person_revision="person-r0007",
            kind=kind,
            event_ref="event:user-turn:1",
            participant_refs=["person:user"],
            self_state_before_ref="self-state:before",
            self_state_after_ref="self-state:after",
            active_goal_refs=["goal:help-user"],
            intention_ref="intent:respond",
            prediction_refs=[],
            outcome_refs=[],
            prediction_error_refs=[],
            personality_state_ref="personality-state:1",
            world_state_delta_refs=[],
            significance=0.7,
            provenance_kind=provenance,
            sensitivity=sensitivity,
            source_refs=["event:user-turn:1"],
            completed_turn_source_ref=source_ref,
            production_activation=False,
        )

    def context_result(
        self,
        *,
        context: str = "memory reference block",
        bad_hash: bool = False,
    ) -> ContextForTurnResult:
        digest = hashlib.sha256(context.encode("utf-8")).hexdigest()
        if bad_hash:
            digest = "f" * 64
        receipt = ContextForTurnReceipt(
            schema=CONTEXT_RECEIPT_SCHEMA,
            target="local",
            semantic_enabled=False,
            candidate_count=2,
            ranked_count=1,
            included_ids=("memory-1",),
            excluded_count=1,
            exclusion_reasons={"not_relevant_or_below_threshold": 1, "context_budget": 0},
            character_count=len(context),
            byte_count=len(context.encode("utf-8")),
            context_sha256=digest,
            sent_to_model=False,
        )
        return ContextForTurnResult(context=context, receipt=receipt)

    def write_receipt(self) -> CompletedTurnWriteReceipt:
        return CompletedTurnWriteReceipt(
            schema=TURN_WRITE_RECEIPT_SCHEMA,
            candidate_count=1,
            considered_count=1,
            created_ids=("memory-created-1",),
            superseded_ids=(),
            superseding_ids=(),
            deduped_ids=(),
            skipped_count=0,
            replayed=False,
            sent_to_store=True,
        )

    def test_structured_inference_requires_trusted_review(self) -> None:
        inferred = self.candidate(
            kind="PREDICTION_ERROR",
            provenance="inferred",
            source_ref=None,
        )
        decision = plan_memory_handoff(inferred)
        self.assertEqual(decision.status, "trusted_review_required")
        self.assertFalse(decision.production_activation)

    def test_secret_experience_is_blocked_from_auto_persist(self) -> None:
        secret = self.candidate(sensitivity="secret")
        decision = plan_memory_handoff(secret)
        self.assertEqual(decision.status, "blocked_secret")

    def test_only_user_explicit_bound_turn_gets_completed_turn_authority(self) -> None:
        candidate = self.candidate()
        decision = plan_memory_handoff(candidate)
        self.assertEqual(decision.status, "completed_turn_authority")

        missing_binding = self.candidate(source_ref=None)
        self.assertEqual(
            plan_memory_handoff(missing_binding).status,
            "trusted_review_required",
        )

    def test_recall_preserves_memory4_receipt_as_reference_data(self) -> None:
        service = FakeContextService(self.context_result())
        bridge = Memory4ExperienceBridge(context_service=service)
        snapshot = run(
            bridge.recall(
                query="what happened before",
                subjects=("project:modelrig",),
            )
        )
        self.assertIsInstance(snapshot, MemoryContextSnapshot)
        self.assertEqual(snapshot.authority, "reference_data")
        self.assertFalse(snapshot.sent_to_model)
        self.assertEqual(snapshot.included_ids, ["memory-1"])
        self.assertTrue(snapshot.source_ref.startswith("memory4-context:"))
        self.assertEqual(len(service.calls), 1)

    def test_recall_rejects_receipt_hash_mismatch(self) -> None:
        bridge = Memory4ExperienceBridge(
            context_service=FakeContextService(self.context_result(bad_hash=True))
        )
        with self.assertRaises(ExperienceMemoryError):
            run(bridge.recall(query="bounded query"))

    def test_write_submits_original_completed_turn_not_experience_semantics(self) -> None:
        service = FakeWriteService(self.write_receipt())
        bridge = Memory4ExperienceBridge(write_service=service)
        candidate = self.candidate()
        turn = CompletedMemoryTurn(
            user_text="Jeg foretrækker korte svar.",
            assistant_text="Det tager jeg højde for.",
            source_ref="chat-turn:1",
        )
        receipt = run(bridge.submit_completed_turn(candidate, turn))

        self.assertIsInstance(receipt, MemoryDurableReceiptRef)
        self.assertEqual(len(service.calls), 1)
        self.assertIs(service.calls[0], turn)
        self.assertEqual(receipt.created_ids, ["memory-created-1"])
        self.assertTrue(receipt.sent_to_store)

        fields = set(ExperienceCandidate.model_fields)
        self.assertNotIn("subject", fields)
        self.assertNotIn("predicate", fields)
        self.assertNotIn("review_status", fields)
        self.assertNotIn("supersedes_id", fields)

    def test_inferred_experience_never_calls_memory4_writer(self) -> None:
        service = FakeWriteService(self.write_receipt())
        bridge = Memory4ExperienceBridge(write_service=service)
        inferred = self.candidate(
            kind="SELF_ACTION_OUTCOME",
            provenance="inferred",
            source_ref=None,
        )
        turn = CompletedMemoryTurn(
            user_text="irrelevant",
            assistant_text="irrelevant",
            source_ref="chat-turn:other",
        )
        with self.assertRaises(ExperienceMemoryError):
            run(bridge.submit_completed_turn(inferred, turn))
        self.assertEqual(service.calls, [])

    def test_completed_turn_binding_mismatch_fails_before_write(self) -> None:
        service = FakeWriteService(self.write_receipt())
        bridge = Memory4ExperienceBridge(write_service=service)
        turn = CompletedMemoryTurn(
            user_text="Hej",
            assistant_text="Hej",
            source_ref="different-turn",
        )
        with self.assertRaises(ExperienceMemoryError):
            run(bridge.submit_completed_turn(self.candidate(), turn))
        self.assertEqual(service.calls, [])

    def test_missing_memory_services_fail_closed(self) -> None:
        bridge = Memory4ExperienceBridge()
        with self.assertRaises(ExperienceMemoryError):
            run(bridge.recall(query="something"))

        turn = CompletedMemoryTurn(
            user_text="Hej",
            assistant_text="Hej",
            source_ref="chat-turn:1",
        )
        with self.assertRaises(ExperienceMemoryError):
            run(bridge.submit_completed_turn(self.candidate(), turn))

    def test_memory_context_does_not_claim_worldstate_authority(self) -> None:
        fields = set(MemoryContextSnapshot.model_fields)
        self.assertNotIn("world_state_mutation", fields)
        self.assertNotIn("truth", fields)
        self.assertNotIn("system_instruction", fields)

        snapshot = run(
            Memory4ExperienceBridge(
                context_service=FakeContextService(self.context_result())
            ).recall(query="reference")
        )
        self.assertEqual(snapshot.authority, "reference_data")

    def test_bridge_has_no_parallel_store_or_background_retry(self) -> None:
        source = (
            ROOT / "worker" / "app" / "consciousness_core" / "experience.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "import sqlite3",
            ".storage import",
            "MemoryStore",
            "create_task(",
            "schedule_service",
            "background",
            "retry",
        ):
            self.assertNotIn(forbidden, source)

    def test_candidate_roundtrip_has_no_durable_authority_fields(self) -> None:
        candidate = self.candidate()
        restored = ExperienceCandidate.model_validate_json(candidate.model_dump_json())
        self.assertEqual(candidate, restored)
        for field in (
            "memory_id",
            "review_status",
            "durable",
            "delete",
            "correct",
            "supersedes_id",
        ):
            self.assertNotIn(field, ExperienceCandidate.model_fields)


if __name__ == "__main__":
    unittest.main(verbosity=2)
