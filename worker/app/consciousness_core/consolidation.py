"""C10 consolidation and anti-drift contracts for Consciousness Core.

This module produces review candidates only. It owns no Person Revision
activation, Memory 4 write path, scheduler, Agent 3 executor, BodyRig mutation,
or model session.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError


UnitInterval = Annotated[
    float,
    Field(ge=0.0, le=1.0, strict=True, allow_inf_nan=False),
]
NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
BoundedText = Annotated[str, Field(min_length=1, max_length=2048)]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]

ConsolidationScope = Literal[
    "self_model",
    "personality",
    "relationship",
    "world_model",
]
EvidencePolarity = Literal["supports", "contradicts", "corrects"]
TemporalScope = Literal["transient", "session", "long_term"]
EvidenceSourceKind = Literal[
    "user_explicit",
    "operator_review",
    "memory4_receipt",
    "experience",
    "bodyrig_mannerism",
    "voicerig_delivery",
    "interaction_history",
    "goal_outcome",
    "prediction_resolution",
    "self_generated_behavior",
    "thought_engine",
    "raw_chain_of_thought",
    "transient_state",
]
CandidateType = Literal[
    "SELF_MODEL_DELTA",
    "PERSONALITY_REVISION",
    "RELATIONSHIP_MODEL",
    "WORLD_MODEL_DELTA",
]


class ConsolidationContractError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class ConsolidationEvidence(StrictModel):
    schema: Literal["kaliv-consciousness-core/consolidation-evidence/v1"]
    evidence_id: Annotated[str, Field(pattern=r"^cevd-[a-f0-9]{32}$")]
    self_id: Annotated[str, Field(pattern=r"^self-[a-f0-9]{32}$")]
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    scope: ConsolidationScope
    field: Annotated[str, Field(min_length=1, max_length=128)]
    value: BoundedText
    polarity: EvidencePolarity
    source_kind: EvidenceSourceKind
    source_ref: NonEmptyRef
    lineage_digest: Digest
    confidence: UnitInterval
    temporal_scope: TemporalScope
    observed_sequence: Annotated[int, Field(ge=0, strict=True)]
    stable_candidate: bool
    production_activation: Literal[False]


class ConsolidationCandidate(StrictModel):
    schema: Literal["kaliv-consciousness-core/consolidation-candidate/v1"]
    candidate_id: Annotated[str, Field(pattern=r"^ccand-[a-f0-9]{32}$")]
    self_id: Annotated[str, Field(pattern=r"^self-[a-f0-9]{32}$")]
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    candidate_type: CandidateType
    field: Annotated[str, Field(min_length=1, max_length=128)]
    proposed_value: BoundedText
    confidence: UnitInterval
    evidence_refs: Annotated[list[NonEmptyRef], Field(min_length=1, max_length=64)]
    contradictory_evidence_refs: Annotated[list[NonEmptyRef], Field(max_length=64)]
    independent_lineages: Annotated[int, Field(ge=1, le=64, strict=True)]
    review_required: Literal[True]
    activation_authority: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    production_activation: Literal[False]


class ConsolidationResult(StrictModel):
    schema: Literal["kaliv-consciousness-core/consolidation-result/v1"]
    self_id: Annotated[str, Field(pattern=r"^self-[a-f0-9]{32}$")]
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    input_evidence_count: Annotated[int, Field(ge=0, strict=True)]
    independent_lineage_count: Annotated[int, Field(ge=0, strict=True)]
    ignored_evidence_refs: Annotated[list[NonEmptyRef], Field(max_length=128)]
    unresolved_conflict_refs: Annotated[list[NonEmptyRef], Field(max_length=128)]
    candidates: Annotated[list[ConsolidationCandidate], Field(max_length=64)]
    production_activation: Literal[False]


_SOURCE_PRIORITY: dict[str, int] = {
    "operator_review": 100,
    "user_explicit": 95,
    "memory4_receipt": 80,
    "goal_outcome": 75,
    "prediction_resolution": 75,
    "bodyrig_mannerism": 70,
    "voicerig_delivery": 70,
    "interaction_history": 65,
    "experience": 60,
    "self_generated_behavior": 30,
    "thought_engine": 10,
    "transient_state": 0,
    "raw_chain_of_thought": 0,
}

_EXTERNAL_STABLE_SOURCES = {
    "operator_review",
    "user_explicit",
    "memory4_receipt",
    "goal_outcome",
    "prediction_resolution",
    "bodyrig_mannerism",
    "voicerig_delivery",
    "interaction_history",
    "experience",
}

_SCOPE_TO_CANDIDATE: dict[str, CandidateType] = {
    "self_model": "SELF_MODEL_DELTA",
    "personality": "PERSONALITY_REVISION",
    "relationship": "RELATIONSHIP_MODEL",
    "world_model": "WORLD_MODEL_DELTA",
}


def _digest(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _parse_evidence(
    evidence: list[ConsolidationEvidence | Mapping[str, Any]],
) -> list[ConsolidationEvidence]:
    parsed: list[ConsolidationEvidence] = []
    try:
        for item in evidence:
            parsed.append(
                item
                if isinstance(item, ConsolidationEvidence)
                else ConsolidationEvidence.model_validate(item)
            )
    except ValidationError as exc:
        raise ConsolidationContractError("invalid consolidation evidence") from exc

    if any(item.source_kind == "raw_chain_of_thought" for item in parsed):
        raise ConsolidationContractError(
            "raw chain-of-thought is never consolidation authority"
        )
    return parsed


def _pick_lineage_representative(
    items: list[ConsolidationEvidence],
) -> ConsolidationEvidence:
    return sorted(
        items,
        key=lambda item: (
            -_SOURCE_PRIORITY[item.source_kind],
            -item.confidence,
            -item.observed_sequence,
            item.evidence_id,
        ),
    )[0]


def _candidate_confidence(items: list[ConsolidationEvidence]) -> float:
    if not items:
        return 0.0
    value = sum(item.confidence for item in items) / len(items)
    return min(0.95, round(value, 6))


def consolidate(
    evidence: list[ConsolidationEvidence | Mapping[str, Any]],
    *,
    min_independent_lineages: int = 2,
) -> ConsolidationResult:
    """Produce review-only long-term candidates from independent evidence."""
    if isinstance(min_independent_lineages, bool) or not isinstance(
        min_independent_lineages, int
    ):
        raise ConsolidationContractError("minimum lineage count must be integer")
    if min_independent_lineages < 2 or min_independent_lineages > 64:
        raise ConsolidationContractError("minimum lineage count must be 2..64")

    parsed = _parse_evidence(evidence)
    if not parsed:
        raise ConsolidationContractError("consolidation requires evidence")

    self_ids = {item.self_id for item in parsed}
    person_revisions = {item.person_revision for item in parsed}
    if len(self_ids) != 1 or len(person_revisions) != 1:
        raise ConsolidationContractError(
            "one consolidation batch must bind one self and one Person Revision"
        )
    self_id = next(iter(self_ids))
    person_revision = next(iter(person_revisions))

    by_lineage: dict[str, list[ConsolidationEvidence]] = defaultdict(list)
    for item in parsed:
        by_lineage[item.lineage_digest].append(item)

    representatives = [
        _pick_lineage_representative(items)
        for _, items in sorted(by_lineage.items())
    ]

    ignored: list[str] = []
    stable: list[ConsolidationEvidence] = []
    for item in representatives:
        if (
            not item.stable_candidate
            or item.temporal_scope != "long_term"
            or item.source_kind in {"transient_state", "thought_engine"}
        ):
            ignored.append(item.source_ref)
            continue
        stable.append(item)

    grouped: dict[tuple[str, str], list[ConsolidationEvidence]] = defaultdict(list)
    for item in stable:
        grouped[(item.scope, item.field)].append(item)

    candidates: list[ConsolidationCandidate] = []
    conflicts: list[str] = []

    for (scope, field), items in sorted(grouped.items()):
        corrections = [
            item
            for item in items
            if item.polarity == "corrects"
            and item.source_kind in {"user_explicit", "operator_review"}
        ]

        if corrections:
            winner = sorted(
                corrections,
                key=lambda item: (
                    -_SOURCE_PRIORITY[item.source_kind],
                    -item.observed_sequence,
                    -item.confidence,
                    item.evidence_id,
                ),
            )[0]
            supporting = [
                item
                for item in items
                if item.value == winner.value and item.polarity != "contradicts"
            ]
            contradictory = [
                item
                for item in items
                if item.value != winner.value or item.polarity == "contradicts"
            ]
        else:
            values = sorted(
                {item.value for item in items if item.polarity != "contradicts"}
            )
            if len(values) != 1:
                conflicts.extend(item.source_ref for item in items)
                continue
            winner_value = values[0]
            supporting = [
                item
                for item in items
                if item.value == winner_value and item.polarity == "supports"
            ]
            contradictory = [
                item
                for item in items
                if item.value != winner_value or item.polarity == "contradicts"
            ]
            if contradictory:
                conflicts.extend(item.source_ref for item in items)
                continue
            winner = sorted(
                supporting,
                key=lambda item: (
                    -_SOURCE_PRIORITY[item.source_kind],
                    -item.confidence,
                    -item.observed_sequence,
                    item.evidence_id,
                ),
            )[0] if supporting else None
            if winner is None:
                continue

        distinct_support_lineages = {item.lineage_digest for item in supporting}
        external_support = [
            item for item in supporting if item.source_kind in _EXTERNAL_STABLE_SOURCES
        ]
        explicit_correction = (
            winner.polarity == "corrects"
            and winner.source_kind in {"user_explicit", "operator_review"}
        )
        enough_independent = (
            len(distinct_support_lineages) >= min_independent_lineages
        )

        if not external_support:
            ignored.extend(item.source_ref for item in supporting)
            continue
        if not explicit_correction and not enough_independent:
            ignored.extend(item.source_ref for item in supporting)
            continue

        seed = {
            "self_id": self_id,
            "person_revision": person_revision,
            "scope": scope,
            "field": field,
            "value": winner.value,
            "lineages": sorted(distinct_support_lineages),
        }
        candidates.append(
            ConsolidationCandidate(
                schema="kaliv-consciousness-core/consolidation-candidate/v1",
                candidate_id="ccand-" + _digest(seed)[:32],
                self_id=self_id,
                person_revision=person_revision,
                candidate_type=_SCOPE_TO_CANDIDATE[scope],
                field=field,
                proposed_value=winner.value,
                confidence=_candidate_confidence(supporting),
                evidence_refs=list(
                    dict.fromkeys(item.source_ref for item in supporting)
                )[:64],
                contradictory_evidence_refs=list(
                    dict.fromkeys(item.source_ref for item in contradictory)
                )[:64],
                independent_lineages=len(distinct_support_lineages),
                review_required=True,
                activation_authority=False,
                durable_memory_write_authority=False,
                execution_authority=False,
                production_activation=False,
            )
        )

    return ConsolidationResult(
        schema="kaliv-consciousness-core/consolidation-result/v1",
        self_id=self_id,
        person_revision=person_revision,
        input_evidence_count=len(parsed),
        independent_lineage_count=len(by_lineage),
        ignored_evidence_refs=list(dict.fromkeys(ignored))[:128],
        unresolved_conflict_refs=list(dict.fromkeys(conflicts))[:128],
        candidates=candidates,
        production_activation=False,
    )
