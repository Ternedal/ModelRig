"""C30-H bounded episode-closure evidence for optional memory review.

Closed experiential episodes are reduced to reference-level evidence only. This
module never persists raw user text, model chain-of-thought, or the closed
episode itself, and it grants no durable-memory authority.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .episodes import (
    EpisodeCloseReason,
    EpisodeMomentKind,
    EpisodeOpenReason,
    ExperienceEpisodeState,
    experience_episode_ref,
)


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
UnitInterval = Annotated[
    float,
    Field(ge=0.0, le=1.0, strict=True, allow_inf_nan=False),
]
NonNegativeInt = Annotated[int, Field(ge=0, strict=True)]
TemporalAnchorId = Annotated[
    str,
    Field(pattern=r"^tanch-[a-f0-9]{32}$"),
]


class EpisodeClosureEvidenceError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class EpisodeKindCount(StrictModel):
    kind: EpisodeMomentKind
    count: Annotated[int, Field(ge=1, le=128, strict=True)]


class EpisodeClosureEvidence(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/episode-closure-evidence/v1"
    ]
    evidence_id: Annotated[
        str,
        Field(pattern=r"^ecev-[a-f0-9]{32}$"),
    ]
    closed_episode_ref: NonEmptyRef
    boundary_signal_ref: NonEmptyRef
    self_id: Annotated[
        str,
        Field(pattern=r"^self-[a-f0-9]{32}$"),
    ]
    person_revision: Annotated[
        str,
        Field(pattern=r"^person-r[0-9]{4,}$"),
    ]
    open_reason: EpisodeOpenReason
    close_reason: EpisodeCloseReason
    opened_anchor_id: TemporalAnchorId
    closed_anchor_id: TemporalAnchorId
    opened_sequence: NonNegativeInt
    closed_sequence: NonNegativeInt
    objective_elapsed_ms: NonNegativeInt
    total_moment_count: NonNegativeInt
    evicted_moment_count: NonNegativeInt
    retained_moment_count: Annotated[
        int,
        Field(ge=0, le=128, strict=True),
    ]
    retained_kind_counts: Annotated[
        list[EpisodeKindCount],
        Field(max_length=8),
    ]
    salient_source_refs: Annotated[
        list[NonEmptyRef],
        Field(max_length=16),
    ]
    participant_refs: Annotated[
        list[NonEmptyRef],
        Field(max_length=32),
    ]
    active_goal_refs: Annotated[
        list[NonEmptyRef],
        Field(max_length=64),
    ]
    max_retained_salience: UnitInterval
    memory_review_disposition: Literal[
        "NO_MOMENTS",
        "REFERENCE_EVIDENCE_ONLY",
    ]
    raw_text_included: Literal[False]
    raw_chain_of_thought_included: Literal[False]
    closed_episode_contents_retained: Literal[False]
    experience_candidate_created: Literal[False]
    durable_memory_write_authority: Literal[False]
    self_state_store_write_applied: Literal[False]
    model_calls: Literal[0]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    timer_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_shape(self) -> "EpisodeClosureEvidence":
        if self.total_moment_count != (
            self.evicted_moment_count + self.retained_moment_count
        ):
            raise ValueError(
                "episode closure evidence moment accounting is inconsistent"
            )
        if self.closed_sequence < self.opened_sequence:
            raise ValueError(
                "episode closure evidence sequence moved backwards"
            )
        if len(self.salient_source_refs) != len(
            set(self.salient_source_refs)
        ):
            raise ValueError(
                "episode closure salient source refs must be unique"
            )
        if len(self.participant_refs) != len(set(self.participant_refs)):
            raise ValueError(
                "episode closure participant refs must be unique"
            )
        if len(self.active_goal_refs) != len(set(self.active_goal_refs)):
            raise ValueError(
                "episode closure goal refs must be unique"
            )
        if len(self.retained_kind_counts) != len(
            {item.kind for item in self.retained_kind_counts}
        ):
            raise ValueError(
                "episode closure retained kind counts must be unique"
            )
        expected = (
            "NO_MOMENTS"
            if self.total_moment_count == 0
            else "REFERENCE_EVIDENCE_ONLY"
        )
        if self.memory_review_disposition != expected:
            raise ValueError(
                "episode closure memory review disposition is invalid"
            )
        return self


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


def episode_closure_evidence_ref(
    evidence: EpisodeClosureEvidence,
) -> str:
    if not isinstance(evidence, EpisodeClosureEvidence):
        raise TypeError("evidence must be EpisodeClosureEvidence")
    return "episode-closure-evidence:" + _digest(evidence)


def _unique_refs(values: list[str], limit: int) -> list[str]:
    return list(dict.fromkeys(values))[:limit]


def derive_episode_closure_evidence(
    episode: ExperienceEpisodeState | Mapping[str, Any],
    *,
    boundary_signal_ref: str,
) -> EpisodeClosureEvidence:
    """Reduce one CLOSED episode to bounded reference-only closure evidence."""
    try:
        closed = (
            episode
            if isinstance(episode, ExperienceEpisodeState)
            else ExperienceEpisodeState.model_validate(episode)
        )
    except ValidationError as exc:
        raise EpisodeClosureEvidenceError(
            "invalid closed experience episode"
        ) from exc

    if closed.phase != "CLOSED":
        raise EpisodeClosureEvidenceError(
            "episode closure evidence requires CLOSED episode"
        )
    if closed.closed_anchor is None or closed.close_reason is None:
        raise EpisodeClosureEvidenceError(
            "closed episode is missing closure evidence"
        )

    opened_ms = closed.opened_anchor.monotonic_ms
    closed_ms = closed.closed_anchor.monotonic_ms
    if opened_ms is None or closed_ms is None:
        raise EpisodeClosureEvidenceError(
            "episode closure evidence requires monotonic anchors"
        )
    if closed_ms < opened_ms:
        raise EpisodeClosureEvidenceError(
            "episode closure monotonic time moved backwards"
        )

    kind_counts = Counter(moment.kind for moment in closed.moments)
    retained_kind_counts = [
        EpisodeKindCount(kind=kind, count=kind_counts[kind])
        for kind in sorted(kind_counts)
    ]

    ranked_moments = sorted(
        closed.moments,
        key=lambda moment: (
            -moment.salience,
            moment.anchor.sequence,
            moment.source_ref,
        ),
    )
    salient_source_refs = _unique_refs(
        [moment.source_ref for moment in ranked_moments],
        16,
    )
    participant_refs = _unique_refs(
        [
            ref
            for moment in closed.moments
            for ref in moment.participant_refs
        ],
        32,
    )
    active_goal_refs = _unique_refs(
        [
            ref
            for moment in closed.moments
            for ref in moment.active_goal_refs
        ],
        64,
    )
    max_salience = max(
        (moment.salience for moment in closed.moments),
        default=0.0,
    )

    closed_ref = experience_episode_ref(closed)
    seed = {
        "closed_episode_ref": closed_ref,
        "boundary_signal_ref": boundary_signal_ref,
        "closed_anchor_id": closed.closed_anchor.anchor_id,
    }
    try:
        return EpisodeClosureEvidence(
            schema=(
                "kaliv-consciousness-core/"
                "episode-closure-evidence/v1"
            ),
            evidence_id="ecev-" + _digest(seed)[:32],
            closed_episode_ref=closed_ref,
            boundary_signal_ref=boundary_signal_ref,
            self_id=closed.self_id,
            person_revision=closed.person_revision,
            open_reason=closed.open_reason,
            close_reason=closed.close_reason,
            opened_anchor_id=closed.opened_anchor.anchor_id,
            closed_anchor_id=closed.closed_anchor.anchor_id,
            opened_sequence=closed.opened_anchor.sequence,
            closed_sequence=closed.closed_anchor.sequence,
            objective_elapsed_ms=closed_ms - opened_ms,
            total_moment_count=closed.moment_count,
            evicted_moment_count=closed.evicted_moment_count,
            retained_moment_count=len(closed.moments),
            retained_kind_counts=retained_kind_counts,
            salient_source_refs=salient_source_refs,
            participant_refs=participant_refs,
            active_goal_refs=active_goal_refs,
            max_retained_salience=max_salience,
            memory_review_disposition=(
                "NO_MOMENTS"
                if closed.moment_count == 0
                else "REFERENCE_EVIDENCE_ONLY"
            ),
            raw_text_included=False,
            raw_chain_of_thought_included=False,
            closed_episode_contents_retained=False,
            experience_candidate_created=False,
            durable_memory_write_authority=False,
            self_state_store_write_applied=False,
            model_calls=0,
            execution_authority=False,
            scheduling_authority=False,
            timer_authority=False,
            production_activation=False,
        )
    except ValidationError as exc:
        raise EpisodeClosureEvidenceError(
            "invalid episode closure evidence"
        ) from exc
