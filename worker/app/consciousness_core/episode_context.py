"""C30-E bounded current-episode projection for replaceable cognition.

The projection is advisory reference data only. It deliberately excludes raw
text, durable-memory contents, model interpretation and chain-of-thought.
"""
from __future__ import annotations

from typing import Annotated, Literal, Mapping, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .episodes import (
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


class EpisodeContextError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class EpisodeContextMoment(StrictModel):
    kind: EpisodeMomentKind
    source_ref: NonEmptyRef
    salience: UnitInterval
    participant_refs: Annotated[
        list[NonEmptyRef],
        Field(max_length=32),
    ]
    temporal_sequence: NonNegativeInt

    @model_validator(mode="after")
    def unique_participants(self) -> "EpisodeContextMoment":
        if len(self.participant_refs) != len(set(self.participant_refs)):
            raise ValueError("episode context participants must be unique")
        return self


class EpisodeContextProjection(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/episode-context-projection/v1"
    ]
    episode_ref: NonEmptyRef
    phase: Literal["ACTIVE", "CLOSED"]
    open_reason: EpisodeOpenReason
    total_moment_count: NonNegativeInt
    evicted_moment_count: NonNegativeInt
    retained_moment_count: Annotated[
        int,
        Field(ge=0, le=128, strict=True),
    ]
    objective_elapsed_ms: NonNegativeInt
    recent_moments: Annotated[
        list[EpisodeContextMoment],
        Field(max_length=16),
    ]
    raw_text_included: Literal[False]
    raw_chain_of_thought_included: Literal[False]
    identity_authority: Literal[False]
    persistent_state_authority: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_accounting(self) -> "EpisodeContextProjection":
        if self.total_moment_count != (
            self.evicted_moment_count + self.retained_moment_count
        ):
            raise ValueError(
                "episode context moment accounting is inconsistent"
            )
        if len(self.recent_moments) > self.retained_moment_count:
            raise ValueError(
                "episode context recent moments exceed retained moments"
            )
        return self


def project_episode_context(
    episode: ExperienceEpisodeState | Mapping[str, Any],
) -> EpisodeContextProjection:
    """Project only bounded reference-level current-episode semantics."""
    try:
        value = (
            episode
            if isinstance(episode, ExperienceEpisodeState)
            else ExperienceEpisodeState.model_validate(episode)
        )
    except ValidationError as exc:
        raise EpisodeContextError(
            "invalid ExperienceEpisodeState"
        ) from exc

    opened_monotonic = value.opened_anchor.monotonic_ms
    if opened_monotonic is None:
        raise EpisodeContextError(
            "episode opening has no monotonic time"
        )
    latest_anchor = (
        value.moments[-1].anchor
        if value.moments
        else value.opened_anchor
    )
    latest_monotonic = latest_anchor.monotonic_ms
    if latest_monotonic is None:
        raise EpisodeContextError(
            "episode latest anchor has no monotonic time"
        )
    if latest_monotonic < opened_monotonic:
        raise EpisodeContextError(
            "episode elapsed time moved backwards"
        )

    recent = [
        EpisodeContextMoment(
            kind=moment.kind,
            source_ref=moment.source_ref,
            salience=moment.salience,
            participant_refs=list(moment.participant_refs),
            temporal_sequence=moment.anchor.sequence,
        )
        for moment in value.moments[-16:]
    ]

    return EpisodeContextProjection(
        schema=(
            "kaliv-consciousness-core/"
            "episode-context-projection/v1"
        ),
        episode_ref=experience_episode_ref(value),
        phase=value.phase,
        open_reason=value.open_reason,
        total_moment_count=value.moment_count,
        evicted_moment_count=value.evicted_moment_count,
        retained_moment_count=len(value.moments),
        objective_elapsed_ms=latest_monotonic - opened_monotonic,
        recent_moments=recent,
        raw_text_included=False,
        raw_chain_of_thought_included=False,
        identity_authority=False,
        persistent_state_authority=False,
        durable_memory_write_authority=False,
        execution_authority=False,
        scheduling_authority=False,
        production_activation=False,
    )
