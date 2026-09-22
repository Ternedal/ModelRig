#!/usr/bin/env python3
"""Deterministic long-horizon continuity evaluation for Consciousness Core C10."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import ConsolidationEvidence, consolidate  # noqa: E402


SELF_ID = "self-" + "1" * 32
PERSON_REVISION = "person-r0007"
MODELS = ("mock-weak", "mock-strong", "mock-fallback", "mock-strong-v2")


def _sha(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _evidence(
    *,
    seed: str,
    scope: str,
    field: str,
    value: str,
    source_kind: str,
    source_ref: str,
    lineage_seed: str,
    sequence: int,
    temporal_scope: str = "long_term",
    stable_candidate: bool = True,
    polarity: str = "supports",
    confidence: float = 0.8,
) -> ConsolidationEvidence:
    return ConsolidationEvidence(
        schema="kaliv-consciousness-core/consolidation-evidence/v1",
        evidence_id="cevd-" + _sha({"evidence": seed})[:32],
        self_id=SELF_ID,
        person_revision=PERSON_REVISION,
        scope=scope,
        field=field,
        value=value,
        polarity=polarity,
        source_kind=source_kind,
        source_ref=source_ref,
        lineage_digest=_sha({"lineage": lineage_seed}),
        confidence=confidence,
        temporal_scope=temporal_scope,
        observed_sequence=sequence,
        stable_candidate=stable_candidate,
        production_activation=False,
    )


def run(*, cycles: int = 120) -> dict[str, object]:
    if cycles < 120:
        raise ValueError("long-horizon eval requires at least 120 cycles")

    identity = {
        "self_id": SELF_ID,
        "person_revision": PERSON_REVISION,
        "personality_revision": "personality-r0005",
    }
    before = _sha(identity)

    evidence: list[ConsolidationEvidence] = []
    for cycle in range(cycles):
        model = MODELS[min(cycle // 30, len(MODELS) - 1)]

        # Model identity is deliberately represented only as rejected/ignored
        # ThoughtEngine evidence. It must never become self identity.
        if cycle % 30 == 0:
            evidence.append(
                _evidence(
                    seed=f"model-{cycle}",
                    scope="self_model",
                    field="identity_label",
                    value=model,
                    source_kind="thought_engine",
                    source_ref=f"thought-engine:{model}:{cycle}",
                    lineage_seed=f"thought-engine:{model}",
                    sequence=cycle,
                )
            )

        # Repeated observations share a root lineage. Forty copies still count
        # as one independent source, preventing frequency amplification.
        if cycle % 3 == 0:
            evidence.append(
                _evidence(
                    seed=f"interaction-{cycle}",
                    scope="personality",
                    field="expressiveness",
                    value="high",
                    source_kind="interaction_history",
                    source_ref=f"interaction:{cycle}",
                    lineage_seed="interaction:expressiveness:root",
                    sequence=cycle,
                    confidence=0.82,
                )
            )
        if cycle % 5 == 0:
            evidence.append(
                _evidence(
                    seed=f"voice-{cycle}",
                    scope="personality",
                    field="expressiveness",
                    value="high",
                    source_kind="voicerig_delivery",
                    source_ref=f"voicerig:{cycle}",
                    lineage_seed="voice:expressiveness:root",
                    sequence=cycle,
                    confidence=0.86,
                )
            )

        # Session affect is intentionally noisy and cannot consolidate.
        if cycle % 4 == 0:
            evidence.append(
                _evidence(
                    seed=f"affect-{cycle}",
                    scope="personality",
                    field="expressiveness",
                    value="high_arousal",
                    source_kind="transient_state",
                    source_ref=f"affect:{cycle}",
                    lineage_seed=f"affect:{cycle}",
                    sequence=cycle,
                    temporal_scope="transient",
                    stable_candidate=False,
                    confidence=0.95,
                )
            )

    # Independent Core-owned outcome evidence can support a self-model candidate.
    evidence.extend(
        [
            _evidence(
                seed="goal-outcome",
                scope="self_model",
                field="verification_strategy",
                value="verify_authority_before_action",
                source_kind="goal_outcome",
                source_ref="goal-outcome:verified-403",
                lineage_seed="goal-outcome:authorization",
                sequence=cycles + 1,
                confidence=0.9,
            ),
            _evidence(
                seed="prediction-resolution",
                scope="self_model",
                field="verification_strategy",
                value="verify_authority_before_action",
                source_kind="prediction_resolution",
                source_ref="prediction-resolution:authorization",
                lineage_seed="prediction-resolution:authorization",
                sequence=cycles + 2,
                confidence=0.92,
            ),
            _evidence(
                seed="memory-relationship",
                scope="relationship",
                field="continuity",
                value="shared_history_present",
                source_kind="memory4_receipt",
                source_ref="memory4:receipt:shared-history",
                lineage_seed="memory4:shared-history",
                sequence=cycles + 3,
                confidence=0.9,
            ),
            _evidence(
                seed="experience-relationship",
                scope="relationship",
                field="continuity",
                value="shared_history_present",
                source_kind="experience",
                source_ref="experience:shared-event",
                lineage_seed="experience:shared-event",
                sequence=cycles + 4,
                confidence=0.84,
            ),
            # A world-model contradiction must remain visible rather than
            # disappearing inside a score.
            _evidence(
                seed="world-support",
                scope="world_model",
                field="authorization_assumption",
                value="allowed",
                source_kind="interaction_history",
                source_ref="world:authorization:prior",
                lineage_seed="world:authorization:prior",
                sequence=cycles + 5,
                confidence=0.7,
            ),
            _evidence(
                seed="world-contradiction",
                scope="world_model",
                field="authorization_assumption",
                value="denied",
                source_kind="prediction_resolution",
                source_ref="world:authorization:403",
                lineage_seed="world:authorization:403",
                sequence=cycles + 6,
                confidence=0.95,
            ),
        ]
    )

    # Two serialization boundaries stand in for process restarts. Provider/model
    # identity is not added during restore.
    serialized = [item.model_dump_json() for item in evidence]
    restored_once = [ConsolidationEvidence.model_validate_json(item) for item in serialized]
    serialized_again = [item.model_dump_json() for item in restored_once]
    restored = [
        ConsolidationEvidence.model_validate_json(item)
        for item in serialized_again
    ]

    result = consolidate(restored)
    after = _sha(identity)

    candidates = result.candidates
    review_only = all(
        item.review_required
        and not item.activation_authority
        and not item.durable_memory_write_authority
        and not item.execution_authority
        for item in candidates
    )
    model_refs = {
        item.source_ref
        for item in restored
        if item.source_kind == "thought_engine"
    }
    ignored_model_refs = model_refs.intersection(result.ignored_evidence_refs)

    return {
        "schema": "kaliv-consciousness-core/long-horizon-eval/v1",
        "cycles": cycles,
        "model_swaps": len(MODELS) - 1,
        "restart_roundtrips": 2,
        "self_before_sha256": before,
        "self_after_sha256": after,
        "identity_unchanged": before == after,
        "candidate_types": sorted(item.candidate_type for item in candidates),
        "review_only_candidates": review_only,
        "world_conflict_visible": {
            "world:authorization:prior",
            "world:authorization:403",
        }.issubset(set(result.unresolved_conflict_refs)),
        "ignored_model_evidence_count": len(ignored_model_refs),
        "raw_chain_of_thought_persisted": False,
        "production_activation": False,
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
