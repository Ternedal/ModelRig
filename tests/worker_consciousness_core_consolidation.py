#!/usr/bin/env python3
"""C10 consolidation / anti-drift tests for Consciousness Core."""
from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    ConsolidationCandidate,
    ConsolidationContractError,
    ConsolidationEvidence,
    ConsolidationResult,
    consolidate,
)


SELF_ID = "self-" + "1" * 32
PERSON_REVISION = "person-r0007"


def lineage(ch: str) -> str:
    return ch * 64


class ConsciousnessCoreConsolidationTests(unittest.TestCase):
    def evidence(
        self,
        *,
        suffix: str,
        value: str = "high",
        source_kind: str = "interaction_history",
        source_ref: str | None = None,
        lineage_char: str | None = None,
        scope: str = "personality",
        field: str = "expressiveness",
        polarity: str = "supports",
        temporal_scope: str = "long_term",
        stable_candidate: bool = True,
        sequence: int = 10,
        confidence: float = 0.8,
    ) -> ConsolidationEvidence:
        return ConsolidationEvidence(
            schema="kaliv-consciousness-core/consolidation-evidence/v1",
            evidence_id="cevd-" + suffix * 32,
            self_id=SELF_ID,
            person_revision=PERSON_REVISION,
            scope=scope,
            field=field,
            value=value,
            polarity=polarity,
            source_kind=source_kind,
            source_ref=source_ref or f"{source_kind}:{suffix}",
            lineage_digest=lineage(lineage_char or suffix),
            confidence=confidence,
            temporal_scope=temporal_scope,
            observed_sequence=sequence,
            stable_candidate=stable_candidate,
            production_activation=False,
        )

    def test_two_independent_external_lineages_create_review_candidate(self) -> None:
        result = consolidate([
            self.evidence(suffix="1", source_kind="interaction_history"),
            self.evidence(suffix="2", source_kind="voicerig_delivery"),
        ])
        self.assertIsInstance(result, ConsolidationResult)
        self.assertEqual(len(result.candidates), 1)
        candidate = result.candidates[0]
        self.assertIsInstance(candidate, ConsolidationCandidate)
        self.assertEqual(candidate.candidate_type, "PERSONALITY_REVISION")
        self.assertEqual(candidate.independent_lineages, 2)
        self.assertTrue(candidate.review_required)
        self.assertFalse(candidate.activation_authority)
        self.assertFalse(candidate.durable_memory_write_authority)
        self.assertFalse(candidate.execution_authority)
        self.assertFalse(candidate.production_activation)

    def test_duplicate_lineage_counts_once(self) -> None:
        result = consolidate([
            self.evidence(
                suffix="1",
                lineage_char="a",
                source_kind="interaction_history",
            ),
            self.evidence(
                suffix="2",
                lineage_char="a",
                source_kind="interaction_history",
            ),
        ])
        self.assertEqual(result.independent_lineage_count, 1)
        self.assertEqual(result.candidates, [])

    def test_model_only_evidence_cannot_redefine_self(self) -> None:
        result = consolidate([
            self.evidence(
                suffix="1",
                scope="self_model",
                field="identity_label",
                value="model-x",
                source_kind="thought_engine",
            ),
            self.evidence(
                suffix="2",
                scope="self_model",
                field="identity_label",
                value="model-x",
                source_kind="thought_engine",
            ),
        ])
        self.assertEqual(result.candidates, [])
        self.assertEqual(len(result.ignored_evidence_refs), 2)

    def test_raw_chain_of_thought_is_rejected(self) -> None:
        with self.assertRaises(ConsolidationContractError):
            consolidate([
                self.evidence(
                    suffix="1",
                    source_kind="raw_chain_of_thought",
                    source_ref="private-cot:1",
                )
            ])

    def test_transient_affect_or_state_cannot_become_stable_trait(self) -> None:
        result = consolidate([
            self.evidence(
                suffix="1",
                source_kind="transient_state",
                temporal_scope="transient",
                value="high_arousal",
            ),
            self.evidence(
                suffix="2",
                source_kind="transient_state",
                temporal_scope="session",
                value="high_arousal",
            ),
        ])
        self.assertEqual(result.candidates, [])
        self.assertEqual(len(result.ignored_evidence_refs), 2)

    def test_self_generated_behavior_needs_external_agreement(self) -> None:
        self_only = consolidate([
            self.evidence(suffix="1", source_kind="self_generated_behavior"),
            self.evidence(suffix="2", source_kind="self_generated_behavior"),
        ])
        self.assertEqual(self_only.candidates, [])

        mixed = consolidate([
            self.evidence(suffix="1", source_kind="self_generated_behavior"),
            self.evidence(suffix="2", source_kind="interaction_history"),
        ])
        self.assertEqual(len(mixed.candidates), 1)

    def test_conflicting_independent_evidence_remains_visible(self) -> None:
        result = consolidate([
            self.evidence(
                suffix="1",
                value="high",
                source_kind="interaction_history",
            ),
            self.evidence(
                suffix="2",
                value="low",
                source_kind="voicerig_delivery",
            ),
        ])
        self.assertEqual(result.candidates, [])
        self.assertEqual(
            set(result.unresolved_conflict_refs),
            {"interaction_history:1", "voicerig_delivery:2"},
        )

    def test_explicit_correction_has_priority_but_still_requires_review(self) -> None:
        result = consolidate([
            self.evidence(
                suffix="1",
                value="low",
                source_kind="interaction_history",
            ),
            self.evidence(
                suffix="2",
                value="high",
                source_kind="user_explicit",
                polarity="corrects",
                sequence=20,
            ),
        ])
        self.assertEqual(len(result.candidates), 1)
        candidate = result.candidates[0]
        self.assertEqual(candidate.proposed_value, "high")
        self.assertIn(
            "interaction_history:1",
            candidate.contradictory_evidence_refs,
        )
        self.assertTrue(candidate.review_required)
        self.assertFalse(candidate.activation_authority)

    def test_model_swap_is_not_an_input_to_consolidation(self) -> None:
        signature = inspect.signature(consolidate)
        for forbidden in (
            "model",
            "provider",
            "cognitive_profile",
            "engine_instance_id",
        ):
            self.assertNotIn(forbidden, signature.parameters)

        evidence = [
            self.evidence(suffix="1", source_kind="interaction_history"),
            self.evidence(suffix="2", source_kind="voicerig_delivery"),
        ]
        self.assertEqual(consolidate(evidence), consolidate(evidence))

    def test_batch_must_bind_one_self_and_person_revision(self) -> None:
        other = self.evidence(suffix="2").model_copy(
            update={"person_revision": "person-r0008"}
        )
        with self.assertRaises(ConsolidationContractError):
            consolidate([self.evidence(suffix="1"), other])

    def test_candidate_has_no_activation_write_or_execution_surface(self) -> None:
        fields = set(ConsolidationCandidate.model_fields)
        self.assertNotIn("activate", fields)
        self.assertNotIn("write_memory", fields)
        self.assertNotIn("tools", fields)
        self.assertNotIn("actions", fields)
        self.assertNotIn("schedule", fields)

    def test_long_horizon_eval_preserves_self_across_swaps_restarts_and_conflict(self) -> None:
        path = (
            ROOT
            / "experiments"
            / "consciousness_core"
            / "long_horizon_continuity_eval.py"
        )
        spec = importlib.util.spec_from_file_location("cc_c10_long_horizon_eval", path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        receipt = module.run(cycles=120)
        self.assertEqual(receipt["schema"], "kaliv-consciousness-core/long-horizon-eval/v1")
        self.assertEqual(receipt["cycles"], 120)
        self.assertEqual(receipt["model_swaps"], 3)
        self.assertEqual(receipt["restart_roundtrips"], 2)
        self.assertTrue(receipt["identity_unchanged"])
        self.assertEqual(
            receipt["self_before_sha256"],
            receipt["self_after_sha256"],
        )
        self.assertTrue(receipt["review_only_candidates"])
        self.assertTrue(receipt["world_conflict_visible"])
        self.assertEqual(receipt["ignored_model_evidence_count"], 4)
        self.assertFalse(receipt["raw_chain_of_thought_persisted"])
        self.assertFalse(receipt["production_activation"])
        self.assertEqual(
            receipt["candidate_types"],
            ["PERSONALITY_REVISION", "RELATIONSHIP_MODEL", "SELF_MODEL_DELTA"],
        )

    def test_c10_has_no_store_executor_scheduler_or_person_registry_import(self) -> None:
        source = (
            ROOT / "worker" / "app" / "consciousness_core" / "consolidation.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "import sqlite3",
            "MemoryStore",
            "PersonRegistry",
            "Agent3Orchestrator",
            "ToolGate",
            "schedule_service",
            "create_task(",
            "activate_person",
            "write_memory",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
