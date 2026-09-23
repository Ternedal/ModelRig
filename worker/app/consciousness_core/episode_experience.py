"""C30-H bounded episode-closure projection into the existing C7 review seam.

This module creates ExperienceCandidate metadata only. It never calls Memory 4
write authority and never copies episode text because C30 episodes contain refs.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel

from .cycle import self_state_ref
from .episode_boundary_application import (
    EpisodeBoundaryApplicationReceipt,
    episode_boundary_application_receipt_ref,
)
from .episodes import ExperienceEpisodeState, experience_episode_ref
from .experience import ExperienceCandidate
from .self_state import PersistentSelfState


class EpisodeExperienceCandidateError(RuntimeError):
    pass


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


def build_episode_experience_candidate(
    *,
    episode: ExperienceEpisodeState,
    application_receipt: EpisodeBoundaryApplicationReceipt,
    state: PersistentSelfState,
    cycle_id: str,
) -> ExperienceCandidate:
    """Create one review-only C7 candidate from an exact C30 closure."""
    if not isinstance(episode, ExperienceEpisodeState):
        raise TypeError("episode must be ExperienceEpisodeState")
    if not isinstance(
        application_receipt,
        EpisodeBoundaryApplicationReceipt,
    ):
        raise TypeError(
            "application_receipt must be EpisodeBoundaryApplicationReceipt"
        )
    if not isinstance(state, PersistentSelfState):
        raise TypeError("state must be PersistentSelfState")
    if episode.phase != "ACTIVE":
        raise EpisodeExperienceCandidateError(
            "candidate requires the exact pre-close ACTIVE episode"
        )
    if not application_receipt.mutation_applied:
        raise EpisodeExperienceCandidateError(
            "KEEP boundary cannot create episode experience candidate"
        )

    episode_ref = experience_episode_ref(episode)
    if application_receipt.previous_episode_ref != episode_ref:
        raise EpisodeExperienceCandidateError(
            "boundary receipt belongs to another episode"
        )
    if application_receipt.closed_episode_ref is None:
        raise EpisodeExperienceCandidateError(
            "boundary receipt has no closed episode ref"
        )
    if state.self_id != episode.self_id:
        raise EpisodeExperienceCandidateError(
            "episode belongs to another self"
        )
    if state.person_revision != episode.person_revision:
        raise EpisodeExperienceCandidateError(
            "episode belongs to another Person Revision"
        )

    participants: list[str] = []
    goals: list[str] = []
    world_refs: list[str] = []
    prediction_error_refs: list[str] = []
    moment_source_refs: list[str] = []
    for moment in episode.moments:
        for ref in moment.participant_refs:
            if ref not in participants:
                participants.append(ref)
        for ref in moment.active_goal_refs:
            if ref not in goals:
                goals.append(ref)
        if moment.source_ref not in moment_source_refs:
            moment_source_refs.append(moment.source_ref)
        if moment.kind in {"WORLD_EVIDENCE", "USER_TURN"}:
            if moment.source_ref not in world_refs:
                world_refs.append(moment.source_ref)
        if moment.kind == "PREDICTION_RESOLUTION":
            if moment.source_ref not in prediction_error_refs:
                prediction_error_refs.append(moment.source_ref)

    if not goals:
        goals = list(state.active_goal_refs)

    application_ref = episode_boundary_application_receipt_ref(
        application_receipt
    )
    source_refs = [
        application_receipt.closed_episode_ref,
        application_ref,
    ]
    if application_receipt.signal_ref is not None:
        source_refs.append(application_receipt.signal_ref)
    for ref in moment_source_refs:
        if ref not in source_refs:
            source_refs.append(ref)
        if len(source_refs) >= 64:
            break

    significance = max(
        (moment.salience for moment in episode.moments),
        default=0.0,
    )
    state_ref = self_state_ref(state)
    seed = {
        "closed_episode_ref": application_receipt.closed_episode_ref,
        "application_ref": application_ref,
        "self_state_ref": state_ref,
        "cycle_id": cycle_id,
    }

    return ExperienceCandidate(
        schema="kaliv-consciousness-core/experience-candidate/v1",
        experience_id="exp-" + _digest(seed)[:32],
        cycle_id=cycle_id,
        self_id=state.self_id,
        person_id=state.person_id,
        person_revision=state.person_revision,
        kind="EXPERIENTIAL_EPISODE",
        event_ref=application_receipt.closed_episode_ref,
        participant_refs=participants[:32],
        self_state_before_ref=state_ref,
        self_state_after_ref=state_ref,
        active_goal_refs=goals[:64],
        intention_ref=None,
        prediction_refs=[],
        outcome_refs=[],
        prediction_error_refs=prediction_error_refs[:32],
        personality_state_ref=state.personality_state_ref,
        world_state_delta_refs=world_refs[:64],
        significance=significance,
        provenance_kind="core_episode",
        sensitivity="private",
        source_refs=source_refs[:64],
        completed_turn_source_ref=None,
        production_activation=False,
    )
