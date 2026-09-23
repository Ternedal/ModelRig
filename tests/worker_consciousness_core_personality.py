#!/usr/bin/env python3
"""C6 multi-source Personality Resolver tests for Consciousness Core.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_personality.py
"""
from __future__ import annotations

import copy
import inspect
import sys
import unittest
from pathlib import Path

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    IdentityTrait,
    PersonalityEvidence,
    PersonalityIdentitySnapshot,
    PersonalityModel,
    PersonalityResolverError,
    PersonalityState,
    TransientTraitModifier,
    resolve_personality_model,
    resolve_personality_state,
)


PERSON_ID = "person-" + "b" * 32
PERSON_REVISION = "person-r0007"
PERSONALITY_REVISION = "personality-r0005"
DIGEST = "a" * 64


class ConsciousnessCorePersonalityTests(unittest.TestCase):
    def identity(self) -> PersonalityIdentitySnapshot:
        return PersonalityIdentitySnapshot(
            schema="kaliv-consciousness-core/personality-identity-snapshot/v1",
            person_id=PERSON_ID,
            person_revision=PERSON_REVISION,
            personality_revision=PERSONALITY_REVISION,
            semantic_traits=[
                IdentityTrait(
                    trait_id="directness",
                    value=0.70,
                    source_ref="person-profile:personality-r0005",
                ),
                IdentityTrait(
                    trait_id="warmth",
                    value=0.65,
                    source_ref="person-profile:personality-r0005",
                ),
            ],
            source_refs=["person-profile:person-r0007"],
            production_activation=False,
        )

    def evidence(
        self,
        *,
        suffix: str = "1",
        source_kind: str = "INTERACTION_HISTORY",
        domain: str = "semantic",
        trait_id: str = "directness",
        value: float = 0.80,
        confidence: float = 0.60,
        lineage: str = "lineage:one",
        source_ref: str = "interaction:1",
        digest: str | None = None,
        approval: str | None = None,
        person_revision: str = PERSON_REVISION,
    ) -> PersonalityEvidence:
        return PersonalityEvidence(
            schema="kaliv-consciousness-core/personality-evidence/v1",
            evidence_id="pe-" + suffix * 32,
            person_id=PERSON_ID,
            person_revision=person_revision,
            source_kind=source_kind,
            trait_domain=domain,
            trait_id=trait_id,
            value=value,
            confidence=confidence,
            lineage_ref=lineage,
            source_ref=source_ref,
            immutable_digest=digest,
            approval_ref=approval,
            production_activation=False,
        )

    def test_bodyrig_can_only_supply_embodied_mannerisms(self) -> None:
        with self.assertRaises(ValidationError):
            self.evidence(
                source_kind="BODYRIG_MANNERISM",
                domain="semantic",
                trait_id="warmth",
                digest=DIGEST,
            )

        accepted = self.evidence(
            source_kind="BODYRIG_MANNERISM",
            domain="embodied",
            trait_id="movement_energy",
            value=0.72,
            confidence=0.93,
            digest=DIGEST,
            source_ref="bodyrig:body-r0003:bodyprint",
        )
        self.assertEqual(accepted.trait_domain, "embodied")
        self.assertEqual(accepted.source_kind, "BODYRIG_MANNERISM")

    def test_bodyrig_requires_immutable_source_digest(self) -> None:
        with self.assertRaises(ValidationError):
            self.evidence(
                source_kind="BODYRIG_MANNERISM",
                domain="embodied",
                trait_id="gesture_amplitude",
                digest=None,
            )

    def test_voicerig_cannot_supply_semantic_traits(self) -> None:
        with self.assertRaises(ValidationError):
            self.evidence(
                source_kind="VOICERIG_DELIVERY",
                domain="semantic",
                trait_id="honesty",
                source_ref="voicerig:kaliv.mrvoice",
            )

    def test_transcript_style_requires_approval_and_digest(self) -> None:
        with self.assertRaises(ValidationError):
            self.evidence(
                source_kind="APPROVED_TRANSCRIPT_STYLE",
                trait_id="playfulness",
            )

        accepted = self.evidence(
            source_kind="APPROVED_TRANSCRIPT_STYLE",
            trait_id="playfulness",
            digest=DIGEST,
            approval="bodyrig:style-approval:1",
            source_ref="bodyrig:style-report:1",
        )
        self.assertEqual(accepted.approval_ref, "bodyrig:style-approval:1")

    def test_duplicate_lineage_counts_once(self) -> None:
        first = self.evidence(suffix="1")
        duplicate = self.evidence(suffix="2")
        model = resolve_personality_model(self.identity(), [first, duplicate])
        self.assertEqual(model.evidence_count, 1)
        directness = next(x for x in model.traits if x.trait_id == "directness")
        self.assertEqual(len(directness.lineage_refs), 1)
        self.assertEqual(len(directness.evidence_ids), 1)

    def test_conflicting_duplicate_lineage_fails_closed(self) -> None:
        first = self.evidence(suffix="1", value=0.80)
        conflict = self.evidence(suffix="2", value=0.20)
        with self.assertRaises(PersonalityResolverError):
            resolve_personality_model(self.identity(), [first, conflict])

    def test_model_keeps_multisource_provenance(self) -> None:
        interaction = self.evidence(
            suffix="1",
            trait_id="directness",
            lineage="interaction-lineage:1",
            source_ref="interaction:1",
        )
        body = self.evidence(
            suffix="2",
            source_kind="BODYRIG_MANNERISM",
            domain="embodied",
            trait_id="movement_energy",
            value=0.72,
            confidence=0.93,
            lineage="body-lineage:1",
            source_ref="bodyrig:body-r0003:bodyprint",
            digest=DIGEST,
        )
        voice = self.evidence(
            suffix="3",
            source_kind="VOICERIG_DELIVERY",
            domain="vocal",
            trait_id="delivery_intensity",
            value=0.61,
            confidence=0.88,
            lineage="voice-lineage:1",
            source_ref="voicerig:kaliv.mrvoice",
        )

        model = resolve_personality_model(
            self.identity(),
            [interaction, body, voice],
        )
        self.assertIsInstance(model, PersonalityModel)
        self.assertEqual(model.evidence_count, 3)
        self.assertIn("interaction:1", model.source_refs)
        self.assertIn("bodyrig:body-r0003:bodyprint", model.source_refs)
        self.assertIn("voicerig:kaliv.mrvoice", model.source_refs)

        embodied = next(
            x for x in model.traits
            if x.trait_domain == "embodied" and x.trait_id == "movement_energy"
        )
        self.assertEqual(embodied.source_kinds, ["BODYRIG_MANNERISM"])

    def test_wrong_person_revision_fails_closed(self) -> None:
        stale = self.evidence(person_revision="person-r0006")
        with self.assertRaises(PersonalityResolverError):
            resolve_personality_model(self.identity(), [stale])

    def test_behaviour_alone_cannot_become_identity_eligible(self) -> None:
        behaviour = self.evidence(
            source_kind="BEHAVIOURAL_EVIDENCE",
            trait_id="playfulness",
            lineage="self-behaviour:1",
            source_ref="consciousness-core:behaviour:1",
        )
        model = resolve_personality_model(self.identity(), [behaviour])
        trait = next(x for x in model.traits if x.trait_id == "playfulness")
        self.assertFalse(trait.promotion_eligible)

    def test_authoritative_semantic_source_is_candidate_eligible_not_activation(self) -> None:
        authored = self.evidence(
            source_kind="OPERATOR_AUTHORED",
            trait_id="playfulness",
            lineage="operator:1",
            source_ref="operator-authored:1",
        )
        model = resolve_personality_model(self.identity(), [authored])
        trait = next(x for x in model.traits if x.trait_id == "playfulness")
        self.assertTrue(trait.promotion_eligible)
        self.assertNotIn("activate", PersonalityModel.model_fields)
        self.assertNotIn("active_person_revision", PersonalityModel.model_fields)

    def test_transient_state_does_not_mutate_identity_or_model(self) -> None:
        identity = self.identity()
        identity_before = identity.model_dump(mode="json")
        model = resolve_personality_model(identity, [])
        model_before = model.model_dump(mode="json")

        modifier = TransientTraitModifier(
            modifier_id="ptm-" + "4" * 32,
            trait_domain="semantic",
            trait_id="directness",
            delta=0.20,
            confidence=0.50,
            source_ref="affect-state:1",
            production_activation=False,
        )
        state = resolve_personality_state(model, [modifier])

        self.assertIsInstance(state, PersonalityState)
        directness = next(x for x in state.traits if x.trait_id == "directness")
        self.assertAlmostEqual(directness.baseline_value, 0.70)
        self.assertAlmostEqual(directness.current_value, 0.80)
        self.assertEqual(identity.model_dump(mode="json"), identity_before)
        self.assertEqual(model.model_dump(mode="json"), model_before)

    def test_unknown_transient_trait_fails_closed(self) -> None:
        model = resolve_personality_model(self.identity(), [])
        modifier = TransientTraitModifier(
            modifier_id="ptm-" + "5" * 32,
            trait_domain="semantic",
            trait_id="invented_trait",
            delta=0.10,
            confidence=1.0,
            source_ref="affect-state:1",
            production_activation=False,
        )
        with self.assertRaises(PersonalityResolverError):
            resolve_personality_state(model, [modifier])

    def test_resolver_is_model_provider_independent(self) -> None:
        signature = inspect.signature(resolve_personality_model)
        self.assertNotIn("model", signature.parameters)
        self.assertNotIn("provider", signature.parameters)
        self.assertNotIn("cognitive_profile", signature.parameters)

        first = resolve_personality_model(self.identity(), [self.evidence()])
        second = resolve_personality_model(self.identity(), [self.evidence()])
        self.assertEqual(first, second)
        self.assertEqual(first.model_id, second.model_id)

    def test_resolver_has_no_activation_execution_or_persistence_imports(self) -> None:
        source = (
            ROOT / "worker" / "app" / "consciousness_core" / "personality.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "import sqlite3",
            "PersonRegistry",
            "activate_person",
            "from ..agent3",
            "MemoryStore",
            "schedule_service",
            "body_session",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
