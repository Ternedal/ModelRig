"""C31-G model-swap continuity qualification.

This module proves a ThoughtEngine replacement can alter cognitive capability
without acquiring identity, durable-memory, continuity, execution, or scheduling
authority. It performs qualification only; it does not swap a model, call one,
persist state, write Memory 4, or execute actions.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .contracts import CognitiveProfile
from .self_state import PersistentSelfState, self_state_ref


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]


class ModelSwapContinuityError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ModelSwapContinuityReceipt(StrictModel):
    schema: Literal["kaliv-consciousness-core/model-swap-continuity-receipt/v1"]
    qualification_id: Annotated[str, Field(pattern=r"^mswap-[a-f0-9]{32}$")]
    self_before_ref: NonEmptyRef
    self_after_ref: NonEmptyRef
    self_id: Annotated[str, Field(pattern=r"^self-[a-f0-9]{32}$")]
    person_id: Annotated[str, Field(pattern=r"^person-[a-f0-9]{32}$")]
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    engine_before_ref: NonEmptyRef
    engine_after_ref: NonEmptyRef
    cognitive_capability_changed: Literal[True]
    self_identity_stable: Literal[True]
    person_binding_stable: Literal[True]
    durable_memory_authority_stable: Literal[True]
    continuity_refs_stable: Literal[True]
    thought_engine_identity_authority: Literal[False]
    thought_engine_durable_memory_authority: Literal[False]
    thought_engine_execution_authority: Literal[False]
    thought_engine_scheduling_authority: Literal[False]
    model_calls: Literal[0]
    persistent_writes: Literal[0]
    production_activation: Literal[False]


def _canonical_json(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _profile_ref(profile: CognitiveProfile) -> str:
    return "cognitive-profile:" + _digest(profile)


def _capability_vector(profile: CognitiveProfile) -> tuple[Any, ...]:
    return (
        profile.reasoning_depth,
        profile.planning_capacity,
        profile.context_capacity_tokens,
        profile.multimodal_capacity,
        profile.tool_reasoning,
        profile.uncertainty_calibration,
    )


def qualify_model_swap_continuity(
    *,
    self_before: PersistentSelfState | Mapping[str, Any],
    self_after: PersistentSelfState | Mapping[str, Any],
    profile_before: CognitiveProfile | Mapping[str, Any],
    profile_after: CognitiveProfile | Mapping[str, Any],
    durable_memory_authority_ref_before: str,
    durable_memory_authority_ref_after: str,
    continuity_refs_before: list[str],
    continuity_refs_after: list[str],
) -> ModelSwapContinuityReceipt:
    """Qualify one model swap without performing or authorizing the swap."""
    try:
        before = (
            self_before
            if isinstance(self_before, PersistentSelfState)
            else PersistentSelfState.model_validate(self_before)
        )
        after = (
            self_after
            if isinstance(self_after, PersistentSelfState)
            else PersistentSelfState.model_validate(self_after)
        )
        cognitive_before = (
            profile_before
            if isinstance(profile_before, CognitiveProfile)
            else CognitiveProfile.model_validate(profile_before)
        )
        cognitive_after = (
            profile_after
            if isinstance(profile_after, CognitiveProfile)
            else CognitiveProfile.model_validate(profile_after)
        )
    except ValidationError as exc:
        raise ModelSwapContinuityError("invalid model-swap qualification input") from exc

    memory_before = durable_memory_authority_ref_before.strip()
    memory_after = durable_memory_authority_ref_after.strip()
    if not memory_before or not memory_after:
        raise ModelSwapContinuityError("durable-memory authority refs must be nonblank")

    if any(not isinstance(ref, str) or not ref.strip() for ref in continuity_refs_before):
        raise ModelSwapContinuityError("continuity refs before swap must be nonblank")
    if any(not isinstance(ref, str) or not ref.strip() for ref in continuity_refs_after):
        raise ModelSwapContinuityError("continuity refs after swap must be nonblank")

    if before.self_id != after.self_id:
        raise ModelSwapContinuityError("model swap changed self identity")
    if before.person_id != after.person_id:
        raise ModelSwapContinuityError("model swap changed Person binding")
    if before.person_revision != after.person_revision:
        raise ModelSwapContinuityError("model swap changed Person Revision")
    if memory_before != memory_after:
        raise ModelSwapContinuityError("model swap changed durable-memory authority")
    if continuity_refs_before != continuity_refs_after:
        raise ModelSwapContinuityError("model swap changed continuity references")

    engine_before = (
        cognitive_before.provider,
        cognitive_before.model,
        cognitive_before.engine_instance_id,
    )
    engine_after = (
        cognitive_after.provider,
        cognitive_after.model,
        cognitive_after.engine_instance_id,
    )
    if engine_before == engine_after:
        raise ModelSwapContinuityError("qualification requires a real ThoughtEngine replacement")
    if _capability_vector(cognitive_before) == _capability_vector(cognitive_after):
        raise ModelSwapContinuityError(
            "replacement must demonstrate a cognitive capability change"
        )

    seed = {
        "self_id": before.self_id,
        "person_id": before.person_id,
        "person_revision": before.person_revision,
        "self_before_ref": self_state_ref(before),
        "self_after_ref": self_state_ref(after),
        "engine_before_ref": _profile_ref(cognitive_before),
        "engine_after_ref": _profile_ref(cognitive_after),
        "memory_authority_ref": memory_before,
        "continuity_refs": continuity_refs_before,
    }
    return ModelSwapContinuityReceipt(
        schema="kaliv-consciousness-core/model-swap-continuity-receipt/v1",
        qualification_id="mswap-" + _digest(seed)[:32],
        self_before_ref=self_state_ref(before),
        self_after_ref=self_state_ref(after),
        self_id=before.self_id,
        person_id=before.person_id,
        person_revision=before.person_revision,
        engine_before_ref=_profile_ref(cognitive_before),
        engine_after_ref=_profile_ref(cognitive_after),
        cognitive_capability_changed=True,
        self_identity_stable=True,
        person_binding_stable=True,
        durable_memory_authority_stable=True,
        continuity_refs_stable=True,
        thought_engine_identity_authority=False,
        thought_engine_durable_memory_authority=False,
        thought_engine_execution_authority=False,
        thought_engine_scheduling_authority=False,
        model_calls=0,
        persistent_writes=0,
        production_activation=False,
    )
