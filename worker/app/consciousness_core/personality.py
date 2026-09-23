"""C6 multi-source Personality Resolver for Consciousness Core.

The resolver composes auditable personality evidence into a non-authoritative
PersonalityModel and a transient PersonalityState. It cannot create or activate
a ModelRig personality/person revision.

BodyRig is deliberately constrained to embodied mannerism evidence. It cannot
author semantic/psychological traits merely because a body/video observation
exists.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


UnitInterval = Annotated[
    float,
    Field(ge=0.0, le=1.0, strict=True, allow_inf_nan=False),
]
SignedUnit = Annotated[
    float,
    Field(ge=-1.0, le=1.0, strict=True, allow_inf_nan=False),
]
NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
TraitId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]

TraitDomain = Literal["semantic", "embodied", "vocal"]
EvidenceSourceKind = Literal[
    "PERSON_REVISION",
    "BODYRIG_MANNERISM",
    "VOICERIG_DELIVERY",
    "APPROVED_TRANSCRIPT_STYLE",
    "INTERACTION_HISTORY",
    "BEHAVIOURAL_EVIDENCE",
    "OPERATOR_AUTHORED",
]


class PersonalityResolverError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class IdentityTrait(StrictModel):
    trait_id: TraitId
    value: UnitInterval
    source_ref: NonEmptyRef


class PersonalityIdentitySnapshot(StrictModel):
    """Reviewed active semantic personality; never mutated by this resolver."""

    schema: Literal["kaliv-consciousness-core/personality-identity-snapshot/v1"]
    person_id: Annotated[str, Field(pattern=r"^person-[a-f0-9]{32}$")]
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    personality_revision: Annotated[
        str,
        Field(pattern=r"^personality-r[0-9]{4,}$"),
    ]
    semantic_traits: Annotated[list[IdentityTrait], Field(max_length=128)]
    source_refs: Annotated[list[NonEmptyRef], Field(min_length=1, max_length=32)]
    production_activation: Literal[False]


class PersonalityEvidence(StrictModel):
    schema: Literal["kaliv-consciousness-core/personality-evidence/v1"]
    evidence_id: Annotated[str, Field(pattern=r"^pe-[a-f0-9]{32}$")]
    person_id: Annotated[str, Field(pattern=r"^person-[a-f0-9]{32}$")]
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    source_kind: EvidenceSourceKind
    trait_domain: TraitDomain
    trait_id: TraitId
    value: UnitInterval
    confidence: UnitInterval
    lineage_ref: NonEmptyRef
    source_ref: NonEmptyRef
    immutable_digest: Digest | None = None
    approval_ref: NonEmptyRef | None = None
    production_activation: Literal[False]

    @model_validator(mode="after")
    def enforce_source_domain(self) -> "PersonalityEvidence":
        if self.source_kind == "BODYRIG_MANNERISM":
            if self.trait_domain != "embodied":
                raise ValueError(
                    "BodyRig mannerism evidence may only populate embodied traits"
                )
            if self.immutable_digest is None:
                raise ValueError(
                    "BodyRig mannerism evidence requires immutable source digest"
                )
        elif self.source_kind == "VOICERIG_DELIVERY":
            if self.trait_domain != "vocal":
                raise ValueError(
                    "VoiceRig delivery evidence may only populate vocal traits"
                )
        elif self.source_kind in {
            "PERSON_REVISION",
            "APPROVED_TRANSCRIPT_STYLE",
            "INTERACTION_HISTORY",
            "BEHAVIOURAL_EVIDENCE",
            "OPERATOR_AUTHORED",
        }:
            if self.trait_domain != "semantic":
                raise ValueError(
                    f"{self.source_kind} evidence may only populate semantic traits"
                )

        if self.source_kind == "APPROVED_TRANSCRIPT_STYLE":
            if self.approval_ref is None or self.immutable_digest is None:
                raise ValueError(
                    "approved transcript style requires approval and immutable digest"
                )
        return self


class ResolvedTrait(StrictModel):
    trait_domain: TraitDomain
    trait_id: TraitId
    resolved_value: UnitInterval
    confidence: UnitInterval
    identity_baseline_value: UnitInterval | None
    evidence_ids: Annotated[list[str], Field(max_length=128)]
    source_kinds: Annotated[list[EvidenceSourceKind], Field(max_length=16)]
    lineage_refs: Annotated[list[NonEmptyRef], Field(max_length=128)]
    promotion_eligible: bool


class PersonalityModel(StrictModel):
    schema: Literal["kaliv-consciousness-core/personality-model/v1"]
    model_id: Annotated[str, Field(pattern=r"^pmodel-[a-f0-9]{32}$")]
    person_id: Annotated[str, Field(pattern=r"^person-[a-f0-9]{32}$")]
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    personality_revision: Annotated[
        str,
        Field(pattern=r"^personality-r[0-9]{4,}$"),
    ]
    traits: Annotated[list[ResolvedTrait], Field(max_length=256)]
    evidence_count: Annotated[int, Field(ge=0, strict=True)]
    source_refs: Annotated[list[NonEmptyRef], Field(min_length=1, max_length=256)]
    production_activation: Literal[False]


class TransientTraitModifier(StrictModel):
    modifier_id: Annotated[str, Field(pattern=r"^ptm-[a-f0-9]{32}$")]
    trait_domain: TraitDomain
    trait_id: TraitId
    delta: SignedUnit
    confidence: UnitInterval
    source_ref: NonEmptyRef
    production_activation: Literal[False]


class PersonalityStateTrait(StrictModel):
    trait_domain: TraitDomain
    trait_id: TraitId
    baseline_value: UnitInterval
    current_value: UnitInterval
    applied_modifier_refs: Annotated[list[NonEmptyRef], Field(max_length=32)]


class PersonalityState(StrictModel):
    schema: Literal["kaliv-consciousness-core/personality-state/v1"]
    state_id: Annotated[str, Field(pattern=r"^pstate-[a-f0-9]{32}$")]
    revision: Annotated[int, Field(ge=1, strict=True)]
    personality_model_ref: NonEmptyRef
    traits: Annotated[list[PersonalityStateTrait], Field(max_length=256)]
    production_activation: Literal[False]


def _digest(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _unique(values: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
        if len(out) >= limit:
            break
    return out


def _evidence_fingerprint(item: PersonalityEvidence) -> tuple[Any, ...]:
    return (
        item.person_id,
        item.person_revision,
        item.source_kind,
        item.trait_domain,
        item.trait_id,
        item.value,
        item.confidence,
        item.lineage_ref,
        item.source_ref,
        item.immutable_digest,
        item.approval_ref,
    )


def _deduplicate_lineage(
    evidence: list[PersonalityEvidence],
) -> list[PersonalityEvidence]:
    """Same root lineage counts once; conflicting copies fail closed."""
    by_lineage: dict[tuple[str, str, str], PersonalityEvidence] = {}
    for item in sorted(evidence, key=lambda x: x.evidence_id):
        key = (item.trait_domain, item.trait_id, item.lineage_ref)
        previous = by_lineage.get(key)
        if previous is None:
            by_lineage[key] = item
            continue
        if _evidence_fingerprint(previous) != _evidence_fingerprint(item):
            raise PersonalityResolverError(
                "conflicting personality evidence shares one lineage"
            )
    return list(by_lineage.values())


def resolve_personality_model(
    identity: PersonalityIdentitySnapshot | Mapping[str, Any],
    evidence: list[PersonalityEvidence | Mapping[str, Any]],
) -> PersonalityModel:
    """Resolve a deterministic, provenance-preserving non-authoritative model."""
    try:
        base = (
            identity
            if isinstance(identity, PersonalityIdentitySnapshot)
            else PersonalityIdentitySnapshot.model_validate(identity)
        )
        parsed = [
            item
            if isinstance(item, PersonalityEvidence)
            else PersonalityEvidence.model_validate(item)
            for item in evidence
        ]
    except ValidationError as exc:
        raise PersonalityResolverError("invalid personality resolver input") from exc

    for item in parsed:
        if item.person_id != base.person_id:
            raise PersonalityResolverError("personality evidence belongs to another person")
        if item.person_revision != base.person_revision:
            raise PersonalityResolverError(
                "personality evidence is not bound to the active Person Revision"
            )

    parsed = _deduplicate_lineage(parsed)

    baseline: dict[tuple[str, str], IdentityTrait] = {
        ("semantic", trait.trait_id): trait
        for trait in base.semantic_traits
    }
    grouped: dict[tuple[str, str], list[PersonalityEvidence]] = defaultdict(list)
    for item in parsed:
        grouped[(item.trait_domain, item.trait_id)].append(item)

    trait_keys = sorted(set(baseline) | set(grouped))
    resolved: list[ResolvedTrait] = []
    authoritative_semantic_sources = {
        "PERSON_REVISION",
        "APPROVED_TRANSCRIPT_STYLE",
        "OPERATOR_AUTHORED",
    }

    for domain, trait_id in trait_keys:
        base_trait = baseline.get((domain, trait_id))
        items = sorted(grouped.get((domain, trait_id), []), key=lambda x: x.evidence_id)

        weighted_sum = 0.0
        total_weight = 0.0
        if base_trait is not None:
            weighted_sum += base_trait.value
            total_weight += 1.0

        for item in items:
            if item.confidence > 0.0:
                weighted_sum += item.value * item.confidence
                total_weight += item.confidence

        if total_weight <= 0.0:
            raise PersonalityResolverError(
                f"trait {domain}:{trait_id} has no usable confidence"
            )

        value = min(1.0, max(0.0, weighted_sum / total_weight))
        confidences = [item.confidence for item in items]
        if base_trait is not None:
            confidences.append(1.0)
        confidence = max(confidences) if confidences else 0.0

        source_kinds = sorted({item.source_kind for item in items})
        promotion_eligible = (
            domain == "semantic"
            and (
                base_trait is not None
                or any(
                    item.source_kind in authoritative_semantic_sources
                    for item in items
                )
            )
        )
        resolved.append(
            ResolvedTrait(
                trait_domain=domain,
                trait_id=trait_id,
                resolved_value=value,
                confidence=confidence,
                identity_baseline_value=(
                    base_trait.value if base_trait is not None else None
                ),
                evidence_ids=[item.evidence_id for item in items],
                source_kinds=source_kinds,
                lineage_refs=_unique([item.lineage_ref for item in items], 128),
                promotion_eligible=promotion_eligible,
            )
        )

    model_seed = {
        "person_id": base.person_id,
        "person_revision": base.person_revision,
        "personality_revision": base.personality_revision,
        "traits": [
            trait.model_dump(mode="json")
            for trait in resolved
        ],
    }
    source_refs = _unique(
        [
            *base.source_refs,
            *[item.source_ref for item in parsed],
        ],
        256,
    )
    return PersonalityModel(
        schema="kaliv-consciousness-core/personality-model/v1",
        model_id="pmodel-" + _digest(model_seed)[:32],
        person_id=base.person_id,
        person_revision=base.person_revision,
        personality_revision=base.personality_revision,
        traits=resolved,
        evidence_count=len(parsed),
        source_refs=source_refs,
        production_activation=False,
    )


def resolve_personality_state(
    model: PersonalityModel | Mapping[str, Any],
    modifiers: list[TransientTraitModifier | Mapping[str, Any]],
    *,
    revision: int = 1,
) -> PersonalityState:
    """Apply transient modifiers without changing PersonalityModel/Identity."""
    try:
        resolved_model = (
            model
            if isinstance(model, PersonalityModel)
            else PersonalityModel.model_validate(model)
        )
        parsed_modifiers = [
            item
            if isinstance(item, TransientTraitModifier)
            else TransientTraitModifier.model_validate(item)
            for item in modifiers
        ]
    except ValidationError as exc:
        raise PersonalityResolverError("invalid personality state input") from exc

    by_trait = {
        (trait.trait_domain, trait.trait_id): trait
        for trait in resolved_model.traits
    }
    mods: dict[tuple[str, str], list[TransientTraitModifier]] = defaultdict(list)
    for item in parsed_modifiers:
        key = (item.trait_domain, item.trait_id)
        if key not in by_trait:
            raise PersonalityResolverError(
                "transient modifier references unknown personality trait"
            )
        mods[key].append(item)

    state_traits: list[PersonalityStateTrait] = []
    for key in sorted(by_trait):
        trait = by_trait[key]
        items = sorted(mods.get(key, []), key=lambda x: x.modifier_id)
        delta = sum(item.delta * item.confidence for item in items)
        current = min(1.0, max(0.0, trait.resolved_value + delta))
        state_traits.append(
            PersonalityStateTrait(
                trait_domain=trait.trait_domain,
                trait_id=trait.trait_id,
                baseline_value=trait.resolved_value,
                current_value=current,
                applied_modifier_refs=[
                    f"personality-modifier:{item.modifier_id}"
                    for item in items
                ],
            )
        )

    state_seed = {
        "model_id": resolved_model.model_id,
        "revision": revision,
        "modifiers": [
            item.model_dump(mode="json")
            for item in sorted(parsed_modifiers, key=lambda x: x.modifier_id)
        ],
    }
    return PersonalityState(
        schema="kaliv-consciousness-core/personality-state/v1",
        state_id="pstate-" + _digest(state_seed)[:32],
        revision=revision,
        personality_model_ref=f"personality-model:{resolved_model.model_id}",
        traits=state_traits,
        production_activation=False,
    )
