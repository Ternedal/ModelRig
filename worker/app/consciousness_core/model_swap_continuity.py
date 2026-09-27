"""C31-G model-swap continuity qualification contract.

A ThoughtEngine/CognitiveProfile may change cognitive capability without becoming
identity, SelfState, Person/Profile, Memory4, continuity, or execution authority.

The qualifier is evidence-based: callers must provide independently bound
pre-swap and post-swap SelfState + lived-continuity receipts.  A receipt is only
issued when the model/profile changed while the authoritative SelfState stayed
byte-for-byte equivalent under the repository's canonical reference function.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .contracts import CognitiveProfile
from .lived_continuity import LivedContinuityReceipt
from .self_state import PersistentSelfState, self_state_ref


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]


class ModelSwapContinuityError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ModelSwapContinuityReceipt(StrictModel):
    schema: Literal["kaliv-consciousness-core/model-swap-continuity-receipt/v1"]
    qualification_id: Annotated[str, Field(pattern=r"^model-swap-[a-f0-9]{32}$")]
    from_cognitive_profile_ref: NonEmptyRef
    to_cognitive_profile_ref: NonEmptyRef
    cognitive_profile_changed: Literal[True]
    cognitive_capability_changed: bool
    self_id: Annotated[str, Field(pattern=r"^self-[a-f0-9]{32}$")]
    person_id: Annotated[str, Field(pattern=r"^person-[a-f0-9]{32}$")]
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    self_state_ref: NonEmptyRef
    before_continuity_ref: NonEmptyRef
    after_continuity_ref: NonEmptyRef
    personality_state_ref: NonEmptyRef
    durable_memory_binding_ref: NonEmptyRef | None
    identity_preserved: Literal[True]
    person_binding_preserved: Literal[True]
    self_state_preserved: Literal[True]
    durable_memory_binding_preserved: Literal[True]
    continuity_preserved: Literal[True]
    raw_chain_of_thought_persisted: Literal[False]
    identity_authority: Literal[False]
    persistent_state_authority: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    model_authority: Literal[False]
    production_activation: Literal[False]


def _json(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _ref(kind: str, value: Any) -> str:
    return kind + ":" + hashlib.sha256(_json(value)).hexdigest()


def _profile(value: CognitiveProfile | Mapping[str, Any]) -> CognitiveProfile:
    return value if isinstance(value, CognitiveProfile) else CognitiveProfile.model_validate(value)


def _state(value: PersistentSelfState | Mapping[str, Any]) -> PersistentSelfState:
    return value if isinstance(value, PersistentSelfState) else PersistentSelfState.model_validate(value)


def _continuity(
    value: LivedContinuityReceipt | Mapping[str, Any],
) -> LivedContinuityReceipt:
    return (
        value
        if isinstance(value, LivedContinuityReceipt)
        else LivedContinuityReceipt.model_validate(value)
    )


def _assert_bound(
    state: PersistentSelfState,
    continuity: LivedContinuityReceipt,
    *,
    phase: str,
) -> None:
    if (
        continuity.self_id != state.self_id
        or continuity.person_revision != state.person_revision
    ):
        raise ModelSwapContinuityError(
            f"{phase} continuity does not belong to supplied SelfState"
        )
    if continuity.self_state_ref != self_state_ref(state):
        raise ModelSwapContinuityError(
            f"{phase} continuity is not bound to exact supplied SelfState"
        )


def qualify_model_swap_continuity(
    *,
    before_profile: CognitiveProfile | Mapping[str, Any],
    after_profile: CognitiveProfile | Mapping[str, Any],
    before_self_state: PersistentSelfState | Mapping[str, Any],
    after_self_state: PersistentSelfState | Mapping[str, Any],
    before_continuity: LivedContinuityReceipt | Mapping[str, Any],
    after_continuity: LivedContinuityReceipt | Mapping[str, Any],
) -> ModelSwapContinuityReceipt:
    """Qualify a model/profile swap without granting it persistent authority."""
    try:
        before = _profile(before_profile)
        after = _profile(after_profile)
        before_state = _state(before_self_state)
        after_state = _state(after_self_state)
        before_lived = _continuity(before_continuity)
        after_lived = _continuity(after_continuity)
    except ValidationError as exc:
        raise ModelSwapContinuityError("invalid model-swap qualification input") from exc

    if before == after:
        raise ModelSwapContinuityError(
            "qualification requires a changed CognitiveProfile"
        )

    _assert_bound(before_state, before_lived, phase="before-swap")
    _assert_bound(after_state, after_lived, phase="after-swap")

    before_state_ref = self_state_ref(before_state)
    after_state_ref = self_state_ref(after_state)
    if before_state_ref != after_state_ref:
        raise ModelSwapContinuityError(
            "model swap mutated authoritative SelfState"
        )

    # Keep this explicit even though exact SelfState equality already implies it:
    # these are the continuity invariants whose preservation C31-G claims.
    invariants = (
        "self_id",
        "person_id",
        "person_revision",
        "personality_state_ref",
        "active_goal_refs",
        "active_intention_refs",
        "last_experience_ref",
    )
    for field in invariants:
        if getattr(before_state, field) != getattr(after_state, field):
            raise ModelSwapContinuityError(
                f"model swap changed continuity invariant: {field}"
            )

    from_ref = _ref("cognitive-profile", before)
    to_ref = _ref("cognitive-profile", after)
    capability_fields = (
        "reasoning_depth",
        "planning_capacity",
        "context_capacity_tokens",
        "multimodal_capacity",
        "tool_reasoning",
        "uncertainty_calibration",
    )
    capability_changed = any(
        getattr(before, field) != getattr(after, field)
        for field in capability_fields
    )

    before_continuity_ref = "lived-continuity:" + before_lived.continuity_loop_id
    after_continuity_ref = "lived-continuity:" + after_lived.continuity_loop_id
    seed = {
        "from": from_ref,
        "to": to_ref,
        "self_state_ref": before_state_ref,
        "before_continuity_ref": before_continuity_ref,
        "after_continuity_ref": after_continuity_ref,
    }

    return ModelSwapContinuityReceipt(
        schema="kaliv-consciousness-core/model-swap-continuity-receipt/v1",
        qualification_id="model-swap-" + hashlib.sha256(_json(seed)).hexdigest()[:32],
        from_cognitive_profile_ref=from_ref,
        to_cognitive_profile_ref=to_ref,
        cognitive_profile_changed=True,
        cognitive_capability_changed=capability_changed,
        self_id=before_state.self_id,
        person_id=before_state.person_id,
        person_revision=before_state.person_revision,
        self_state_ref=before_state_ref,
        before_continuity_ref=before_continuity_ref,
        after_continuity_ref=after_continuity_ref,
        personality_state_ref=before_state.personality_state_ref,
        durable_memory_binding_ref=before_state.last_experience_ref,
        identity_preserved=True,
        person_binding_preserved=True,
        self_state_preserved=True,
        durable_memory_binding_preserved=True,
        continuity_preserved=True,
        raw_chain_of_thought_persisted=False,
        identity_authority=False,
        persistent_state_authority=False,
        durable_memory_write_authority=False,
        execution_authority=False,
        scheduling_authority=False,
        model_authority=False,
        production_activation=False,
    )
