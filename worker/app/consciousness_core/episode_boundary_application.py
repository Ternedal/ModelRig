"""C30-G atomic process-local application of C30-F boundary decisions.

The application retains only the active successor episode and a bounded receipt.
Closed episode contents are not accumulated as a parallel autobiographical store.
"""
from __future__ import annotations

from typing import Annotated, Literal, Mapping, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .episode_boundary import (
    BoundaryDecision,
    EpisodeBoundaryPolicyDecision,
)
from .episodes import (
    ExperienceEpisodeState,
    close_experience_episode,
    experience_episode_ref,
    open_experience_episode,
)


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
TemporalAnchorId = Annotated[
    str,
    Field(pattern=r"^tanch-[a-f0-9]{32}$"),
]


class EpisodeBoundaryApplicationError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class EpisodeBoundaryApplicationReceipt(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/"
        "episode-boundary-application-receipt/v1"
    ]
    previous_episode_ref: NonEmptyRef
    decision: BoundaryDecision
    signal_ref: NonEmptyRef | None
    closed_episode_ref: NonEmptyRef | None
    next_episode_ref: NonEmptyRef | None
    boundary_anchor_id: TemporalAnchorId | None
    mutation_applied: bool
    closed_episode_contents_retained: Literal[False]
    model_calls: Literal[0]
    durable_memory_write_authority: Literal[False]
    self_state_store_write_applied: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    timer_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_shape(self) -> "EpisodeBoundaryApplicationReceipt":
        if self.decision == "KEEP":
            if (
                self.signal_ref is not None
                or self.closed_episode_ref is not None
                or self.next_episode_ref is not None
                or self.boundary_anchor_id is not None
                or self.mutation_applied
            ):
                raise ValueError(
                    "KEEP application receipt shape is invalid"
                )
        elif self.decision == "CLOSE_ONLY":
            if (
                self.signal_ref is None
                or self.closed_episode_ref is None
                or self.next_episode_ref is not None
                or self.boundary_anchor_id is None
                or not self.mutation_applied
            ):
                raise ValueError(
                    "CLOSE_ONLY application receipt shape is invalid"
                )
        else:
            if (
                self.signal_ref is None
                or self.closed_episode_ref is None
                or self.next_episode_ref is None
                or self.boundary_anchor_id is None
                or not self.mutation_applied
            ):
                raise ValueError(
                    "CLOSE_AND_ROTATE application receipt shape is invalid"
                )
        return self


class EpisodeBoundaryApplicationResult(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/episode-boundary-application/v1"
    ]
    active_episode: ExperienceEpisodeState | None
    receipt: EpisodeBoundaryApplicationReceipt
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_active_shape(self) -> "EpisodeBoundaryApplicationResult":
        if self.receipt.decision == "CLOSE_ONLY":
            if self.active_episode is not None:
                raise ValueError(
                    "CLOSE_ONLY application cannot retain active episode"
                )
        else:
            if self.active_episode is None:
                raise ValueError(
                    "KEEP/ROTATE application requires active episode"
                )
            if self.active_episode.phase != "ACTIVE":
                raise ValueError(
                    "boundary application active episode must be ACTIVE"
                )
            if (
                self.receipt.decision == "CLOSE_AND_ROTATE"
                and experience_episode_ref(self.active_episode)
                != self.receipt.next_episode_ref
            ):
                raise ValueError(
                    "rotated active episode/ref mismatch"
                )
        return self


def apply_episode_boundary_decision(
    episode: ExperienceEpisodeState | Mapping[str, Any],
    decision: EpisodeBoundaryPolicyDecision | Mapping[str, Any],
) -> EpisodeBoundaryApplicationResult:
    """Apply one exact C30-F decision without sampling time or persisting state."""
    try:
        current = (
            episode
            if isinstance(episode, ExperienceEpisodeState)
            else ExperienceEpisodeState.model_validate(episode)
        )
        policy = (
            decision
            if isinstance(decision, EpisodeBoundaryPolicyDecision)
            else EpisodeBoundaryPolicyDecision.model_validate(decision)
        )
    except ValidationError as exc:
        raise EpisodeBoundaryApplicationError(
            "invalid episode boundary application input"
        ) from exc

    if current.phase != "ACTIVE":
        raise EpisodeBoundaryApplicationError(
            "boundary application requires ACTIVE episode"
        )
    current_ref = experience_episode_ref(current)
    if policy.episode_ref != current_ref:
        raise EpisodeBoundaryApplicationError(
            "boundary decision belongs to another episode"
        )

    if policy.decision == "KEEP":
        receipt = EpisodeBoundaryApplicationReceipt(
            schema=(
                "kaliv-consciousness-core/"
                "episode-boundary-application-receipt/v1"
            ),
            previous_episode_ref=current_ref,
            decision="KEEP",
            signal_ref=None,
            closed_episode_ref=None,
            next_episode_ref=None,
            boundary_anchor_id=None,
            mutation_applied=False,
            closed_episode_contents_retained=False,
            model_calls=0,
            durable_memory_write_authority=False,
            self_state_store_write_applied=False,
            execution_authority=False,
            scheduling_authority=False,
            timer_authority=False,
            production_activation=False,
        )
        return EpisodeBoundaryApplicationResult(
            schema=(
                "kaliv-consciousness-core/"
                "episode-boundary-application/v1"
            ),
            active_episode=current,
            receipt=receipt,
            production_activation=False,
        )

    if (
        policy.boundary_anchor is None
        or policy.close_reason is None
        or policy.signal_ref is None
    ):
        raise EpisodeBoundaryApplicationError(
            "boundary mutation is missing exact close evidence"
        )

    closed = close_experience_episode(
        current,
        closing_anchor=policy.boundary_anchor,
        reason=policy.close_reason,
    )
    closed_ref = experience_episode_ref(closed)

    next_episode = None
    next_ref = None
    if policy.decision == "CLOSE_AND_ROTATE":
        if policy.next_open_reason is None:
            raise EpisodeBoundaryApplicationError(
                "rotation is missing next open reason"
            )
        next_episode = open_experience_episode(
            self_id=current.self_id,
            person_revision=current.person_revision,
            opening_anchor=policy.boundary_anchor,
            reason=policy.next_open_reason,
        )
        next_ref = experience_episode_ref(next_episode)

    receipt = EpisodeBoundaryApplicationReceipt(
        schema=(
            "kaliv-consciousness-core/"
            "episode-boundary-application-receipt/v1"
        ),
        previous_episode_ref=current_ref,
        decision=policy.decision,
        signal_ref=policy.signal_ref,
        closed_episode_ref=closed_ref,
        next_episode_ref=next_ref,
        boundary_anchor_id=policy.boundary_anchor.anchor_id,
        mutation_applied=True,
        closed_episode_contents_retained=False,
        model_calls=0,
        durable_memory_write_authority=False,
        self_state_store_write_applied=False,
        execution_authority=False,
        scheduling_authority=False,
        timer_authority=False,
        production_activation=False,
    )
    return EpisodeBoundaryApplicationResult(
        schema=(
            "kaliv-consciousness-core/"
            "episode-boundary-application/v1"
        ),
        active_episode=next_episode,
        receipt=receipt,
        production_activation=False,
    )
