"""C29-M post-recovery wake-artifact retirement for model context only.

Authoritative Core models are not mutated. The function returns a deep-copied
model-context payload with exact wake-specific observations/candidates removed
only after C29-K proves the session is ORIENTED.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping

from .continuity import (
    PostWakeContinuityState,
    post_wake_continuity_state_ref,
)
from .continuity_orientation import ContinuityOrientationState


class ContinuityContextRetirementError(RuntimeError):
    pass


def retire_wake_artifacts_from_model_context(
    context: Mapping[str, Any],
    *,
    continuity_state: PostWakeContinuityState,
    orientation: ContinuityOrientationState,
) -> dict[str, Any]:
    """Return model-visible context with only exact wake artifacts retired."""
    if not isinstance(context, Mapping):
        raise TypeError("context must be a mapping")
    if not isinstance(continuity_state, PostWakeContinuityState):
        raise TypeError("continuity_state must be PostWakeContinuityState")
    if not isinstance(orientation, ContinuityOrientationState):
        raise TypeError("orientation must be ContinuityOrientationState")
    if orientation.phase != "ORIENTED":
        raise ContinuityContextRetirementError(
            "wake artifacts may retire only after ORIENTED"
        )
    continuity_ref = post_wake_continuity_state_ref(continuity_state)
    if orientation.continuity_state_ref != continuity_ref:
        raise ContinuityContextRetirementError(
            "orientation belongs to another continuity state"
        )
    if not orientation.reorientation_complete:
        raise ContinuityContextRetirementError(
            "orientation does not prove completed reorientation"
        )

    payload = copy.deepcopy(dict(context))
    retirement_refs = {
        continuity_state.wake_receipt_ref,
        continuity_ref,
    }

    world = payload.get("world_state")
    if not isinstance(world, dict):
        raise ContinuityContextRetirementError(
            "model context has no world_state mapping"
        )
    observations = world.get("observations")
    if not isinstance(observations, list):
        raise ContinuityContextRetirementError(
            "model context world_state has no observations list"
        )

    kept_observations: list[Any] = []
    for item in observations:
        if not isinstance(item, dict):
            raise ContinuityContextRetirementError(
                "model context observation is not a mapping"
            )
        source_refs = item.get("source_refs")
        if not isinstance(source_refs, list):
            raise ContinuityContextRetirementError(
                "model context observation has invalid source_refs"
            )
        if retirement_refs.intersection(source_refs):
            continue
        kept_observations.append(item)
    world["observations"] = kept_observations

    workspace = payload.get("workspace")
    if not isinstance(workspace, dict):
        raise ContinuityContextRetirementError(
            "model context has no workspace mapping"
        )
    candidates = workspace.get("candidates")
    selected = workspace.get("selected_candidate_ids")
    if not isinstance(candidates, list) or not isinstance(selected, list):
        raise ContinuityContextRetirementError(
            "model context workspace has invalid candidate data"
        )

    kept_candidates: list[Any] = []
    removed_candidate_ids: set[str] = set()
    for item in candidates:
        if not isinstance(item, dict):
            raise ContinuityContextRetirementError(
                "model context candidate is not a mapping"
            )
        if item.get("source_ref") in retirement_refs:
            candidate_id = item.get("candidate_id")
            if isinstance(candidate_id, str):
                removed_candidate_ids.add(candidate_id)
            continue
        kept_candidates.append(item)

    workspace["candidates"] = kept_candidates
    workspace["selected_candidate_ids"] = [
        candidate_id
        for candidate_id in selected
        if candidate_id not in removed_candidate_ids
    ]

    # The explicit C29-F projection must already be absent after C29-I.
    # Fail closed rather than silently retaining contradictory wake context.
    if payload.get("continuity") is not None:
        raise ContinuityContextRetirementError(
            "ORIENTED model context still carries active continuity projection"
        )
    payload.pop("continuity", None)

    return payload
